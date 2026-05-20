import json

from plugins.memory.memory_os.fixtures import build_sannai_multi_root_fixture
from plugins.memory.memory_os.migrator import (
    export_shadow_bundle,
    import_shadow_bundle,
    scan_legacy_sources,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _target_roots(tmp_path):
    target_home = tmp_path / "target" / ".hermes" / "profiles" / "sannai-shadow"
    return MemoryOSRoots.from_hermes_home(target_home, profile="sannai-shadow")


def test_scan_legacy_sources_covers_sannai_multi_root_shape(tmp_path):
    layout = build_sannai_multi_root_fixture(tmp_path)

    sources = scan_legacy_sources(layout.roots)
    by_kind = {source["kind"]: source for source in sources}

    assert "soul" in by_kind
    assert "memory" in by_kind
    assert "user" in by_kind
    assert "state:diary" in by_kind
    assert "state:self_memory" in by_kind
    assert "state:lingering_thoughts" in by_kind
    assert "state:quiet_moments" in by_kind
    assert "state:heartbeat_lingering_candidates" in by_kind
    assert "state:digests_daily" in by_kind
    assert by_kind["state:heartbeat_lingering_candidates"]["candidate_status_counts"] == {
        "candidate": 1,
        "owner_eligible": 1,
        "owner_defer": 1,
    }


def test_export_shadow_bundle_dry_run_reports_without_writing(tmp_path):
    layout = build_sannai_multi_root_fixture(tmp_path)
    out = tmp_path / "bundle"
    before_hashes = {source["path"]: source["sha256"] for source in scan_legacy_sources(layout.roots)}

    report = export_shadow_bundle(layout.roots, out_path=out, dry_run=True)

    assert report["dry_run"] is True
    assert report["source_count"] >= 9
    assert report["candidate_status_counts"]["owner_eligible"] == 1
    assert str(out / "manifest.json") in report["would_write_paths"]
    assert not out.exists()
    after_hashes = {source["path"]: source["sha256"] for source in scan_legacy_sources(layout.roots)}
    assert after_hashes == before_hashes


def test_export_shadow_bundle_includes_private_bodies_but_excludes_secrets(tmp_path):
    layout = build_sannai_multi_root_fixture(tmp_path)
    (layout.hermes_home / ".env").write_text("API_KEY=DO_NOT_COPY\n", encoding="utf-8")
    (layout.state_root / "diary.md").write_text("diary api_key=DO_NOT_LEAK\n", encoding="utf-8")
    out = tmp_path / "bundle"

    report = export_shadow_bundle(
        layout.roots,
        out_path=out,
        include_private_bodies=True,
    )

    assert report["dry_run"] is False
    assert (out / "manifest.json").exists()
    assert (out / "source" / "state" / "diary.md").read_text(encoding="utf-8") == "diary api_key=[redacted]\n"
    assert not (out / "source" / "profile" / ".env").exists()
    assert "DO_NOT_LEAK" not in (out / "source" / "state" / "diary.md").read_text(encoding="utf-8")


def test_import_shadow_bundle_dry_run_reports_would_write_without_target_writes(tmp_path):
    layout = build_sannai_multi_root_fixture(tmp_path / "source")
    bundle = tmp_path / "bundle"
    export_shadow_bundle(layout.roots, out_path=bundle, include_private_bodies=True)
    roots = _target_roots(tmp_path)

    report = import_shadow_bundle(bundle, roots, dry_run=True)

    assert report["dry_run"] is True
    assert str(roots.imports_root / bundle.name / "import_report.json") in report["would_write_paths"]
    assert report["candidate_status_counts"]["owner_eligible"] == 1
    assert not roots.memory_os_root.exists()


def test_import_shadow_bundle_writes_only_imports_and_canonical_store(tmp_path):
    layout = build_sannai_multi_root_fixture(tmp_path / "source")
    source_before = {source["path"]: source["sha256"] for source in scan_legacy_sources(layout.roots)}
    bundle = tmp_path / "bundle"
    export_shadow_bundle(layout.roots, out_path=bundle, include_private_bodies=True)
    roots = _target_roots(tmp_path)

    report = import_shadow_bundle(bundle, roots, dry_run=False)

    assert report["dry_run"] is False
    assert (roots.imports_root / bundle.name / "import_report.json").exists()
    assert report["candidate_status_counts"]["owner_eligible"] == 1
    assert report["approval_state_counts"]["approved_for_s5_visibility"] == 1
    assert not list(roots.crystallized_root.glob("*.md"))

    store = MemoryOSStore(roots)
    events = store.read_events()
    assert any(event.kind == "legacy_source" for event in events)
    lingering = store.read_working_document("lingering")
    assert lingering["items"][0]["kind"] == "lingering"

    imported_report = json.loads((roots.imports_root / bundle.name / "import_report.json").read_text(encoding="utf-8"))
    assert imported_report["source_count"] == report["source_count"]
    source_after = {source["path"]: source["sha256"] for source in scan_legacy_sources(layout.roots)}
    assert source_after == source_before
