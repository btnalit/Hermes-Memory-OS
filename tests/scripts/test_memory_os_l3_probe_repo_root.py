"""Tests for L3 probe repo root resolution — auto-detection + identity verification."""

from __future__ import annotations

import os
import sys
from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────

def _load_l3_helper():
    """Load memory_os_l3_probe_helper as a module for testing."""
    import importlib.util
    path = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_l3_probe_helper.py"
    spec = importlib.util.spec_from_file_location("l3_helper", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _make_fake_repo(tmp_path: Path) -> Path:
    """Create a minimal fake Memory-OS repo with identity markers."""
    repo = tmp_path / "fake_memory_os_repo"
    (repo / "plugins" / "memory" / "memory_os").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = \"Hermes-Memory-OS\"\n")
    (repo / "plugins" / "memory" / "memory_os" / "__init__.py").write_text(
        "# Memory-OS provider\n"
    )
    (repo / "scripts").mkdir()
    (repo / "scripts" / "probe_l3_prefetch_behavior.py").write_text(
        "print('GOVERNANCE PATH OK')\n"
    )
    return repo


# ── _is_memory_os_repo ───────────────────────────────────────────────

class TestIsMemoryOSRepo:
    def test_valid_repo_returns_true(self, tmp_path):
        mod = _load_l3_helper()
        repo = _make_fake_repo(tmp_path)
        assert mod._is_memory_os_repo(repo) is True

    def test_missing_pyproject_toml_fails_loud(self, tmp_path):
        mod = _load_l3_helper()
        repo = _make_fake_repo(tmp_path)
        (repo / "pyproject.toml").unlink()
        try:
            mod._is_memory_os_repo(repo)
            assert False, "should have raised SystemExit"
        except SystemExit as exc:
            assert "Missing marker files" in str(exc)
            assert "pyproject.toml" in str(exc)

    def test_missing_init_fails_loud(self, tmp_path):
        mod = _load_l3_helper()
        repo = _make_fake_repo(tmp_path)
        (repo / "plugins" / "memory" / "memory_os" / "__init__.py").unlink()
        try:
            mod._is_memory_os_repo(repo)
            assert False, "should have raised SystemExit"
        except SystemExit as exc:
            assert "Missing marker files" in str(exc)
            assert "__init__.py" in str(exc)

    def test_non_existent_path_returns_false(self, tmp_path):
        mod = _load_l3_helper()
        assert mod._is_memory_os_repo(tmp_path / "nonexistent") is False

    def test_file_not_dir_returns_false(self, tmp_path):
        mod = _load_l3_helper()
        f = tmp_path / "some_file.txt"
        f.write_text("not a dir")
        assert mod._is_memory_os_repo(f) is False


# ── _auto_detect_repo_root ───────────────────────────────────────────

class TestAutoDetectRepoRoot:
    def test_finds_repo_by_walking_up(self, tmp_path, monkeypatch):
        """When running from deep inside a repo, walking up finds the root."""
        mod = _load_l3_helper()
        repo = _make_fake_repo(tmp_path)
        deep = repo / "plugins" / "memory" / "memory_os"
        deep.mkdir(parents=True, exist_ok=True)

        # Simulate __file__ being deep inside the repo
        monkeypatch.setattr(
            mod.Path, "__file__",
            str(deep / "some_script.py"),
            raising=False,
        )
        # Override __file__ on the module's Path reference is tricky.
        # Instead, test _walk_up_for_markers directly.
        found = mod._walk_up_for_markers(deep, mod._MEMORY_OS_IDENTITY_MARKERS)
        assert found is not None
        assert found.resolve() == repo.resolve()

    def test_returns_none_when_no_repo_in_chain(self, tmp_path):
        mod = _load_l3_helper()
        empty = tmp_path / "empty_dir"
        empty.mkdir()
        found = mod._walk_up_for_markers(empty, mod._MEMORY_OS_IDENTITY_MARKERS)
        assert found is None

    def test_walk_stops_at_filesystem_root(self, tmp_path, monkeypatch):
        mod = _load_l3_helper()
        # Walk from tmp_path upward — should eventually hit root and return None
        found = mod._walk_up_for_markers(tmp_path, mod._MEMORY_OS_IDENTITY_MARKERS)
        assert found is None  # tmp_path is not a repo root


# ── _has_all_markers ─────────────────────────────────────────────────

