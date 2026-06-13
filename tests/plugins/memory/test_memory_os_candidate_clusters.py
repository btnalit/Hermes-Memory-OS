import argparse
import json

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.crystallized import CrystallizedCandidate, append_candidate_queue
from plugins.memory.memory_os.candidate_clusters import build_candidate_clusters, candidate_cluster_report
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def test_near_duplicate_candidates_collapse_into_one_review_cluster():
    candidates = [
        _candidate(
            "cand-a",
            "用户希望 Memory-OS 候选审阅通过聚类合并近重复项，owner 一次审一簇。",
            ["evt-a1"],
        ),
        _candidate(
            "cand-b",
            "用户希望 Memory OS 候选审阅把近重复候选聚类合并，让 owner 一次审一簇。",
            ["evt-b1", "evt-b2"],
        ),
        _candidate(
            "cand-c",
            "WC26 odds pipeline uses deterministic match ids for grading cards.",
            ["evt-c1"],
        ),
    ]

    clusters = build_candidate_clusters(candidates, min_similarity=0.58)

    duplicate_cluster = next(cluster for cluster in clusters if set(cluster.member_candidate_ids) == {"cand-a", "cand-b"})
    singleton_cluster = next(cluster for cluster in clusters if cluster.member_candidate_ids == ["cand-c"])
    assert duplicate_cluster.member_count == 2
    assert duplicate_cluster.evidence_count == 3
    assert duplicate_cluster.review_state == "owner_review_required"
    assert duplicate_cluster.boundary == {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_unapproved_crystallized_approval": False,
    }
    assert singleton_cluster.member_count == 1


def test_candidate_clusters_dedupe_repeated_candidate_ids_before_counting_members():
    candidates = [
        _candidate("cand-a", "候选审阅聚类入口按高频证据排序", ["evt-a1"]),
        _candidate("cand-a", "候选审阅聚类入口按高频证据排序", ["evt-a1"]),
        _candidate("cand-b", "候选审阅聚类入口按高频 evidence 排序", ["evt-b1"]),
    ]

    clusters = build_candidate_clusters(candidates, min_similarity=0.45)

    assert clusters[0].member_candidate_ids == ["cand-a", "cand-b"]
    assert clusters[0].member_count == 2
    assert clusters[0].evidence_count == 2


def test_candidate_cluster_ranking_prefers_frequency_then_evidence_count():
    candidates = [
        _candidate("cand-low-a", "short stable preference for telegram review channel", ["evt-1"]),
        _candidate("cand-low-b", "stable preference for telegram review channel", ["evt-2"]),
        _candidate("cand-high-a", "Memory OS cluster review should group repeated candidate evidence for approval", ["evt-3", "evt-4"]),
        _candidate("cand-high-b", "Memory-OS cluster review should group repeated candidate evidence for owner approval", ["evt-5", "evt-6"]),
        _candidate("cand-high-c", "Memory OS cluster review should group repeated candidate evidence for approval", ["evt-7"]),
    ]

    clusters = build_candidate_clusters(candidates, min_similarity=0.55)

    assert clusters[0].member_count == 3
    assert clusters[0].evidence_count == 5
    assert set(clusters[0].member_candidate_ids) == {"cand-high-a", "cand-high-b", "cand-high-c"}


def test_candidate_cluster_report_is_read_only_and_does_not_write_triage_or_approvals(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate("cand-a", "Candidate review clustering groups duplicate candidate evidence", ["evt-a"]))
    append_candidate_queue(store, _candidate("cand-b", "Candidate review clustering groups duplicate candidate evidence for owner review", ["evt-b"]))

    report = candidate_cluster_report(store, limit=5, min_similarity=0.55)

    assert report["schema_version"] == "memory-os.candidate_clusters.v0"
    assert report["status"] == "ok"
    assert report["cluster_count"] == 1
    assert report["clusters"][0]["member_count"] == 2
    assert report["clusters"][0]["review_state"] == "owner_review_required"
    assert report["boundary"]["actual_unapproved_crystallized_approval"] is False
    assert not (store.roots.crystallized_root / "candidate_triage.jsonl").exists()
    assert list(store.roots.crystallized_root.glob("*.md")) == []


def test_candidate_clusters_cli_top_renders_top_k_review_entrance(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    append_candidate_queue(store, _candidate("cand-a", "候选审阅聚类入口按高频证据排序", ["evt-a1", "evt-a2"]))
    append_candidate_queue(store, _candidate("cand-b", "候选审阅聚类入口按高频 evidence 排序", ["evt-b1"]))
    append_candidate_queue(store, _candidate("cand-c", "unrelated production deployment fact", ["evt-c1"]))

    result = memory_os_command(_parse_memory_os_args(["candidate-clusters", "top", "--limit", "1", "--min-similarity", "0.45"]))
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["schema_version"] == "memory-os.candidate_clusters.v0"
    assert payload["limit"] == 1
    assert len(payload["clusters"]) == 1
    assert payload["clusters"][0]["member_count"] == 2
    assert payload["clusters"][0]["review_state"] == "owner_review_required"


def _candidate(candidate_id: str, body: str, source_event_ids: list[str]) -> CrystallizedCandidate:
    return CrystallizedCandidate(
        candidate_id=candidate_id,
        kind="preference",
        body=body,
        source_event_ids=source_event_ids,
        sensitivity="private",
        tags=["test"],
        bridge_state="owner_eligible",
    )


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _parse_memory_os_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    register_cli(parser)
    return parser.parse_args(argv)
