"""Tests for recall golden set framework."""

import argparse

import pytest
from pathlib import Path
from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.fixtures import build_crystallized_frontmatter
from plugins.memory.memory_os.recall_golden import (
    GoldenSet,
    GoldenQuery,
    GoldenResult,
    RecallEvaluation,
    RecallEvaluationItem,
    load_golden_set,
    save_golden_set,
    evaluate_recall,
    score_from_evaluation,
    classify_evaluation_item,
    run_golden_set_report,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


SEED_GOLDEN_PATH = Path(__file__).parent / "fixtures" / "recall_golden_seed.golden.json"


def _init_store(tmp_path, *, profile: str = "memoryos-test") -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _parse_memory_os_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    register_cli(parser)
    return parser.parse_args(argv)


def _canonical_write_surface_snapshot(store: MemoryOSStore) -> dict:
    """Snapshot the four canonical write surfaces the CLI command must never touch."""

    def _files(root: Path) -> frozenset:
        if not root.exists():
            return frozenset()
        return frozenset(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())

    return {
        "events": _files(store.roots.events_root),
        "working": _files(store.roots.working_root),
        "crystallized": _files(store.roots.crystallized_root),
        "candidates_jsonl_exists": (store.roots.crystallized_root / "candidates.jsonl").exists(),
    }


class TestGoldenSetIO:
    def test_save_and_load(self, tmp_path: Path):
        gs = GoldenSet(
            profile="test",
            queries=[
                GoldenQuery(
                    query="test query",
                    expected=[
                        GoldenResult(
                            recall_type="crystallized",
                            content_pattern="test content",
                            source_ref="source-1",
                        ),
                    ],
                    description="test description",
                ),
            ],
            description="test golden set",
        )
        path = tmp_path / "test.golden.json"
        save_golden_set(path, gs)
        assert path.exists()

        loaded = load_golden_set(path)
        assert loaded.profile == "test"
        assert len(loaded.queries) == 1
        assert loaded.queries[0].query == "test query"
        assert len(loaded.queries[0].expected) == 1
        assert loaded.queries[0].expected[0].recall_type == "crystallized"

    def test_load_nonexistent(self, tmp_path: Path):
        path = tmp_path / "nonexistent.golden.json"
        gs = load_golden_set(path)
        assert gs.profile == "nonexistent"
        assert len(gs.queries) == 0

    def test_load_empty(self, tmp_path: Path):
        path = tmp_path / "empty.golden.json"
        path.write_text('{"schema_version": "v1", "queries": []}', encoding="utf-8")
        gs = load_golden_set(path)
        assert len(gs.queries) == 0


class TestClassifyEvaluationItem:
    def test_hit(self):
        item = RecallEvaluationItem(
            query="test", recall_type="crystallized", content_pattern="test",
            expected_source_ref="", must_hit=True, matched=True, score=1.0,
        )
        assert classify_evaluation_item(item) == "hit"

    def test_miss(self):
        item = RecallEvaluationItem(
            query="test", recall_type="crystallized", content_pattern="test",
            expected_source_ref="", must_hit=True, matched=False, score=0.0,
        )
        assert classify_evaluation_item(item) == "miss_missing"

    def test_false_positive(self):
        item = RecallEvaluationItem(
            query="test", recall_type="crystallized", content_pattern="test",
            expected_source_ref="", must_hit=False, matched=True, score=0.0,
        )
        assert classify_evaluation_item(item) == "false_positive"

    def test_error(self):
        item = RecallEvaluationItem(
            query="test", recall_type="crystallized", content_pattern="test",
            expected_source_ref="", must_hit=True, matched=False, error="failed",
        )
        assert classify_evaluation_item(item) == "error"

    def test_source_authority_issue(self):
        item = RecallEvaluationItem(
            query="test", recall_type="crystallized", content_pattern="test",
            expected_source_ref="expected-source", must_hit=True, matched=True,
            matched_source_ref="wrong-source",
        )
        assert classify_evaluation_item(item) == "source_authority_issue"


class TestScoreFromEvaluation:
    def test_perfect_score(self):
        eval_result = RecallEvaluation(
            golden_set="test", total_hits=10, total_misses=0, false_positives=0,
            false_negatives=0, total_errors=0,
        )
        score = score_from_evaluation(eval_result)
        assert score["recall_rate"] == 1.0
        assert score["precision"] == 1.0

    def test_zero_hits(self):
        eval_result = RecallEvaluation(
            golden_set="test", total_hits=0, total_misses=10, false_positives=0,
            false_negatives=10, total_errors=0,
        )
        score = score_from_evaluation(eval_result)
        assert score["recall_rate"] == 0.0

    def test_false_positives(self):
        eval_result = RecallEvaluation(
            golden_set="test", total_hits=5, total_misses=5, false_positives=3,
            false_negatives=5, total_errors=0,
        )
        score = score_from_evaluation(eval_result)
        assert score["recall_rate"] == 0.5
        assert score["precision"] == pytest.approx(5 / 8, rel=0.01)


class TestRunGoldenSetReport:
    """`run_golden_set_report` is the composition the CLI calls: load + evaluate + score."""

    def test_missing_golden_file_reports_zero_queries_not_an_error(self, tmp_path):
        store = _init_store(tmp_path)

        report = run_golden_set_report(store, tmp_path / "nonexistent.golden.json", profile="default")

        assert report["query_count"] == 0
        assert report["items"] == []
        assert report["score"]["total_errors"] == 0
        assert report["score"]["recall_rate"] == 0.0

    def test_report_shape_against_seed_golden_set_on_empty_store(self, tmp_path):
        store = _init_store(tmp_path)

        report = run_golden_set_report(store, SEED_GOLDEN_PATH, profile="seed")

        assert report["schema_version"]
        assert report["golden_path"] == str(SEED_GOLDEN_PATH)
        assert report["query_count"] == 5
        assert len(report["items"]) == 5
        # On a store with no captured data at all, every must_hit expectation
        # in the seed set legitimately misses -- including the two
        # before/after markers, which are *expected* to miss today regardless
        # of store population (see fixture description).
        must_hit_items = [item for item in report["items"] if item["must_hit"]]
        assert must_hit_items
        assert all(not item["matched"] for item in must_hit_items)
        assert all(item["classification"] == "miss_missing" for item in must_hit_items)


class TestSeedGoldenSetFixture:
    """The committed seed golden set used by the `recall-golden run` CLI command."""

    def test_seed_golden_set_loads_and_has_expected_item_count(self):
        gs = load_golden_set(SEED_GOLDEN_PATH)

        assert gs.profile == "seed"
        assert len(gs.queries) == 5
        assert all(q.query for q in gs.queries)
        assert all(q.expected for q in gs.queries)

    def test_seed_golden_set_has_exactly_one_labeled_before_after_marker(self):
        gs = load_golden_set(SEED_GOLDEN_PATH)

        markers = [q for q in gs.queries if "BEFORE/AFTER MARKER" in q.description]
        assert len(markers) == 1

        marker = markers[0]
        assert marker.expected[0].must_hit is True
        assert "67" in marker.expected[0].content_pattern

    def test_seed_golden_set_has_a_negative_control_item(self):
        gs = load_golden_set(SEED_GOLDEN_PATH)

        negatives = [q for q in gs.queries for e in q.expected if e.must_hit is False]
        assert len(negatives) == 1


class TestRecallGoldenCli:
    """End-to-end coverage of `memory recall-golden run` and its read-only contract."""

    def test_recall_golden_run_prints_report_and_is_read_only(self, tmp_path, monkeypatch, capsys):
        store = _init_store(tmp_path, profile="default")
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        before = _canonical_write_surface_snapshot(store)

        result = memory_os_command(
            _parse_memory_os_args(["recall-golden", "run", "--golden-path", str(SEED_GOLDEN_PATH)])
        )

        after = _canonical_write_surface_snapshot(store)
        assert after == before, "recall-golden run must not write events/, working/, crystallized/, or candidates.jsonl"

        import json

        output = json.loads(capsys.readouterr().out)
        assert output["golden_path"] == str(SEED_GOLDEN_PATH)
        assert output["query_count"] == 5
        assert "score" in output
        assert len(output["items"]) == 5
        # The seed set's must-hit items miss on an empty store (including the
        # deliberate before/after markers), so the command reports non-zero.
        assert result == 1

    def test_recall_golden_run_defaults_to_profile_resolved_path_when_missing(self, tmp_path, monkeypatch, capsys):
        store = _init_store(tmp_path, profile="default")
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        before = _canonical_write_surface_snapshot(store)

        result = memory_os_command(_parse_memory_os_args(["recall-golden", "run"]))

        after = _canonical_write_surface_snapshot(store)
        assert after == before

        import json

        output = json.loads(capsys.readouterr().out)
        assert output["query_count"] == 0
        assert result == 0


@pytest.mark.usefixtures("crystallized_test_write_authority")
class TestEvaluateRecallCounterfactual:
    """Mandatory counterfactual: prove the evaluator responds to real degradation.

    Builds one crystallized fact via the real production write path
    (``MemoryOSStore.append_crystallized_record`` -- the same call
    ``test_memory_os_prefetch.py::test_prefetch_orders_layers_deterministically``
    exercises), confirms a hit, deletes the underlying record to simulate a
    capture/storage regression, and confirms the score actually drops. If it
    does not, ``evaluate_recall`` is a no-op gate rather than a real instrument.
    """

    def test_score_drops_when_recallable_fact_is_deleted(self, tmp_path):
        store = _init_store(tmp_path)

        frontmatter = build_crystallized_frontmatter(seed=91, kind="moment")
        body = "The rendezvous marker fact GOLDEN_COUNTERFACTUAL_9182 is confirmed true."
        record_path = store.append_crystallized_record("counterfactual.md", frontmatter.__dict__, body)

        golden_set = GoldenSet(
            profile="counterfactual",
            queries=[
                GoldenQuery(
                    query="rendezvous marker fact",
                    expected=[
                        GoldenResult(
                            recall_type="crystallized",
                            content_pattern="GOLDEN_COUNTERFACTUAL_9182",
                        ),
                    ],
                ),
            ],
        )

        before = evaluate_recall(store, golden_set, profile="counterfactual")
        before_score = score_from_evaluation(before)
        assert before.total_hits == 1
        assert before.total_misses == 0
        assert before_score["recall_rate"] == 1.0

        # Degrade: delete the underlying crystallized record. This simulates
        # the exact class of regression the golden set exists to catch -- a
        # fact silently dropping out of recall.
        record_path.unlink()

        after = evaluate_recall(store, golden_set, profile="counterfactual")
        after_score = score_from_evaluation(after)

        assert after.total_hits == 0
        assert after.total_misses == 1
        assert after.false_negatives == 1
        assert after_score["recall_rate"] == 0.0
        assert after_score["recall_rate"] < before_score["recall_rate"]