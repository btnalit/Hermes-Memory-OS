from plugins.memory.memory_os.index import _write_edge_canonical
from plugins.memory.memory_os.roots import MemoryOSRoots


def test_edge_canonical_write_uses_locked_jsonl_append(tmp_path, monkeypatch):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    calls = []

    def fake_append_jsonl_locked(path, record, *, ensure_parent=True, durable=True):
        calls.append(
            {
                "path": path,
                "record": record,
                "ensure_parent": ensure_parent,
                "durable": durable,
            }
        )

    monkeypatch.setattr(
        "plugins.memory.memory_os.jsonl_io.append_jsonl_locked",
        fake_append_jsonl_locked,
    )

    ok = _write_edge_canonical(
        roots,
        {"edge_id": "edge_test", "relation_type": "co_occurs"},
    )

    assert ok is True
    assert len(calls) == 1
    assert calls[0]["path"] == roots.memory_os_root / "graph" / "edges.jsonl"
    assert calls[0]["record"]["edge_id"] == "edge_test"
    assert calls[0]["ensure_parent"] is False
    assert calls[0]["durable"] is True
