"""Tests for locked JSONL IO primitives (data-plane safety)."""
import json
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from plugins.memory.memory_os.jsonl_io import (
    _FLOCK_AVAILABLE,
    append_jsonl_locked,
    append_jsonl_lines_locked,
    locked_jsonl_file,
    write_jsonl_atomic_locked,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _reset_flock_warned():
    """Reset the module-level _flock_warned flag between tests."""
    import plugins.memory.memory_os.jsonl_io as mod
    mod._flock_warned = False


# ── G.1: fcntl unavailable guard ─────────────────────────────────────

class TestFcntlGuard:
    """G.1: fcntl unavailable -> writes proceed + one-time warning, no crash."""

    def test_append_proceeds_when_flock_unavailable(self, tmp_path, caplog):
        _reset_flock_warned()
        with mock.patch("plugins.memory.memory_os.jsonl_io._FLOCK_AVAILABLE", False):
            path = tmp_path / "test.jsonl"
            append_jsonl_locked(path, {"id": 1, "msg": "hello"})
            lines = path.read_text().strip().split("\n")
            assert len(lines) == 1
            record = json.loads(lines[0])
            assert record["id"] == 1
            assert record["msg"] == "hello"

    def test_warning_emitted_once_only(self, tmp_path, caplog):
        _reset_flock_warned()
        with mock.patch("plugins.memory.memory_os.jsonl_io._FLOCK_AVAILABLE", False):
            append_jsonl_locked(tmp_path / "a.jsonl", {"x": 1})
            append_jsonl_locked(tmp_path / "b.jsonl", {"x": 2})
        warnings = [r.message for r in caplog.records if "fcntl unavailable" in r.message]
        assert len(warnings) == 1


# ── G.2: non-reentrant guard ──────────────────────────────────────────

class TestNonReentrantGuard:
    """G.2: same-process re-acquisition of same path raises RuntimeError."""

    def test_reentrant_same_path_raises(self, tmp_path):
        path = tmp_path / "data.jsonl"
        with locked_jsonl_file(path):
            with pytest.raises(RuntimeError, match="reentrant locked_jsonl_file"):
                with locked_jsonl_file(path):
                    pass

    def test_different_paths_allowed(self, tmp_path):
        """Different files in same process are fine."""
        with locked_jsonl_file(tmp_path / "a.jsonl"):
            with locked_jsonl_file(tmp_path / "b.jsonl"):
                pass

    def test_lock_released_after_context_exit(self, tmp_path):
        """After context exit, same path can be locked again."""
        path = tmp_path / "data.jsonl"
        with locked_jsonl_file(path):
            pass
        with locked_jsonl_file(path):
            pass


# ── G.3: single write() contract ──────────────────────────────────────

class TestSingleWriteContract:
    """G.3: each append produces a valid complete JSONL line.

    The single-write() contract is enforced by implementation design:
    the full serialized record is built in memory and passed to one
    handle.write() call.  Interleaved writes would show as malformed
    lines in the concurrent test (L.1), which verifies the real-world
    protection.
    """

    def test_append_jsonl_locked_produces_one_valid_line(self, tmp_path):
        path = tmp_path / "test.jsonl"
        record = {"id": 1, "msg": "hello"}
        append_jsonl_locked(path, record)

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed == record

    def test_append_jsonl_lines_locked_produces_n_valid_lines(self, tmp_path):
        path = tmp_path / "test.jsonl"
        records = [{"id": i} for i in range(10)]
        append_jsonl_lines_locked(path, records)

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 10
        for i, line in enumerate(lines):
            assert json.loads(line) == records[i]

    def test_append_jsonl_locked_sorts_keys(self, tmp_path):
        """Records are written with sort_keys=True (existing convention)."""
        path = tmp_path / "test.jsonl"
        append_jsonl_locked(path, {"z": 1, "a": 2, "m": 3})
        line = path.read_text().strip()
        # With sort_keys=True, keys should be in alphabetical order
        assert line == '{"a": 2, "m": 3, "z": 1}'

    def test_append_jsonl_locked_empty_batch_noop(self, tmp_path):
        """Empty records list should not create a file."""
        path = tmp_path / "empty.jsonl"
        append_jsonl_lines_locked(path, [])
        assert not path.exists()


# ── L.1: concurrent writers ───────────────────────────────────────────

class TestConcurrentWriters:
    """L.1: concurrent writers produce correct complete output."""

    def test_concurrent_appends_no_data_loss(self, tmp_path):
        import concurrent.futures

        path = tmp_path / "concurrent.jsonl"
        n_writers = 20
        n_records = 100

        def writer(worker_id: int):
            for i in range(n_records):
                append_jsonl_locked(path, {
                    "worker": worker_id,
                    "seq": i,
                    "uid": f"w{worker_id}-r{i}",
                })

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_writers) as pool:
            futures = [pool.submit(writer, w) for w in range(n_writers)]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        lines = path.read_text().strip().split("\n")
        assert len(lines) == n_writers * n_records, \
            f"Expected {n_writers * n_records} lines, got {len(lines)}"

        records = [json.loads(line) for line in lines]
        uids = {r["uid"] for r in records}
        expected = {f"w{w}-r{i}" for w in range(n_writers) for i in range(n_records)}
        missing = expected - uids
        extra = uids - expected
        assert not missing, f"Missing {len(missing)} ids: {sorted(list(missing))[:5]}..."
        assert not extra, f"Extra {len(extra)} unexpected ids"

    def test_lock_released_after_exception(self, tmp_path):
        """Lock is released even if an exception occurs inside the context."""
        path = tmp_path / "crash.jsonl"
        try:
            with locked_jsonl_file(path) as target:
                raise ValueError("simulated crash")
        except ValueError:
            pass
        # Should be able to acquire lock again — proves it was released
        with locked_jsonl_file(path):
            pass


# ── write_jsonl_atomic_locked ─────────────────────────────────────────

class TestWriteJsonlAtomicLocked:
    """write_jsonl_atomic_locked tests."""

    def test_atomic_replace_under_lock(self, tmp_path):
        path = tmp_path / "data.jsonl"
        records = [{"id": i, "value": f"record-{i}"} for i in range(5)]
        write_jsonl_atomic_locked(path, records)

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 5
        parsed = [json.loads(line) for line in lines]
        assert [r["id"] for r in parsed] == [0, 1, 2, 3, 4]

    def test_atomic_replace_overwrites_existing(self, tmp_path):
        path = tmp_path / "data.jsonl"
        path.write_text("old data\n")
        records = [{"new": True}]
        write_jsonl_atomic_locked(path, records)

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"new": True}
