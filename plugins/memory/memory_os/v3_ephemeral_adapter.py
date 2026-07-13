"""No-session V3 inference adapter over Hermes' existing auxiliary LLM router.

This reuses the host's provider, model, credential-pool and fallback machinery,
without constructing ``AIAgent`` and therefore without a session, tools, memory,
hooks, persisted traces, delivery, cron-output, or gateway-capture lifecycle.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import yaml


class HermesEphemeralAdapter:
    """Strict structured inference through ``agent.auxiliary_client.call_llm``."""

    def __init__(self, *, host_agent_root: Path | None = None, hermes_home: Path | None = None) -> None:
        self._callable = _load_auxiliary_callable(host_agent_root, hermes_home)

    @property
    def capability(self) -> bool:
        return self._callable is not None

    def infer(
        self,
        *,
        packet: dict[str, Any],
        prompt_contract: str,
        route_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        if self._callable is None:
            raise RuntimeError("ephemeral_capability_unavailable")
        provider = str(route_snapshot.get("provider") or "")
        model = str(route_snapshot.get("model") or "")
        if not provider or not model:
            raise RuntimeError("route_snapshot_missing")
        worker_result = self._callable(
            provider=provider,
            model=model,
            messages=[
                {"role": "system", "content": str(prompt_contract)},
                {"role": "user", "content": json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"))},
            ],
            tools=[],
            temperature=0.0,
            max_tokens=3000,
            timeout=120.0,
        )
        if not isinstance(worker_result, dict):
            raise RuntimeError("ephemeral_worker_contract_invalid")
        raw = str(worker_result.get("content") or "").strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        try:
            structured = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("ephemeral_output_not_json") from exc
        if not isinstance(structured, dict):
            raise RuntimeError("ephemeral_output_not_object")
        response_model = str(worker_result.get("model") or "")
        actual = _resolve_actual_route(response_model, route_snapshot)
        if actual is None:
            raise RuntimeError("actual_route_unverifiable")
        fallback_used = actual != {"provider": provider, "model": model}
        return {
            "status": "ok",
            "structured_output": structured,
            "requested_provider": provider,
            "requested_model": model,
            "actual_provider": actual["provider"],
            "actual_model": actual["model"],
            "fallback_used": fallback_used,
            "model_input_transmitted": True,
            "owner_delivery_attempted": False,
            "external_action_executed": False,
            "tools_enabled": False,
        }


def resolve_host_route_snapshot(hermes_home: Path) -> dict[str, Any]:
    """Read non-secret routing identity only; credentials never enter the packet."""
    path = Path(hermes_home) / "config.yaml"
    if not path.is_file():
        return {"provider": "", "model": "", "allowed_routes": []}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    model = loaded.get("model") if isinstance(loaded, dict) else {}
    model = model if isinstance(model, dict) else {}
    provider = str(model.get("provider") or "")
    model_name = str(model.get("default") or model.get("model") or "")
    allowed = [{"provider": provider, "model": model_name}] if provider and model_name else []
    fallbacks = loaded.get("fallback_providers") if isinstance(loaded, dict) else []
    if isinstance(fallbacks, list):
        for item in fallbacks:
            if not isinstance(item, dict):
                continue
            pair = {"provider": str(item.get("provider") or ""), "model": str(item.get("model") or "")}
            if pair["provider"] and pair["model"] and pair not in allowed:
                allowed.append(pair)
    return {"provider": provider, "model": model_name, "allowed_routes": allowed}


def _resolve_actual_route(response_model: str, route_snapshot: dict[str, Any]) -> dict[str, str] | None:
    allowed = route_snapshot.get("allowed_routes")
    if not isinstance(allowed, list):
        return None
    exact = [
        {"provider": str(item.get("provider") or ""), "model": str(item.get("model") or "")}
        for item in allowed
        if isinstance(item, dict) and str(item.get("model") or "") == response_model
    ]
    return exact[0] if len(exact) == 1 else None


def _load_auxiliary_callable(host_agent_root: Path | None, hermes_home: Path | None):
    if host_agent_root is None or hermes_home is None:
        return None
    root = Path(host_agent_root).expanduser().resolve()
    home = Path(hermes_home).expanduser().resolve()
    worker = Path(__file__).with_name("v3_ephemeral_worker.py")
    host_python = root / "venv" / "bin" / "python"
    if not (root / "agent" / "auxiliary_client.py").is_file() or not worker.is_file() or not host_python.is_file():
        return None

    def invoke(**kwargs):
        request = dict(kwargs)
        completed = subprocess.run(
            [str(host_python), str(worker)],
            input=json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            text=True,
            capture_output=True,
            cwd=root,
            env={
                "HOME": str(home.parent),
                "HERMES_HOME": str(home),
                "PYTHONPATH": str(root),
                "PATH": "/usr/local/bin:/usr/bin:/bin",
            },
            timeout=float(request.get("timeout") or 120.0) + 30.0,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("ephemeral_worker_failed")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("ephemeral_worker_output_invalid") from exc
        if not isinstance(result, dict) or set(result) != {"content", "model"}:
            raise RuntimeError("ephemeral_worker_contract_invalid")
        return result

    return invoke
