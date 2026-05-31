from plugins.modules.context.symbolic_offloader import SymbolicOffloaderModule


def test_symbolic_offloader_round_trips_original_text_by_node_id(tmp_path):
    module = SymbolicOffloaderModule(tmp_path, profile="default")
    original = "tool output line 1\nimportant evidence line 2\n"

    result = module.offload_entries(
        task_id="task-001",
        entries=[
            {
                "node_id": "001-N3",
                "title": "tool output",
                "text": original,
            }
        ],
    )
    recalled = module.recall_node("task-001", "001-N3")

    assert result["schema_version"] == "memory-os.symbolic_offload_result.v0"
    assert result["module"] == "symbolic_offloader"
    assert result["offloaded_count"] == 1
    assert result["pressure_tier"] == "mild"
    assert "001-N3" in result["mermaid"]
    assert result["actual_send"] is False
    assert result["actual_execute"] is False
    assert result["canonical_state_changed"] is False
    assert recalled["node_id"] == "001-N3"
    assert recalled["text"] == original
    assert recalled["checksum"] == result["nodes"][0]["original_sha256"]


def test_symbolic_offloader_pressure_tier_does_not_delete_originals(tmp_path):
    module = SymbolicOffloaderModule(tmp_path, profile="default")
    entries = [
        {"node_id": "001-N1", "title": "one", "text": "a" * 5000},
        {"node_id": "001-N2", "title": "two", "text": "b" * 5000},
    ]

    result = module.offload_entries(task_id="task-002", entries=entries, token_budget=1000)

    assert result["pressure_tier"] == "emergency"
    assert result["offloaded_count"] == 2
    assert module.recall_node("task-002", "001-N1")["text"] == "a" * 5000
    assert module.recall_node("task-002", "001-N2")["text"] == "b" * 5000
    assert result["canonical_state_changed"] is False
    assert result["live_behavior_changed"] is False
