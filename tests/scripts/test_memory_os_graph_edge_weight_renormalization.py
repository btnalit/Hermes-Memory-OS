"""P3 — 存量饱和权重一次性重归一脚本测试。

重归一输入是分层出生权重之前的历史产物(新写入口已造不出 weight=1.0,
乘性强化 + 0.005 最小增量也到不了)— 测试直接以生产同形状铺设存量,
与 W2 压缩测试同理,不是绕过真实生产者。
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from plugins.memory.memory_os.edge_weights import EDGE_BIRTH_WEIGHTS
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _load_script():
    script = _REPO_ROOT / "scripts" / "memory_os_graph_edge_weight_renormalization.py"
    spec = importlib.util.spec_from_file_location(
        "memory_os_graph_edge_weight_renormalization", script
    )
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

    def edge(i, rel, proposed_by, *, weight=1.0, source_event_id="", state="active"):
        return {
            "edge_id": f"edge_renorm_{i}",
            "from_record_type": "crystallized_record",
            "from_record_id": f"cry_from_{i}",
            "to_record_type": "crystallized_record",
            "to_record_id": f"cry_to_{i}",
            "relation_type": rel,
            "weight": weight,
            "created_at": f"2026-06-0{(i % 8) + 1}T00:00:00+00:00",
            "source_event_id": source_event_id,
            "state": state,
            "invalidated_at": None,
            "proposed_by": proposed_by,
        }

    rows = [
        edge(0, "depends_on", "structural"),                                  # → 0.70
        edge(1, "co_occurs", "structural", source_event_id="evt_shared_1"),   # → 0.55
        edge(2, "co_occurs", "structural"),                                   # → 0.45
        edge(3, "refines", "structural"),                                     # 遗留语义提名 → 0.45
        edge(4, "refines", "llm"),                                            # → 0.60
        edge(5, "evidence_for", "provenance"),                                # → 0.70
        edge(6, "co_occurs", "vector"),                                       # 1.0 vector:不动,计数
        edge(7, "co_occurs", "structural", weight=0.55),                      # 已分层:不在计划内
        edge(8, "refines", "structural", state="invalidated"),                # invalidated:不动
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


def _weights(index):
    conn = sqlite3.connect(str(index.roots.index_path))
    rows = conn.execute("select edge_id, weight from memory_edges").fetchall()
    conn.close()
    return {str(r[0]): float(r[1]) for r in rows}


def test_renorm_dry_run_plans_without_writing(tmp_path):
    roots, store, index = _seed(tmp_path)
    mod = _load_script()

    rc = mod.main(["--hermes-home", str(tmp_path), "--profile", "default"])
    assert rc == 0

    weights = _weights(index)
    assert weights["edge_renorm_0"] == pytest.approx(1.0), "dry-run must not write"
    report_path = roots.memory_os_root / "system" / "graph_edge_weight_renormalization_report.json"
    assert not report_path.exists(), "dry-run must not persist the epoch report"


def test_renorm_apply_maps_buckets_and_persists_report(tmp_path):
    """反事实:apply 后各证据桶映射到位;vector/已分层/invalidated 不动;
    纪元报告落盘(迁移全表 + 映射版本)。"""
    roots, store, index = _seed(tmp_path)
    mod = _load_script()

    rc = mod.main(["--hermes-home", str(tmp_path), "--profile", "default", "--apply"])
    assert rc == 0

    weights = _weights(index)
    assert weights["edge_renorm_0"] == pytest.approx(
        EDGE_BIRTH_WEIGHTS[("structural", "explicit_reference")]
    )
    assert weights["edge_renorm_1"] == pytest.approx(
        EDGE_BIRTH_WEIGHTS[("structural", "shared_source_event")]
    )
    assert weights["edge_renorm_2"] == pytest.approx(
        EDGE_BIRTH_WEIGHTS[("structural", "body_similarity")]
    )
    assert weights["edge_renorm_3"] == pytest.approx(
        EDGE_BIRTH_WEIGHTS[("structural", "body_similarity")]
    )
    assert weights["edge_renorm_4"] == pytest.approx(0.60)
    assert weights["edge_renorm_5"] == pytest.approx(
        EDGE_BIRTH_WEIGHTS[("provenance", "source_event_provenance")]
    )
    assert weights["edge_renorm_6"] == pytest.approx(1.0), "vector weights are real similarities"
    assert weights["edge_renorm_7"] == pytest.approx(0.55), "already-tiered edges untouched"
    assert weights["edge_renorm_8"] == pytest.approx(1.0), "invalidated edges untouched"

    report_path = roots.memory_os_root / "system" / "graph_edge_weight_renormalization_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mapping_version"] == "v1"
    assert report["migrated_count"] == 6
    assert report["skipped_vector_count"] == 1
    assert sorted(report["migrated_edge_ids"]) == [f"edge_renorm_{i}" for i in range(6)]
    assert report["failed_count"] == 0
    assert report["bucket_counts"]["structural_legacy_semantic"] == 1


def test_renorm_survives_index_sync_and_is_idempotent(tmp_path):
    """反事实(依赖 W0):重归一结果在重投影后保持;第二次 apply 计划为 0
    (weight==1.0 不可再生 → 幂等)。"""
    roots, store, index = _seed(tmp_path)
    mod = _load_script()
    rc = mod.main(["--hermes-home", str(tmp_path), "--profile", "default", "--apply"])
    assert rc == 0

    index.sync_from_store(store)
    weights = _weights(index)
    assert weights["edge_renorm_0"] == pytest.approx(
        EDGE_BIRTH_WEIGHTS[("structural", "explicit_reference")]
    ), "renormalized weight must survive reprojection (W0 canonical append)"

    report2 = mod.renormalize_edge_weights(
        MemoryOSRoots.from_hermes_home(tmp_path, profile="default"), apply=True,
    )
    assert report2["planned_count"] == 0, "second apply must find nothing to migrate"
    assert report2["migrated_count"] == 0
