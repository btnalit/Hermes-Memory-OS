"""Lossless task-local symbolic offloader for V7 L4."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.audit import append_audit
from plugins.memory.memory_os.jsonl_io import append_jsonl, read_jsonl


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def symbolic_offloader_manifest() -> dict[str, Any]:
    return {
        "name": "symbolic_offloader",
        "kind": "context",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {"required": ["memory_os >=0.1.0"], "optional": []},
        "provides": {
            "commands": ["status", "doctor", "offload-entries", "recall-node"],
            "schedules": [],
            "reads": ["task_local.tool_output"],
            "writes": ["local_artifact.symbolic_offloader"],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "profile_scope": "per-profile",
        },
    }


class SymbolicOffloaderModule:
    """Move verbose task-local text into exact refs and keep node ids in context."""

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "symbolic_offloader"

    @property
    def refs_root(self) -> Path:
        return self.module_root / "refs"

    @property
    def reports_path(self) -> Path:
        return self.module_root / "reports.jsonl"

    @property
    def audit_path(self) -> Path:
        return self.module_root / "audit.jsonl"

    def offload_entries(
        self,
        *,
        task_id: str,
        entries: list[dict[str, Any]],
        token_budget: int | None = None,
        write: bool = True,
    ) -> dict[str, Any]:
        safe_task_id = _safe_id(task_id, "task_id")
        nodes = [
            self._build_node(safe_task_id, entry, index=index)
            for index, entry in enumerate(entries, start=1)
        ]
        result = {
            "schema_version": "memory-os.symbolic_offload_result.v0",
            "module": "symbolic_offloader",
            "profile": self.profile,
            "task_id": safe_task_id,
            "status": "ok",
            "offloaded_count": len(nodes),
            "pressure_tier": _pressure_tier(sum(int(node["estimated_tokens"]) for node in nodes), token_budget),
            "nodes": nodes,
            "mermaid": _mermaid(nodes),
            "actual_send": False,
            "actual_execute": False,
            "canonical_state_changed": False,
            "live_behavior_changed": False,
        }
        if write:
            for node in nodes:
                path = self.hermes_home / str(node["ref"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(node["text"]), encoding="utf-8")
                node.pop("text", None)
            append_jsonl(self.reports_path, result)
        else:
            for node in nodes:
                node.pop("text", None)
        return result

    def recall_node(self, task_id: str, node_id: str) -> dict[str, Any]:
        safe_task_id = _safe_id(task_id, "task_id")
        safe_node_id = _safe_id(node_id, "node_id")
        path = self.refs_root / safe_task_id / f"{safe_node_id}.md"
        text = path.read_text(encoding="utf-8")
        checksum = _sha256(text)
        append_audit(
            self.audit_path,
            action="offload_node_recalled",
            status="ok",
            target=f"{safe_task_id}/{safe_node_id}",
            details={"checksum": checksum, "char_count": len(text)},
        )
        return {
            "schema_version": "memory-os.symbolic_offload_recall.v0",
            "module": "symbolic_offloader",
            "profile": self.profile,
            "task_id": safe_task_id,
            "node_id": safe_node_id,
            "text": text,
            "checksum": checksum,
            "actual_send": False,
            "actual_execute": False,
            "canonical_state_changed": False,
        }

    def status(self) -> dict[str, Any]:
        reports = read_jsonl(self.reports_path)
        ref_count = len(list(self.refs_root.glob("*/*.md"))) if self.refs_root.exists() else 0
        return {
            "schema_version": "memory-os.symbolic_offloader_status.v0",
            "module": "symbolic_offloader",
            "profile": self.profile,
            "status": "ok" if reports or ref_count else "missing",
            "report_count": len(reports),
            "ref_count": ref_count,
            "actual_send": False,
            "actual_execute": False,
            "canonical_state_changed": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings = []
        reports = read_jsonl(self.reports_path)
        missing_refs = []
        for report in reports:
            for node in report.get("nodes") or []:
                ref = str(node.get("ref") or "")
                if ref and not (self.hermes_home / ref).exists():
                    missing_refs.append(ref)
        if missing_refs:
            findings.append(
                {
                    "severity": "error",
                    "code": "offload_ref_missing",
                    "message": "SymbolicOffloader report references missing ref files.",
                    "refs": missing_refs[:20],
                }
            )
        return {
            "schema_version": "memory-os.symbolic_offloader_doctor.v0",
            "module": "symbolic_offloader",
            "profile": self.profile,
            "status": "error" if findings else "ok",
            "findings": findings,
            "actual_send": False,
            "actual_execute": False,
        }

    def _build_node(self, task_id: str, entry: dict[str, Any], *, index: int) -> dict[str, Any]:
        node_id = _safe_id(str(entry.get("node_id") or f"001-N{index}"), "node_id")
        title = str(entry.get("title") or node_id).strip() or node_id
        text = str(entry.get("text") or "")
        ref = Path("system-modules") / "symbolic_offloader" / "refs" / task_id / f"{node_id}.md"
        return {
            "node_id": node_id,
            "title": title[:120],
            "ref": ref.as_posix(),
            "original_sha256": _sha256(text),
            "char_count": len(text),
            "estimated_tokens": _estimate_tokens(text),
            "text": text,
        }


def _safe_id(value: str, field_name: str) -> str:
    candidate = str(value or "").strip()
    if not _SAFE_ID_RE.match(candidate):
        raise ValueError(f"Invalid {field_name}: {value}")
    return candidate


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _pressure_tier(estimated_tokens: int, token_budget: int | None) -> str:
    if not token_budget or token_budget <= 0:
        return "mild"
    ratio = estimated_tokens / float(token_budget)
    if ratio >= 2.0:
        return "emergency"
    if ratio >= 1.0:
        return "aggressive"
    return "mild"


def _mermaid(nodes: list[dict[str, Any]]) -> str:
    lines = ["graph TD"]
    if not nodes:
        lines.append('  EMPTY["no offloaded nodes"]')
    for node in nodes:
        lines.append(f'  {node["node_id"].replace("-", "_")}["{node["node_id"]}: {node["title"]}"]')
    return "\n".join(lines)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
