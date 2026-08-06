"""W2 (E2) — 存量重复边一次性压缩脚本测试。

压缩输入是 W1 之前的历史产物(写入口去重已使新产生的重复不可能),
因此测试直接以生产同形状(JSONL 行 + memory_edges 投影行)铺设存量,
这不是绕过真实生产者 — W1 之后的真实生产者已经造不出这种输入。
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _load_script():
    script = _REPO_ROOT / "scripts" / "memory_os_graph_edges_compaction.py"
    spec = importlib.util.spec_from_file_location("memory_os_graph_edges_compaction", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)

    edges_path = roots.memory_os_root / "graph" / "edges.jsonl"
    edges_path.parent.mkdir(parents=True, exist_ok=True)

    def edge(i, frm, to, rel, created_at, state="candidate"):
        return {
            "edge_id": f"edge_seed_{i}",
            "from_record_type": "crystallized_record",
            "from_record_id": frm,
            "to_record_type": "crystallized_record",
            "to_record_id": to,
            "relation_type": rel,
            "weight": 0.6,
            "created_at": created_at,
            "source_event_id": "",
            "state": state,
            "invalidated_at": None,
            "proposed_by": "structural",
        }

    # 三元组 A: 3 份重复(earliest = edge_seed_0);三元组 B: 唯一;
    # 三元组 C: 2 份重复但其中一份已 invalidated(不参与压缩)。
    rows = [
        edge(0, "cry_a", "cry_b", "refines", "2026-06-01T00:00:00+00:00"),
        edge(1, "cry_a", "cry_b", "refines", "2026-06-02T00:00:00+00:00"),
        edge(2, "cry_a", "cry_b", "refines", "2026-06-03T00:00:00+00:00"),
        edge(3, "cry_c", "cry_d", "co_occurs", "2026-06-01T00:00:00+00:00"),
        edge(4, "cry_e", "cry_f", "refines", "2026-06-01T00:00:00+00:00"),
        edge(5, "cry_e", "cry_f", "refines", "2026-06-02T00:00:00+00:00", state="invalidated"),
    ]
    with edges_path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    conn = sqlite3.connect(str(roots.index_path))
    conn.executemany(
        "insert or replace into memory_edges (edge_id, from_record_type, from_record_id,"
        " to_record_type, to_record_id, relation_type, weight, created_at,"
        " source_event_id, state, invalidated_at, proposed_by)"
        " values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            tuple(r[k] for k in (
                "edge_id", "from_record_type", "from_record_id", "to_record_type",
                "to_record_id", "relation_type", "weight", "created_at",
                "source_event_id", "state", "invalidated_at", "proposed_by"))
            for r in rows
        ],
    )
    conn.commit()
    conn.close()
    return roots, store, index


def _states(index):
    conn = sqlite3.connect(str(index.roots.index_path))
    rows = conn.execute("select edge_id, state from memory_edges").fetchall()
    conn.close()
    return {str(r[0]): str(r[1]) for r in rows}


def test_w2_compaction_keeps_earliest_and_invalidates_rest(tmp_path):
    """反事实:压缩后每组重复三元组只留最早一条非 invalidated,其余 invalidated。"""
    roots, store, index = _seed(tmp_path)
    mod = _load_script()

    rc = mod.main(["--hermes-home", str(tmp_path), "--profile", "default", "--apply"])
    assert rc == 0

    states = _states(index)
    assert states["edge_seed_0"] == "candidate"      # earliest of triple A kept
    assert states["edge_seed_1"] == "invalidated"
    assert states["edge_seed_2"] == "invalidated"
    assert states["edge_seed_3"] == "candidate"      # unique triple untouched
    assert states["edge_seed_4"] == "candidate"      # only live row of triple C kept
    assert states["edge_seed_5"] == "invalidated"    # was already invalidated


def test_w2_compaction_survives_index_sync(tmp_path):
    """反事实(依赖 W0):压缩结果必须在 index_sync 重投影后保持。"""
    roots, store, index = _seed(tmp_path)
    mod = _load_script()
    rc = mod.main(["--hermes-home", str(tmp_path), "--profile", "default", "--apply"])
    assert rc == 0

    index.sync_from_store(store)

    states = _states(index)
    assert states["edge_seed_1"] == "invalidated"
    assert states["edge_seed_2"] == "invalidated"
    assert states["edge_seed_0"] == "candidate"


def test_w2_compaction_dry_run_changes_nothing(tmp_path):
    """默认 dry-run:不写任何文件,不改任何状态。"""
    roots, store, index = _seed(tmp_path)
    edges_path = roots.memory_os_root / "graph" / "edges.jsonl"
    before = edges_path.read_text(encoding="utf-8")

    mod = _load_script()
    rc = mod.main(["--hermes-home", str(tmp_path), "--profile", "default"])
    assert rc == 0

    assert edges_path.read_text(encoding="utf-8") == before
    states = _states(index)
    assert states["edge_seed_1"] == "candidate"


def test_w2_compaction_idempotent(tmp_path):
    """第二次 --apply 必须是 0 变更。"""
    roots, store, index = _seed(tmp_path)
    mod = _load_script()
    assert mod.main(["--hermes-home", str(tmp_path), "--profile", "default", "--apply"]) == 0

    report = mod.compact_duplicate_edges(roots, apply=False)
    assert report["duplicate_group_count"] == 0
    assert report["invalidate_planned_count"] == 0
