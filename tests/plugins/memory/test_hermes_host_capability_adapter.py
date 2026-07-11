from plugins.memory.memory_os import host_capability_probe as core_probe
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.seam.hermes_memory_os.host_capability_adapter import probe_host_capabilities


def test_host_capability_adapter_supplies_host_observations_without_core_host_calls(tmp_path, monkeypatch):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")

    def forbidden_core_host_call(*_args, **_kwargs):
        raise AssertionError("host invocation must be supplied by the Hermes seam")

    monkeypatch.setattr(core_probe, "_gateway_capability", forbidden_core_host_call)
    monkeypatch.setattr(core_probe, "_hermes_cron_capability", forbidden_core_host_call)
    monkeypatch.setattr(core_probe, "_owner_channel_capability", forbidden_core_host_call)

    report = probe_host_capabilities(
        roots,
        hermes_bin="definitely-missing-hermes-bin",
        include_hermes_version=False,
    )

    assert report["schema_version"] == "memory-os.host_capability_probe.v2"
    assert report["host_observation_owner"] == "hermes_memory_os_seam"
    assert report["capability_contract"]["contract_status"] == "ok"
    assert report["raw_body_included"] is False