class TestHasAllMarkers:
    def test_all_present(self, tmp_path):
        mod = _load_l3_helper()
        repo = _make_fake_repo(tmp_path)
        assert mod._has_all_markers(repo, mod._MEMORY_OS_IDENTITY_MARKERS) is True

    def test_one_missing(self, tmp_path):
        mod = _load_l3_helper()
        repo = _make_fake_repo(tmp_path)
        (repo / "pyproject.toml").unlink()
        assert mod._has_all_markers(repo, mod._MEMORY_OS_IDENTITY_MARKERS) is False

    def test_empty_dir(self, tmp_path):
        mod = _load_l3_helper()
        assert mod._has_all_markers(tmp_path, mod._MEMORY_OS_IDENTITY_MARKERS) is False


# ── _resolve_repo_root (integration) ─────────────────────────────────

class TestResolveRepoRoot:
    def test_env_var_takes_priority(self, tmp_path, monkeypatch):
        mod = _load_l3_helper()
        repo = _make_fake_repo(tmp_path)
        monkeypatch.setenv("MEMORY_OS_REPO_ROOT", str(repo))
        result = mod._resolve_repo_root()
        assert result.resolve() == repo.resolve()

    def test_env_var_wrong_path_fails_loud(self, tmp_path, monkeypatch):
        mod = _load_l3_helper()
        wrong = tmp_path / "wrong_dir"
        wrong.mkdir()
        monkeypatch.setenv("MEMORY_OS_REPO_ROOT", str(wrong))
        try:
            mod._resolve_repo_root()
            assert False, "should have raised SystemExit"
        except SystemExit as exc:
            assert "does not appear to be a Memory-OS repository" in str(exc)

    def test_config_file_second_priority(self, tmp_path, monkeypatch):
        mod = _load_l3_helper()
        repo = _make_fake_repo(tmp_path)

        # Write config next to where the helper "would be"
        helper_path = tmp_path / "memory_os_l3_probe_helper.py"
        helper_path.write_text("# stub\n")
        config_path = tmp_path / "l3_probe_repo_root.txt"
        config_path.write_text(str(repo))

        # Override __file__ so config_file resolution finds our txt
        monkeypatch.setattr(
            mod.os.path, "dirname",
            lambda p: str(tmp_path),
            raising=False,
        )
        # Actually, it's simpler to test via monkeypatching Path(__file__)
        # Let's test the logic directly by temporarily modifying module-level path
        import plugins.memory.memory_os.prefetch  # noqa: ensure sys.path ready

        # Cleaner: test that _is_memory_os_repo is called for config path
        # by verifying the resolution chain
        # For a reliable test, we replace _resolve_repo_root's config_file
        # with our known path
        original_file = mod.__file__
        try:
            # Point __file__ at our tmp_path so config file resolution works
            mod.__dict__["__file__"] = str(helper_path)
            result = mod._resolve_repo_root()
            assert result.resolve() == repo.resolve()
        finally:
            mod.__dict__["__file__"] = original_file

    def test_auto_detect_fallback(self, tmp_path, monkeypatch):
        """When env and config both missing, auto-detection kicks in."""
        mod = _load_l3_helper()
        repo = _make_fake_repo(tmp_path)

        # Remove env var
        monkeypatch.delenv("MEMORY_OS_REPO_ROOT", raising=False)
        # Remove config file (by pointing __file__ somewhere without one)
        monkeypatch.setattr(
            mod, "__file__",
            str(repo / "scripts" / "memory_os_l3_probe_helper.py"),
        )
        # Remove config sidecar
        config = repo / "scripts" / "l3_probe_repo_root.txt"
        if config.exists():
            config.unlink()

        # Auto-detection should walk up from script location and find repo
        result = mod._resolve_repo_root()
        assert result.resolve() == repo.resolve()

    def test_all_methods_fail_raises_system_exit(self, tmp_path, monkeypatch):
        mod = _load_l3_helper()
        monkeypatch.delenv("MEMORY_OS_REPO_ROOT", raising=False)
        # Point both __file__ and cwd into an empty dir with no repo markers
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setattr(mod, "__file__", str(empty / "helper.py"))
        monkeypatch.setattr(mod.Path, "cwd", lambda: empty.resolve())
        # No config file, no env var, empty dir → auto-detect fails
        try:
            mod._resolve_repo_root()
            assert False, "should have raised SystemExit"
        except SystemExit as exc:
            assert "Cannot resolve Memory-OS repo root" in str(exc)
