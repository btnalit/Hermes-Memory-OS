"""Tests for recall golden set framework."""

import pytest
from pathlib import Path
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
)


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