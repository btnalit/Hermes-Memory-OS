#!/usr/bin/env python3
"""Read-only RAGFlow external evidence observation probe.

This script is primarily a boundary/health probe for using RAGFlow as
external evidence.  When invoked with ``--intake <indices> --execute``,
it bridges specific chunks into the tainted intake pipeline via
``external_intake()``.  Without ``--execute``, intake is a dry-run
report-only path — no canonical writes occur.

The ``--intake`` path is manual-only (never cron), requires
``--execute`` to actually write, and each intake is audited through
the ExecutionGate envelope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_self = Path(__file__).absolute()
_repo_root = _self.parents[1]


def _preparse_cli_arg(argv: list[str], flag: str) -> str:
    """Extract a --flag value from raw argv before argparse runs."""
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return ""


# Resolve HERMES_HOME at module level — CLI > env > default.
_CLI_HOME = _preparse_cli_arg(sys.argv, "--hermes-home")
_ENV_HOME = os.environ.get("HERMES_HOME", "")
_HERMES_HOME = _CLI_HOME or _ENV_HOME or str(Path.home() / ".hermes")

if (_repo_root / "plugins" / "seam" / "external_evidence").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.seam.external_evidence.config import get_provider_config, load_seam_config


def _canonical_hashes(hermes_home: str | Path) -> dict[str, str]:
    root = Path(hermes_home) / "memory-os" / "crystallized"
    hashes: dict[str, str] = {}
    if not root.exists():
        return hashes
    for path in sorted(root.glob("*.md")):
        try:
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
    return hashes


def _redacted_provider_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(config.get("enabled")),
        "base_url": str(config.get("base_url") or ""),
        "api_key_file": "[REDACTED]" if config.get("api_key_file") else "",
        "dataset_id": str(config.get("dataset_id") or ""),
    }


def _read_api_key(path: str) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _search_ragflow_http(config: dict[str, Any], query: str, *, top_k: int, timeout: float) -> list[dict[str, Any]]:
    """Best-effort direct RAGFlow search.

    The local MCP path remains the preferred interactive retrieval surface;
    this HTTP helper is intentionally fail-open so API drift cannot affect
    Memory-OS operations.
    """
    base_url = str(config.get("base_url") or "").rstrip("/")
    dataset_id = str(config.get("dataset_id") or "")
    api_key = _read_api_key(str(config.get("api_key_file") or ""))
    if not base_url or not dataset_id or not api_key:
        return []

    import urllib.error
    import urllib.request

    attempts = [
        (f"{base_url}/api/v1/retrieval", {"question": query, "dataset_ids": [dataset_id], "page_size": top_k}),
        (f"{base_url}/api/v1/datasets/{dataset_id}/documents/search", {"query": query, "top_k": top_k}),
    ]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for url, body in attempts:
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                method="POST",
                headers=headers,
            )
            response = urllib.request.urlopen(req, timeout=timeout)
            data = json.loads(response.read().decode("utf-8"))
            chunks = _extract_chunks(data)
            if chunks:
                return chunks[:top_k]
        except Exception:
            continue
    return []


def _extract_chunks(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    candidates: Any = data.get("chunks")
    if candidates is None and isinstance(data.get("data"), dict):
        candidates = data["data"].get("chunks") or data["data"].get("documents")
    if candidates is None:
        candidates = data.get("data") if isinstance(data.get("data"), list) else []
    if not isinstance(candidates, list):
        return []
    chunks: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or item.get("text") or "").strip()
        if not content:
            continue
        chunks.append({
            "content_preview": content[:240],
            "dataset_id": str(item.get("dataset_id") or ""),
            "document_id": str(item.get("document_id") or item.get("id") or ""),
            "chunk_id": str(item.get("chunk_id") or item.get("id") or ""),
            "similarity": item.get("similarity") or item.get("score"),
            "source_class": "external_evidence",
            "provider": "ragflow",
            "owner_approved_memory": False,
        })
    return chunks


def probe(
    hermes_home: str | Path,
    *,
    query: str,
    top_k: int = 5,
    timeout: float = 5.0,
    override_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before = _canonical_hashes(hermes_home)
    config_root = load_seam_config(hermes_home)
    provider_config = get_provider_config(config_root, "ragflow")
    if override_config:
        provider_config.update({
            key: value for key, value in override_config.items()
            if key in {"enabled", "base_url", "api_key_file", "dataset_id"}
            and value not in (None, "")
        })
        provider_config["enabled"] = bool(provider_config.get("enabled"))
    t0 = time.monotonic()
    chunks: list[dict[str, Any]] = []
    status = "disabled"
    reason = "provider_disabled"

    if provider_config.get("enabled"):
        chunks = _search_ragflow_http(provider_config, query, top_k=top_k, timeout=timeout)
        status = "ok" if chunks else "no_results_or_unreachable"
        reason = "ok" if chunks else "fail_open_empty_results"

    after = _canonical_hashes(hermes_home)
    return {
        "schema_version": "memory-os.ragflow_readonly_probe.v0",
        "status": status,
        "reason": reason,
        "mode": "read_only_external_evidence",
        "provider": "ragflow",
        "query": query,
        "config": _redacted_provider_config(provider_config),
        "result_count": len(chunks),
        "results": chunks,
        "contains_external_evidence": True,
        "memory_write_allowed": False,
        "crystallization_allowed": False,
        "canonical_unchanged": before == after,
        "canonical_hash_count": len(after),
        "latency_ms": int((time.monotonic() - t0) * 1000),
    }


def _parse_intake_indices(raw: str) -> list[int]:
    """Parse comma-separated intake indices (e.g. '0,2')."""
    if not raw or not raw.strip():
        return []
    indices: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            indices.append(int(part))
        except ValueError:
            continue
    return indices


def _intake_chunk(
    hermes_home: str | Path,
    chunk: dict[str, Any],
    *,
    provider: str = "ragflow",
) -> dict[str, Any]:
    """Bridge one chunk into the tainted intake pipeline.

    Returns an intake result dict with ``event_id`` on success or
    ``error`` on failure.  Requires MemoryOSStore initialization.
    """
    from plugins.memory.memory_os.external_intake import external_intake
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    content = str(chunk.get("content_preview") or chunk.get("content") or "")
    doc_id = str(chunk.get("document_id") or "")
    chunk_id = str(chunk.get("chunk_id") or "")
    external_ref = f"ragflow:{doc_id}:{chunk_id}" if doc_id else ""

    if not content.strip() or not external_ref:
        return {"index": chunk.get("_index", -1), "error": "empty_content_or_ref", "intake": "skipped"}

    try:
        roots = MemoryOSRoots.from_hermes_home(str(hermes_home))
        store = MemoryOSStore(roots)
        store.initialize()
        event_id = external_intake(
            store,
            content=content,
            external_ref=external_ref,
            provider=provider,
            metadata={
                "dataset_id": str(chunk.get("dataset_id", "")),
                "similarity": chunk.get("similarity"),
                "intake_source": "ragflow_readonly_probe",
            },
        )
        return {"index": chunk.get("_index", -1), "event_id": event_id, "intake": "ok"}
    except ValueError as exc:
        return {"index": chunk.get("_index", -1), "error": str(exc), "intake": "rejected"}
    except Exception as exc:
        return {"index": chunk.get("_index", -1), "error": str(exc), "intake": "failed"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="RAGFlow external evidence observation probe with optional tainted intake.",
    )
    parser.add_argument("--hermes-home", default=_HERMES_HOME)
    parser.add_argument("--query", default="Memory-OS RAGFlow external evidence boundary")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--enable-for-probe",
        action="store_true",
        help="Temporarily enable the provider for this invocation only; does not write config.",
    )
    parser.add_argument("--base-url", default="", help="Ephemeral RAGFlow base URL override")
    parser.add_argument("--dataset-id", default="", help="Ephemeral RAGFlow dataset ID override")
    parser.add_argument("--api-key-file", default="", help="Ephemeral API key file override (redacted in output)")
    parser.add_argument("--output", choices=("json",), default="json")
    parser.add_argument(
        "--intake",
        default="",
        help="Comma-separated chunk indices to intake as tainted evidence (e.g. '0,2'). Requires --execute.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform intake. Without this flag, --intake is dry-run only.",
    )
    args = parser.parse_args(argv)

    override = None
    if args.enable_for_probe or args.base_url or args.dataset_id or args.api_key_file:
        override = {
            "enabled": bool(args.enable_for_probe),
            "base_url": args.base_url,
            "dataset_id": args.dataset_id,
            "api_key_file": args.api_key_file,
        }
    report = probe(
        args.hermes_home,
        query=args.query,
        top_k=args.top_k,
        timeout=args.timeout,
        override_config=override,
    )

    # ── Phase 4: Tainted intake bridging ────────────────────────────────
    intake_indices = _parse_intake_indices(args.intake)
    intake_results: list[dict[str, Any]] = []
    if intake_indices:
        results = report.get("results", [])
        for idx in intake_indices:
            if 0 <= idx < len(results):
                chunk = dict(results[idx])
                chunk["_index"] = idx
                if args.execute:
                    intake_results.append(_intake_chunk(args.hermes_home, chunk))
                else:
                    intake_results.append({
                        "index": idx,
                        "external_ref": f"ragflow:{chunk.get('document_id', '')}:{chunk.get('chunk_id', '')}",
                        "intake": "dry_run",
                        "note": "Use --execute to actually perform intake",
                    })
        report["intake"] = {
            "requested_indices": intake_indices,
            "executed": args.execute,
            "results": intake_results,
        }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("canonical_unchanged") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
