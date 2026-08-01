#!/usr/bin/env python3
"""Self-contained blank-host smoke for Memory-OS validation."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Location-agnostic import resolution.
#
# An unconditional sys.path.insert(parents[1]) breaks on the INSTALLED layout:
# there parents[1] is $HERMES_HOME, whose plugins/ directory shadows the
# memory-os runtime namespace and yields
# "ModuleNotFoundError: No module named 'plugins.memory'". Resolve the repo
# checkout only when it actually contains the package, else fall back to the
# installed runtime tree.
_self = Path(__file__).absolute()
_repo_root = _self.parents[1]


def _preparse_cli_arg(argv: list[str], flag: str) -> str:
    """Extract a --flag value from raw argv before argparse runs."""
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            val = argv[i + 1]
            if val.startswith("--"):
                return ""  # next token is another flag, not a value
            return val
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return ""


# Resolve HERMES_HOME at module level -- CLI > env > default.
_HERMES_HOME = (
    _preparse_cli_arg(sys.argv, "--hermes-home")
    or os.environ.get("HERMES_HOME", "")
    or str(Path.home() / ".hermes")
)

if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory import load_memory_provider  # noqa: E402
from plugins.memory.memory_os.adapters.hindsight import (  # noqa: E402
    HindsightAdapter,
    HindsightAdapterConfig,
)
from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose  # noqa: E402
from plugins.memory.memory_os.crystallized import (  # noqa: E402
    CrystallizedMemoryService,
    _RESOLVER_PROVISIONAL_WRITE_CAPABILITY,
)
from plugins.memory.memory_os.fixtures import build_sannai_multi_root_fixture  # noqa: E402
from plugins.memory.memory_os.index import MemoryOSIndex  # noqa: E402
from plugins.memory.memory_os.inner_drive import InnerDriveEngine  # noqa: E402
from plugins.memory.memory_os.migrator import (  # noqa: E402
    export_shadow_bundle,
    import_shadow_bundle,
    migration_diff_report,
    migration_scan_report,
    replay_shadow_import,
)
from plugins.memory.memory_os.roots import MemoryOSRoots  # noqa: E402
from plugins.memory.memory_os.store import MemoryOSStore  # noqa: E402


class FakeHindsightClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def retain(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        return {"ok": True, "id": f"blank-host-smoke-{len(self.payloads)}"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a self-contained Memory-OS blank-host smoke.")
    parser.add_argument("--base-dir", help="Writable validation directory. Defaults to a new temp directory.")
    args = parser.parse_args(argv)

    if args.base_dir:
        base_dir = Path(args.base_dir).expanduser().resolve()
        base_dir.mkdir(parents=True, exist_ok=True)
    else:
        base_dir = Path(tempfile.mkdtemp(prefix="memory-os-blank-host-")).resolve()

    report = run_smoke(base_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def run_smoke(base_dir: Path) -> dict[str, Any]:
    e2e = _run_e2e(base_dir / "e2e")
    migrator = _run_migrator_flow(base_dir / "migrator")
    return {
        "schema_version": "memory-os.blank_host_smoke.v0",
        "base_dir": str(base_dir),
        "production_touched": False,
        "network_used": False,
        "gateway_restart_attempted": False,
        "e2e": e2e,
        "migrator": migrator,
    }


def _run_e2e(base_dir: Path) -> dict[str, Any]:
    hermes_home = base_dir / "empty-profile"
    provider = load_memory_provider("memory_os")
    provider.initialize(
        "blank-host-smoke",
        hermes_home=str(hermes_home),
        platform="blank-host-smoke",
        agent_identity="memoryos-test",
        worker_autostart=False,
    )
    provider.sync_turn(
        "Owner asks Memory-OS blank-host smoke to remember a public validation fact.",
        "Agent records a summary-only validation event.",
        session_id="blank-host-smoke",
    )
    provider.shutdown()

    roots = MemoryOSRoots.from_hermes_home(hermes_home, profile="memoryos-test")
    store = MemoryOSStore(roots)
    events = store.read_events()
    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)

    process_result = InnerDriveEngine(store).process_event(events[0], candidate_sensitivity="public")
    decision = ApprovalDecision(
        candidate_id=process_result.candidate.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="blank_host_resolver",
        reviewed_at="2026-05-20T08:00:00+00:00",
        note="Blank-host smoke approval.",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-05-21T08:00:00+00:00",
    )
    crystallized = CrystallizedMemoryService(store)
    crystallized.write_approved_record(
        process_result.candidate,
        decision,
        file_name="moments.md",
        now=datetime(2026, 5, 20, 8, 1, tzinfo=timezone.utc),
        capability=_RESOLVER_PROVISIONAL_WRITE_CAPABILITY,
    )
    disabled_report = HindsightAdapter(store, client=FakeHindsightClient()).export_all()
    enabled_client = FakeHindsightClient()
    enabled_report = HindsightAdapter(
        store,
        config=HindsightAdapterConfig(enabled=True),
        client=enabled_client,
    ).export_all()

    working_document = store.read_working_document("lingering")
    records = crystallized.read_records("moments.md")
    return {
        "event_count": len(events),
        "index_event_count": index.counts()["events"],
        "working_item_count": len(working_document["items"]),
        "candidate_id": process_result.candidate.candidate_id,
        "crystallized_record_count": len(records),
        "adapter_disabled_exported_count": disabled_report["exported_count"],
        "adapter_enabled_exported_count": enabled_report["exported_count"],
        "adapter_payload_count": len(enabled_client.payloads),
    }


def _run_migrator_flow(base_dir: Path) -> dict[str, Any]:
    layout = build_sannai_multi_root_fixture(base_dir / "source")
    scan_report = migration_scan_report(layout.roots, dry_run=True)

    dry_run_out = base_dir / "dry-shadow-bundle"
    dry_export_report = export_shadow_bundle(layout.roots, out_path=dry_run_out, dry_run=True)

    bundle = base_dir / "shadow-bundle"
    export_shadow_bundle(layout.roots, out_path=bundle, include_private_bodies=True)
    target_roots = MemoryOSRoots.from_hermes_home(
        base_dir / "target" / ".hermes" / "profiles" / "sannai-shadow",
        profile="sannai-shadow",
    )
    import_report = import_shadow_bundle(bundle, target_roots, dry_run=False)
    replay_report = replay_shadow_import(target_roots, dry_run=False, no_adapter_export=True)
    diff_report = migration_diff_report(bundle / "manifest.json", target_roots)

    return {
        "scan_source_count": scan_report["source_count"],
        "export_dry_run_wrote": dry_run_out.exists() or bool(dry_export_report["written_paths"]),
        "import_source_count": import_report["source_count"],
        "replay_events_replayed": replay_report["events_replayed"],
        "replay_messages_sent": replay_report["messages_sent"],
        "diff_ready_for_owner_review": diff_report["ready_for_owner_review"],
        "approval_state_counts": diff_report["approval_state_counts"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
