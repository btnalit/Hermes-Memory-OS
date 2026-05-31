import pytest


def test_default_eval_adapter_registry_expands_first_six_in_order():
    from eval.memory_os.runner.registry import FIRST_SIX_ADAPTERS, default_adapter_registry

    registry = default_adapter_registry()
    specs = registry.expand(["all"])

    assert [spec.name for spec in specs] == list(FIRST_SIX_ADAPTERS)
    assert all(spec.deterministic is True for spec in specs)
    assert all(spec.provenance == "synthetic_fixture" for spec in specs)


def test_eval_adapter_registry_rejects_unknown_adapter():
    from eval.memory_os.runner.registry import default_adapter_registry

    registry = default_adapter_registry()

    with pytest.raises(ValueError, match="Unsupported RH-31 adapter: no_such_adapter"):
        registry.expand(["no_such_adapter"])


def test_rh31_runner_uses_adapter_registry_without_changing_first_six(tmp_path):
    from eval.memory_os.runner.run import run_rh31_eval

    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=["all"],
        report_root=tmp_path / "eval" / "reports",
        write_report=False,
    )

    assert [adapter["name"] for adapter in summary["adapters"]] == [
        "grep",
        "memory_os_fts",
        "context_projection",
        "low_clue_candidates",
        "memory_sources_replay",
        "diagnostic_grounding",
    ]
