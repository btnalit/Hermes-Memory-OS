import subprocess
from pathlib import Path

from scripts.memory_os_v24_final_verify import copy_clean_tree, initialize_clean_git


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def test_initialize_clean_git_ignores_tracked_paths_deleted_from_candidate(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q")
    _git(source, "config", "user.name", "test")
    _git(source, "config", "user.email", "test@example.invalid")
    (source / "keep.txt").write_text("keep\n", encoding="utf-8")
    (source / "obsolete.txt").write_text("obsolete\n", encoding="utf-8")
    _git(source, "add", "-A")
    _git(source, "commit", "-q", "-m", "baseline")
    (source / "obsolete.txt").unlink()

    candidate = tmp_path / "candidate"
    copy_clean_tree(source, candidate)
    initialize_clean_git(candidate, source)

    assert _git(candidate, "status", "--short").stdout == ""
    assert _git(candidate, "ls-files").stdout.splitlines() == ["keep.txt"]
