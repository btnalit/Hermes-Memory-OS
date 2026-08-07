#!/usr/bin/env python3
"""One-time renormalization of legacy saturated edge weights (P3 2026-08-07).

背景:三个 proposer 曾全部以 weight=1.0 产边(= 反馈 cap)。分层出生权重
(edge_weights.py)只作用于新边;存量 1.0 边**不会被遗忘环自然清掉**——
没有任何降权路径,1.0 边只要被注入一次就刷新 last_hit,并在
``order by weight desc limit N`` 下永久霸占排序顶端,新分层边(0.35–0.75)
一条也上不来,P3 修复会完全惰性化。

本脚本把存量 weight==1.0 的非 invalidated 边按可回溯的证据粗粒度映射回
出生权重(mapping v1;confidence 等细粒度证据已不可回溯):

  - structural + depends_on                → 0.70(显式引用)
  - structural + co_occurs + source_event  → 0.55(共享事件源)
  - structural + co_occurs(无事件源)      → 0.45(词面相似)
  - structural + 其他关系(refines 等,W1 之前的词面语义提名遗产)→ 0.45
  - llm(任意关系;confidence 不可回溯)   → 0.60
  - provenance + evidence_for              → 0.70(溯源硬证据)
  - vector                                 → 不动(weight=真实相似度),计数
  - 未知 proposed_by                       → 不动,计数

Durability 依赖 W0:``index.update_edge_weight`` 先向 ``graph/edges.jsonl``
追加整行更新(last-writer-wins),再更新投影 — 结果在 index_sync/rebuild
后保持。纪元证据落盘
``system/graph_edge_weight_renormalization_report.json``(apply 时),含
迁移 edge_id 全表 + 映射规则版本。

Default is DRY-RUN(prints the plan, writes nothing)。Pass ``--apply`` to
execute。Idempotent:第二次 --apply 找到 0 条待迁移(乘性强化 + 0.005
最小增量下限使 weight==1.0 不可再生,该值从此可判定为「未迁移遗留行」)。

Invocation:
  python scripts/memory_os_graph_edge_weight_renormalization.py \
      --hermes-home /path/to/home --profile default [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def _preparse_cli_arg(argv: list[str], flag: str) -> str:
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            val = argv[i + 1]
            if val.startswith("--"):
                return ""
            return val
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return ""


_CLI_HOME = _preparse_cli_arg(sys.argv, "--hermes-home")
_ENV_HOME = os.environ.get("HERMES_HOME", "")
_HERMES_HOME = _CLI_HOME or _ENV_HOME or str(Path.home() / ".hermes")

_self = Path(__file__).absolute()
_repo_root = _self.parents[1]
if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory.memory_os.edge_weights import EDGE_BIRTH_WEIGHTS  # noqa: E402
from plugins.memory.memory_os.index import (  # noqa: E402
    MemoryOSIndex,
    _initialize_schema,
    update_edge_weight,
)
from plugins.memory.memory_os.roots import MemoryOSRoots  # noqa: E402

MAPPING_VERSION = "v1"
# weight==1.0 判定阈值:乘性强化 + update_edge_weight 的 0.005 最小增量
# 使新路径的权重永远到不了 0.9999(0.12×(1−w)<0.005 ⇔ w>0.958 即停),
# 该阈值只会命中遗留饱和行。
_SATURATED_THRESHOLD = 0.9999

_LLM_LEGACY_WEIGHT = 0.60


def _effective_edges(edges_path: Path) -> dict[str, dict]:
    """Fold the canonical ledger per edge_id, last-writer-wins in file order
    (mirrors ``_index_edges`` projection semantics)."""
    effective: dict[str, dict] = {}
    if not edges_path.exists():
        return effective
    for raw in edges_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            edge = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(edge, dict):
            continue
        edge_id = str(edge.get("edge_id") or "")
        if edge_id:
            effective[edge_id] = edge
    return effective


def _legacy_target_weight(edge: dict) -> tuple[float | None, str]:
    """Map a legacy saturated edge to (target_weight, bucket) — None = skip."""
    proposed_by = str(edge.get("proposed_by") or "structural")
    relation = str(edge.get("relation_type") or "")
    if proposed_by == "vector":
        return None, "skipped_vector"
    if proposed_by == "provenance":
        return (
            EDGE_BIRTH_WEIGHTS[("provenance", "source_event_provenance")],
            "provenance_evidence",
        )
    if proposed_by == "llm":
        return _LLM_LEGACY_WEIGHT, "llm_confidence_unrecoverable"
    if proposed_by == "structural":
        if relation == "depends_on":
            return (
                EDGE_BIRTH_WEIGHTS[("structural", "explicit_reference")],
                "structural_explicit_reference",
            )
        if relation == "co_occurs":
            if str(edge.get("source_event_id") or "").strip():
                return (
                    EDGE_BIRTH_WEIGHTS[("structural", "shared_source_event")],
                    "structural_shared_source_event",
                )
            return (
                EDGE_BIRTH_WEIGHTS[("structural", "body_similarity")],
                "structural_body_similarity",
            )
        # W1 之前 structural 曾按词面重叠提名 refines 等语义关系(生产
        # refines 占 1951/2149)— 证据强度同词面相似。
        return (
            EDGE_BIRTH_WEIGHTS[("structural", "body_similarity")],
            "structural_legacy_semantic",
        )
    return None, "skipped_unknown_proposer"


def renormalize_edge_weights(roots: MemoryOSRoots, *, apply: bool) -> dict:
    edges_path = roots.memory_os_root / "graph" / "edges.jsonl"
    effective = _effective_edges(edges_path)

    planned: list[tuple[str, float, str]] = []
    bucket_counts: dict[str, int] = {}
    skipped_vector = 0
    skipped_unknown = 0
    saturated = 0
    for edge_id, edge in sorted(effective.items()):
        if str(edge.get("state") or "") == "invalidated":
            continue
        try:
            weight = float(edge.get("weight") or 0.0)
        except (TypeError, ValueError):
            continue
        if weight < _SATURATED_THRESHOLD:
            continue
        saturated += 1
        target, bucket = _legacy_target_weight(edge)
        if target is None:
            if bucket == "skipped_vector":
                skipped_vector += 1
            else:
                skipped_unknown += 1
            continue
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        planned.append((edge_id, target, bucket))

    report = {
        "schema_version": "memory-os.graph_edge_weight_renormalization.v0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mapping_version": MAPPING_VERSION,
        "ledger_row_count": (
            sum(1 for _ in edges_path.read_text(encoding="utf-8").splitlines())
            if edges_path.exists()
            else 0
        ),
        "effective_edge_count": len(effective),
        "saturated_count": saturated,
        "planned_count": len(planned),
        "bucket_counts": bucket_counts,
        "skipped_vector_count": skipped_vector,
        "skipped_unknown_proposer_count": skipped_unknown,
        "applied": bool(apply),
        "migrated_count": 0,
        "failed_count": 0,
        "failed_edge_ids": [],
        "migrated_edge_ids": [],
    }

    if not apply or not planned:
        return report

    conn = sqlite3.connect(str(roots.index_path))
    try:
        _initialize_schema(conn)
        for edge_id, target, _bucket in planned:
            result = update_edge_weight(conn, edge_id, target, roots=roots)
            if result and not result.get("weight_update_noop"):
                report["migrated_count"] += 1
                report["migrated_edge_ids"].append(edge_id)
            else:
                report["failed_count"] += 1
                report["failed_edge_ids"].append(edge_id)
    finally:
        conn.close()

    # 纪元证据(apply runs only):迁移全表 + 映射版本,后续任何
    # weight==1.0 行都可对照本报告判定为「未走本次迁移的写入口」。
    out = roots.memory_os_root / "system" / "graph_edge_weight_renormalization_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", default=_HERMES_HOME)
    parser.add_argument("--profile", default=os.environ.get("HERMES_PROFILE", "default"))
    parser.add_argument("--apply", action="store_true", help="execute (default: dry-run)")
    args = parser.parse_args(argv)

    roots = MemoryOSRoots.from_hermes_home(args.hermes_home, profile=args.profile)
    if not roots.index_path.exists():
        # No index yet — build the projection so weight updates can resolve.
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(roots)
        store.initialize()
        MemoryOSIndex(roots).rebuild_from_store(store)

    report = renormalize_edge_weights(roots, apply=bool(args.apply))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
