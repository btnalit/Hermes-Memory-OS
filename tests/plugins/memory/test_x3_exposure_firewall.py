"""X.3 counter-evidence firewall tests (A4).

Bidirectional poison: exposure data must NEVER enter eligibility gates
or prefetch ranking. These tests verify the firewall by checking import
isolation and asserting that exposure rollup is NOT consumed by decision
paths.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest


def _module_imports(module_path: Path) -> set[str]:
    """Return the set of imported module names from a Python source file."""
    try:
        source = module_path.read_text(encoding="utf-8")
    except Exception:
        return set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
    return imports


# Modules that must NOT import exposure_rollup
FIREWALL_GATED_MODULES = [
    "plugins/memory/memory_os/crystallized.py",
    "plugins/memory/memory_os/permanent_promotion.py",
    "plugins/memory/memory_os/evidence_profile.py",
]

# The forbidden import
EXPOSURE_ROLLUP_MODULE = "exposure_rollup"


class TestExposureFirewall:
    """X.3: exposure data must not feed eligibility, clearance, or ranking."""

    @pytest.mark.parametrize("module_relpath", FIREWALL_GATED_MODULES)
    def test_eligibility_modules_never_import_exposure_rollup(
        self, module_relpath: str,
    ) -> None:
        """Poison: exposure_rollup imported by eligibility/clearance/evidence modules."""
        repo_root = Path(__file__).resolve().parents[3]
        module_path = repo_root / module_relpath
        assert module_path.exists(), f"Module not found: {module_path}"

        imports = _module_imports(module_path)
        assert EXPOSURE_ROLLUP_MODULE not in imports, (
            f"FIREWALL VIOLATION: {module_relpath} imports {EXPOSURE_ROLLUP_MODULE}. "
            f"Exposure data must never feed eligibility, clearance, or ranking decisions. "
            f"This is the X.3 invariant — if you need exposure data here, the design is wrong."
        )

    def test_exposure_rollup_not_in_evidence_profile_inputs(self) -> None:
        """evidence_profile.build_evidence_profile() must not consume rollup data."""
        from plugins.memory.memory_os.evidence_profile import build_evidence_profile

        # Verify build_evidence_profile signature — must not accept exposure/rollup
        import inspect
        sig = inspect.signature(build_evidence_profile)
        param_names = list(sig.parameters.keys())
        forbidden = {"exposure", "rollup", "selected_count", "exposure_data", "rollup_data"}
        for param in param_names:
            assert param not in forbidden, (
                f"FIREWALL VIOLATION: build_evidence_profile accepts '{param}'. "
                f"Exposure data must never influence evidence profiles (X.3)."
            )

    def test_exposure_rollup_not_in_permanent_promotion_eligibility(self) -> None:
        """collect_permanent_promotion_eligibility must not consume rollup data."""
        from plugins.memory.memory_os.crystallized import CrystallizedMemoryService

        import inspect
        sig = inspect.signature(CrystallizedMemoryService.collect_permanent_promotion_eligibility)
        param_names = list(sig.parameters.keys())
        # Skip 'self' parameter
        param_names = [p for p in param_names if p != "self"]
        forbidden = {"exposure", "rollup", "selected_count", "exposure_data", "rollup_data"}
        for param in param_names:
            assert param not in forbidden, (
                f"FIREWALL VIOLATION: collect_permanent_promotion_eligibility "
                f"accepts '{param}'. Exposure data must never influence "
                f"promotion eligibility (X.3)."
            )

    def test_prefetch_ranking_not_contaminated_by_exposure(self) -> None:
        """Prefetch ranking/sorting must not reference exposure rollup."""
        repo_root = Path(__file__).resolve().parents[3]
        prefetch_path = repo_root / "plugins/memory/memory_os/prefetch.py"
        imports = _module_imports(prefetch_path)
        assert EXPOSURE_ROLLUP_MODULE not in imports, (
            f"FIREWALL VIOLATION: prefetch.py imports {EXPOSURE_ROLLUP_MODULE}. "
            f"Prefetch ranking must not use exposure rollup data (X.3)."
        )

        # Additional check: scan prefetch source for exposure-related symbols
        source = prefetch_path.read_text(encoding="utf-8")
        forbidden_patterns = [
            "exposure_rollup",
            "selected_count",
            "exposure_rollup_lag",
        ]
        for pattern in forbidden_patterns:
            assert pattern not in source, (
                f"FIREWALL VIOLATION: prefetch.py contains '{pattern}'. "
                f"Exposure data must not feed prefetch ranking (X.3)."
            )

    def test_exposure_rollup_module_self_contained(self) -> None:
        """exposure_rollup module does not import eligibility/ranking modules."""
        repo_root = Path(__file__).resolve().parents[3]
        er_path = repo_root / "plugins/memory/memory_os/exposure_rollup.py"
        imports = _module_imports(er_path)

        # exposure_rollup may read data, but must not import mutation paths
        forbidden_imports = {
            "permanent_promotion",
            "owner_actions",
        }
        for forbidden in forbidden_imports:
            assert forbidden not in imports, (
                f"FIREWALL VIOLATION: exposure_rollup imports {forbidden}. "
                f"Observation lane must not couple to mutation paths."
            )
