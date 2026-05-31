"""Governed abstraction distillation with source recall."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def abstraction_distillation_manifest() -> dict[str, Any]:
    return {
        "name": "abstraction_distillation",
        "kind": "context",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {"required": ["memory_os >=0.1.0"], "optional": ["confabulation_detector"]},
        "provides": {
            "commands": ["status", "doctor", "distill", "recall-source"],
            "schedules": ["abstraction_distillation_shadow"],
            "reads": ["memory_os.events.summary", "local_artifact.evidence_profile"],
            "writes": ["local_artifact.abstraction_distillation"],
        },
        "defaults": {"enabled": False, "delivery_mode": "no-send", "profile_scope": "per-profile"},
    }


class AbstractionDistillationModule:
    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "abstraction_distillation"

    @property
    def sources_root(self) -> Path:
        return self.module_root / "sources"

    @property
    def items_path(self) -> Path:
        return self.module_root / "items.jsonl"

    def distill(self, *, source_ref: str, source_text: str, write: bool = True) -> dict[str, Any]:
        checksum = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        items = [
            self._item(level="L1", kind="atom", source_ref=source_ref, source_text=source_text, checksum=checksum),
            self._item(level="L2", kind="scenario", source_ref=source_ref, source_text=source_text, checksum=checksum),
            self._item(level="L3", kind="sop", source_ref=source_ref, source_text=source_text, checksum=checksum),
        ]
        result = {
            "schema_version": "hermes.abstraction_distillation_result.v0",
            "module": "abstraction_distillation",
            "profile": self.profile,
            "status": "ok",
            "distillation_count": len(items),
            "items": items,
            "truth_status": "candidate_only",
            "distillation_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "canonical_state_changed": False,
            "live_behavior_changed": False,
        }
        if write:
            self.sources_root.mkdir(parents=True, exist_ok=True)
            (self.sources_root / f"{checksum}.md").write_text(source_text, encoding="utf-8")
            _append_many_jsonl(self.items_path, items)
        return result

    def recall_source(self, checksum: str) -> dict[str, Any]:
        safe = str(checksum)
        if not safe or "/" in safe or "\\" in safe or ".." in safe:
            raise ValueError("Invalid source checksum")
        text = (self.sources_root / f"{safe}.md").read_text(encoding="utf-8")
        return {
            "schema_version": "hermes.abstraction_distillation_recall.v0",
            "module": "abstraction_distillation",
            "profile": self.profile,
            "source_checksum": safe,
            "text": text,
            "actual_send": False,
            "actual_execute": False,
        }

    def status(self) -> dict[str, Any]:
        items = _read_jsonl(self.items_path)
        return {
            "schema_version": "hermes.abstraction_distillation_status.v0",
            "module": "abstraction_distillation",
            "profile": self.profile,
            "status": "ok" if items else "missing",
            "item_count": len(items),
            "distillation_live_applied": any(item.get("live_applied") is True for item in items),
            "actual_send": False,
            "actual_execute": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings = []
        for item in _read_jsonl(self.items_path):
            checksum = str(item.get("source_checksum") or "")
            if checksum and not (self.sources_root / f"{checksum}.md").exists():
                findings.append({"severity": "error", "code": "distillation_source_missing", "checksum": checksum})
        return {
            "schema_version": "hermes.abstraction_distillation_doctor.v0",
            "module": "abstraction_distillation",
            "profile": self.profile,
            "status": "error" if findings else "ok",
            "findings": findings,
        }

    def _item(self, *, level: str, kind: str, source_ref: str, source_text: str, checksum: str) -> dict[str, Any]:
        text = " ".join(source_text.split())
        return {
            "schema_version": "hermes.abstraction_distillation_item.v0",
            "profile": self.profile,
            "level": level,
            "kind": kind,
            "source_ref": str(source_ref),
            "source_checksum": checksum,
            "summary": text[:180],
            "truth_status": "candidate_only",
            "live_applied": False,
            "actual_send": False,
            "actual_execute": False,
        }


def _append_many_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
