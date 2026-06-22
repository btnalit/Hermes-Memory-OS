#!/usr/bin/env python3
"""Vector retrieval value benchmark — real embedder on realistic data.

Uses the real LocalEmbedder (paraphrase-multilingual-MiniLM-L12-v2) on
20 crystallized records with known semantic relationships (cross-lingual
pairs, synonym pairs, noise) to measure whether vector similarity retrieval
surfaces records that FTS5 full-text search misses.

This script closes the "诚实 gap": the pipeline is verified correct by
1485 tests, but those tests use MockEmbedder (deterministic by text length,
zero semantics).  They prove the cosine math is right — they cannot prove
vectors improve recall.  This benchmark can.

Usage:
    python scripts/memory_os_vector_retrieval_benchmark.py
    python scripts/memory_os_vector_retrieval_benchmark.py --json
    python scripts/memory_os_vector_retrieval_benchmark.py --limit 10

The script creates an isolated temp directory, seeds records, builds a
full SQLite index with real embeddings, runs comparative retrieval, and
reports the results.  Clean exit when sentence-transformers is not installed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 0 — embedder availability check (lightweight, no model load)
# ═══════════════════════════════════════════════════════════════════════════════

def _check_embedder_importable() -> bool:
    """Check whether sentence_transformers can be imported (no model load)."""
    try:
        import importlib

        importlib.import_module("sentence_transformers")
        return True
    except ImportError:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# Benchmark data — 20 records with deliberate semantic relationships
# ═══════════════════════════════════════════════════════════════════════════════

# Each record: id, kind, tags, body (the full crystallized record text).
# "pair" is a documentation key grouping related records; it is not written
# into the frontmatter.
#
# Design:
#   4 cross-lingual pairs: same topic, Chinese ↔ English
#   4 synonym pairs:       same topic, different English vocabulary
#   4 noise records:       unrelated content
#
# Every pair has one Chinese record and one English record (or, for synonym
# pairs, two English records with different wording).  The ground-truth
# queries test whether vector retrieval bridges the language/vocabulary gap
# that FTS5 keyword matching cannot.

RECORDS: list[dict[str, Any]] = [
    # ── Cross-lingual pair: dark mode / 深色模式 ──────────────────────────
    {
        "id": "rec_cn_dark_mode",
        "kind": "preference",
        "tags": ["ui", "accessibility"],
        "pair": "dark_mode",
        "body": (
            "用户偏好设置：系统应默认启用深色模式以减轻眼睛疲劳。"
            "长时间使用浅色界面会导致视觉不适，建议在所有应用中提供深色主题选项，"
            "并允许用户在亮色和深色之间切换。深色模式对于夜间工作的开发人员尤其重要。"
        ),
    },
    {
        "id": "rec_en_dark_theme",
        "kind": "preference",
        "tags": ["ui", "accessibility"],
        "pair": "dark_mode",
        "body": (
            "UI customization settings: the application shall provide a dark theme "
            "option as the default to reduce eye strain during extended use. Users "
            "should be able to toggle between light and dark appearances. Night-time "
            "developers particularly benefit from reduced blue light exposure."
        ),
    },

    # ── Cross-lingual pair: code review / 代码审查 ────────────────────────
    {
        "id": "rec_cn_code_review",
        "kind": "policy",
        "tags": ["development", "review"],
        "pair": "code_review",
        "body": (
            "代码审查政策：所有合并请求必须经过至少一位高级开发人员批准。"
            "审查者应检查代码正确性、安全性和可维护性。未经审查的代码不得合并到主分支。"
            "紧急修复可以事后审查，但必须在24小时内完成补审。"
        ),
    },
    {
        "id": "rec_en_pr_review",
        "kind": "policy",
        "tags": ["development", "review"],
        "pair": "code_review",
        "body": (
            "Pull request approval rules: every merge to main requires at minimum "
            "one senior engineer sign-off. Reviewers must verify correctness, "
            "security, and maintainability. Unreviewed code shall not reach the "
            "main branch. Hotfixes may be reviewed post-merge but must complete "
            "the review within 24 hours."
        ),
    },

    # ── Cross-lingual pair: deployment / 部署 ─────────────────────────────
    {
        "id": "rec_cn_deployment",
        "kind": "decision",
        "tags": ["devops", "infrastructure"],
        "pair": "deployment",
        "body": (
            "部署流程：使用Docker容器化所有服务，通过Kubernetes编排管理。"
            "每个微服务应有独立的Dockerfile，构建镜像后推送到私有镜像仓库。"
            "生产环境使用Helm charts管理Kubernetes资源配置，确保环境一致性。"
        ),
    },
    {
        "id": "rec_en_container",
        "kind": "decision",
        "tags": ["devops", "infrastructure"],
        "pair": "deployment",
        "body": (
            "Container orchestration strategy: all microservices are packaged as "
            "Docker images and deployed via Kubernetes clusters. Each service "
            "maintains its own Dockerfile. Built images are pushed to a private "
            "container registry. Production uses Helm charts for consistent "
            "Kubernetes resource management across environments."
        ),
    },

    # ── Cross-lingual pair: monitoring / 监控 ─────────────────────────────
    {
        "id": "rec_cn_monitoring",
        "kind": "decision",
        "tags": ["devops", "observability"],
        "pair": "monitoring",
        "body": (
            "监控告警配置：生产环境必须部署Prometheus采集指标数据，"
            "使用Grafana构建可视化仪表盘。关键指标包括CPU使用率、内存占用、"
            "请求延迟和错误率。告警规则通过Alertmanager配置，严重告警发送到企业微信。"
        ),
    },
    {
        "id": "rec_en_observability",
        "kind": "decision",
        "tags": ["devops", "observability"],
        "pair": "monitoring",
        "body": (
            "Observability stack requirements: production services must export "
            "Prometheus metrics and expose Grafana dashboard visualizations. "
            "Tracked metrics include CPU utilization, memory consumption, request "
            "latency percentiles, and error rates. Alerting rules are managed via "
            "Alertmanager with critical alerts routed to Slack."
        ),
    },

    # ── Synonym pair: error handling / retry logic ────────────────────────
    {
        "id": "rec_cn_error_handling",
        "kind": "policy",
        "tags": ["development", "resilience"],
        "pair": "error_handling",
        "body": (
            "错误处理规范：所有API调用必须包含超时重试机制，最多重试3次。"
            "重试间隔采用指数退避策略，初始等待1秒，每次加倍。"
            "不可恢复的错误（如认证失败）不应重试，应直接返回错误。"
        ),
    },
    {
        "id": "rec_en_retry_logic",
        "kind": "policy",
        "tags": ["development", "resilience"],
        "pair": "error_handling",
        "body": (
            "Network resilience patterns: implement exponential backoff with "
            "jitter for all external service calls, maximum 3 retry attempts. "
            "Initial backoff is 1 second, doubling each attempt. Non-recoverable "
            "errors such as authentication failures must not be retried and "
            "should surface immediately to the caller."
        ),
    },

    # ── Synonym pair: testing coverage / quality gates ────────────────────
    {
        "id": "rec_cn_testing",
        "kind": "policy",
        "tags": ["development", "quality"],
        "pair": "testing",
        "body": (
            "测试策略：单元测试覆盖率必须达到80%以上才能合并代码。"
            "集成测试覆盖所有API端点的正常路径和错误路径。"
            "端到端测试在每次发布前执行，覆盖核心用户流程。"
        ),
    },
    {
        "id": "rec_en_test_coverage",
        "kind": "policy",
        "tags": ["development", "quality"],
        "pair": "testing",
        "body": (
            "Quality gates: unit test line coverage must exceed 80 percent before "
            "pull requests can be merged. Integration tests shall cover happy-path "
            "and error-path scenarios for every API endpoint. End-to-end tests "
            "execute against staging before each release, covering core user "
            "journeys including login, checkout, and account management."
        ),
    },

    # ── Synonym pair: performance / caching ───────────────────────────────
    {
        "id": "rec_cn_performance",
        "kind": "insight",
        "tags": ["performance", "database"],
        "pair": "performance",
        "body": (
            "性能优化经验：数据库查询缓存是提升响应速度最有效的方法。"
            "引入Redis缓存层后，平均API响应时间从800ms降低到120ms。"
            "缓存键设计应包含版本号以便在数据结构变更时自动失效。"
        ),
    },
    {
        "id": "rec_en_query_cache",
        "kind": "insight",
        "tags": ["performance", "database"],
        "pair": "performance",
        "body": (
            "Database optimization findings: adding a Redis cache layer reduced "
            "average API response time from 800 milliseconds to 120 milliseconds. "
            "Cache keys should embed a schema version so they auto-invalidate "
            "when the underlying data structure changes. Cache warming on deploy "
            "prevents cold-start latency spikes."
        ),
    },

    # ── Synonym pair: security / password hashing ─────────────────────────
    {
        "id": "rec_cn_security",
        "kind": "policy",
        "tags": ["security", "authentication"],
        "pair": "security",
        "body": (
            "安全备忘录：所有用户密码必须使用bcrypt哈希算法加密存储，"
            "工作因子不低于12。敏感数据（密钥、令牌、个人身份信息）必须加密存储。"
            "API密钥定期轮换，轮换周期不超过90天。"
        ),
    },
    {
        "id": "rec_en_password_hash",
        "kind": "policy",
        "tags": ["security", "authentication"],
        "pair": "security",
        "body": (
            "Authentication security requirements: all stored credentials must use "
            "bcrypt with a work factor of at least 12. Sensitive data including "
            "API keys, access tokens, and personally identifiable information "
            "must be encrypted at rest. Credential rotation is enforced every "
            "90 days for all service accounts."
        ),
    },

    # ── Noise records (deliberately unrelated) ────────────────────────────
    {
        "id": "rec_cn_lunch",
        "kind": "note",
        "tags": ["personal"],
        "pair": "noise",
        "body": (
            "午餐推荐：公司附近新开了一家日料店，寿司很新鲜，价格适中。"
            "特别推荐三文鱼刺身和鳗鱼饭。周一到周五午餐时段人比较多，"
            "建议提前预约或者11:30之前到店。"
        ),
    },
    {
        "id": "rec_cn_meeting",
        "kind": "note",
        "tags": ["personal", "planning"],
        "pair": "noise",
        "body": (
            "周会记录：讨论了Q3产品路线图和客户反馈优先级。"
            "产品团队提出了三个新功能需求，其中用户权限管理被列为最高优先级。"
            "下次会议定在下周二下午两点，届时将审查原型设计。"
        ),
    },
    {
        "id": "rec_en_coffee",
        "kind": "note",
        "tags": ["personal"],
        "pair": "noise",
        "body": (
            "Office amenities update: the espresso machine on floor 3 has been "
            "upgraded to a new model with double boiler and PID temperature "
            "control. The single-origin Ethiopian beans are highly recommended "
            "by the facilities team."
        ),
    },
    {
        "id": "rec_en_sprint_plan",
        "kind": "note",
        "tags": ["personal", "planning"],
        "pair": "noise",
        "body": (
            "Sprint planning notes: team velocity averaged 23 story points over "
            "the last four sprints. The upcoming sprint will focus on reducing "
            "technical debt in the authentication module and improving test "
            "coverage in the payment service integration layer."
        ),
    },
]

# Each query includes: the query text, the list of ground-truth record IDs
# that SHOULD be retrieved (the semantic pair), and a label.
QUERIES: list[dict[str, Any]] = [
    {
        "query": "dark theme",
        "ground_truth": ["rec_cn_dark_mode", "rec_en_dark_theme"],
        "label": "Cross-lingual EN→CN: 'dark theme' ↔ 深色模式",
    },
    {
        "query": "代码审查",
        "ground_truth": ["rec_cn_code_review", "rec_en_pr_review"],
        "label": "Cross-lingual CN→EN: 代码审查 ↔ PR review",
    },
    {
        "query": "pull request review",
        "ground_truth": ["rec_en_pr_review", "rec_cn_code_review"],
        "label": "Synonym EN: 'pull request review' ↔ code review policy",
    },
    {
        "query": "容器部署",
        "ground_truth": ["rec_cn_deployment", "rec_en_container"],
        "label": "Cross-lingual CN→EN: 容器部署 ↔ container orchestration",
    },
    {
        "query": "retry backoff",
        "ground_truth": ["rec_en_retry_logic", "rec_cn_error_handling"],
        "label": "Synonym EN: 'retry backoff' ↔ 重试机制",
    },
    {
        "query": "test coverage",
        "ground_truth": ["rec_en_test_coverage", "rec_cn_testing"],
        "label": "Synonym EN: 'test coverage' ↔ 测试覆盖率",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _make_frontmatter(rec: dict[str, Any]) -> dict[str, Any]:
    """Build a valid crystallized-record frontmatter dict from a record spec."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "memory-os.crystallized.v0",
        "id": rec["id"],
        "kind": rec["kind"],
        "created_at": now,
        "approved_by": "owner",
        "approved_at": now,
        "approval_purpose": "benchmark_seed",
        "approval_note": "synthetic benchmark record",
        "source_event_ids": [],
        "tags": rec.get("tags", []),
        "sensitivity": "private",
        "hindsight_indexed": False,
        "bridge_state": "active",
    }


def _vector_search_scored(
    index_path: str,
    query_vec: "np.ndarray | None",
    *,
    record_type: str = "crystallized_record",
    limit: int = 60,
) -> list[tuple[str, float]]:
    """Return (record_id, cosine_score) tuples sorted descending.

    Mirrors MemoryOSIndex.vector_search() but returns scores alongside IDs
    so the benchmark report can display similarity values.
    """
    import numpy as np

    if query_vec is None:
        return []
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "select record_id, embedding from memory_embeddings "
            "where record_type = ?",
            (record_type,),
        ).fetchall()

        q_norm = float(np.linalg.norm(query_vec))
        if q_norm == 0.0:
            return []

        results: list[tuple[str, float]] = []
        for row in rows:
            try:
                vec = np.frombuffer(row["embedding"], dtype=np.float32)
            except Exception:
                continue
            if vec.shape != query_vec.shape:
                continue
            dot = float(np.dot(query_vec, vec))
            v_norm = float(np.linalg.norm(vec))
            if v_norm == 0.0:
                continue
            sim = dot / (q_norm * v_norm)
            results.append((str(row["record_id"]), sim))

        results.sort(key=lambda r: r[1], reverse=True)
        return results[:limit]
    except Exception:
        return []
    finally:
        conn.close()


def _rrf_ordered(
    fts_ids: list[str],
    vec_ids: list[str],
    *,
    k: int = 60,
    top_n: int = 60,
) -> list[str]:
    """RRF union returning a ranked list (not set).

    Same algorithm as prefetch._rrf_union() but returns ordered IDs
    for readable benchmark output.
    """
    scores: dict[str, float] = {}
    for rank, rid in enumerate(fts_ids):
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank + 1)
    for rank, rid in enumerate(vec_ids):
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank + 1)
    sorted_ids = sorted(scores.keys(), key=lambda rid: scores[rid], reverse=True)
    return sorted_ids[:top_n]


# ═══════════════════════════════════════════════════════════════════════════════
# Main benchmark
# ═══════════════════════════════════════════════════════════════════════════════

def run_benchmark(limit: int = 8) -> dict[str, Any]:
    """Run the retrieval benchmark and return structured results."""

    # ── Ensure the repo root is on sys.path ───────────────────────────────
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore
    from plugins.memory.memory_os.index import MemoryOSIndex
    from plugins.memory.memory_os.embedder import LocalEmbedder

    embedder = LocalEmbedder()
    if not embedder.is_available():
        return {
            "status": "skipped",
            "reason": "embedder_unavailable",
            "diagnostic": (
                "LocalEmbedder.is_available() returned False.  "
                "Check that sentence-transformers is installed and the model "
                "paraphrase-multilingual-MiniLM-L12-v2 can be loaded."
            ),
        }

    # ── Create isolated environment ───────────────────────────────────────
    tmp_dir = tempfile.mkdtemp(prefix="memory_os_benchmark_")
    tmp_path = Path(tmp_dir)
    try:
        # ── Set up store and seed records ──────────────────────────────────
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="benchmark")
        store = MemoryOSStore(roots)
        store.initialize()

        for i, rec in enumerate(RECORDS):
            fm = _make_frontmatter(rec)
            store.append_crystallized_record(
                f"benchmark_{i:03d}_{rec['id']}.md", fm, rec["body"]
            )

        # ── Build index with real embedder ─────────────────────────────────
        index = MemoryOSIndex(roots)
        index._embedder = embedder  # thread embedder BEFORE rebuild
        index.rebuild_from_store(store)

        counts = index.counts()
        if counts.get("memory_embeddings", 0) == 0:
            return {
                "status": "error",
                "reason": "no_embeddings",
                "diagnostic": (
                    "index.rebuild_from_store() completed but memory_embeddings "
                    "is empty. The embedder may have returned empty bytes."
                ),
            }

        # ── Run queries ────────────────────────────────────────────────────
        index_path = str(roots.index_path)
        query_results: list[dict[str, Any]] = []

        for q in QUERIES:
            query_text: str = q["query"]
            ground_truth: set[str] = set(q["ground_truth"])
            label: str = q.get("label", query_text)

            # FTS5 lane
            fts_raw = index.search(query_text, limit=limit)
            fts_hits = fts_raw.get("hits", []) if isinstance(fts_raw, dict) else []
            fts_ids = [
                str(h["record_id"])
                for h in fts_hits
                if isinstance(h, dict)
                and str(h.get("record_type", "")) == "crystallized_record"
            ]

            # Vector lane
            qvec = embedder.embed_query(query_text)
            vec_scored = _vector_search_scored(index_path, qvec, limit=limit)
            vec_ids = [rid for rid, _score in vec_scored]

            # RRF union
            rrf_ids = _rrf_ordered(fts_ids, vec_ids, top_n=limit)

            # Diff analysis
            fts_set = set(fts_ids)
            vec_set = set(vec_ids)
            rrf_set = set(rrf_ids)

            vec_only = [
                (rid, score)
                for rid, score in vec_scored
                if rid not in fts_set
            ]
            fts_only = [rid for rid in fts_ids if rid not in vec_set]

            qr = {
                "query": query_text,
                "label": label,
                "ground_truth": sorted(ground_truth),
                "fts_ids": fts_ids,
                "vec_ids": vec_ids,
                "vec_scored": [
                    {"id": rid, "cosine": round(score, 4)}
                    for rid, score in vec_scored
                ],
                "rrf_ids": rrf_ids,
                "vec_only": [
                    {"id": rid, "cosine": round(score, 4)}
                    for rid, score in vec_only
                ],
                "fts_only": fts_only,
                "gt_in_fts": sorted(ground_truth & fts_set),
                "gt_in_vec": sorted(ground_truth & vec_set),
                "gt_in_rrf": sorted(ground_truth & rrf_set),
            }
            query_results.append(qr)

        # ── Summary statistics ─────────────────────────────────────────────
        total_gt = sum(len(q["ground_truth"]) for q in QUERIES)
        total_gt_fts = sum(len(qr["gt_in_fts"]) for qr in query_results)
        total_gt_vec = sum(len(qr["gt_in_vec"]) for qr in query_results)
        total_gt_rrf = sum(len(qr["gt_in_rrf"]) for qr in query_results)

        total_vec_only = sum(len(qr["vec_only"]) for qr in query_results)
        total_fts_only = sum(len(qr["fts_only"]) for qr in query_results)

        avg_fts = sum(len(qr["fts_ids"]) for qr in query_results) / max(len(QUERIES), 1)
        avg_vec = sum(len(qr["vec_ids"]) for qr in query_results) / max(len(QUERIES), 1)

        summary = {
            "record_count": len(RECORDS),
            "query_count": len(QUERIES),
            "embedding_count": counts.get("memory_embeddings", 0),
            "embedder_model": embedder._model_name if hasattr(embedder, "_model_name") else "unknown",
            "avg_fts_hits": round(avg_fts, 1),
            "avg_vec_hits": round(avg_vec, 1),
            "total_vec_only": total_vec_only,
            "total_fts_only": total_fts_only,
            "ground_truth_total": total_gt,
            "ground_truth_recall_fts": round(total_gt_fts / max(total_gt, 1), 3),
            "ground_truth_recall_vec": round(total_gt_vec / max(total_gt, 1), 3),
            "ground_truth_recall_rrf": round(total_gt_rrf / max(total_gt, 1), 3),
        }

        return {
            "status": "ok",
            "summary": summary,
            "queries": query_results,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _print_report(result: dict[str, Any]) -> None:
    """Print a human-readable benchmark report."""
    if result.get("status") != "ok":
        print(f"Benchmark skipped: {result.get('reason', 'unknown')}")
        if result.get("diagnostic"):
            print(f"  {result['diagnostic']}")
        return

    summary = result["summary"]
    queries = result["queries"]

    print("=" * 72)
    print("  Memory-OS Vector Retrieval Benchmark")
    print("=" * 72)
    print(f"  Embedder:  {summary['embedder_model']}")
    print(f"  Records:   {summary['record_count']} "
          f"({summary['embedding_count']} embeddings)")
    print(f"  Queries:   {summary['query_count']}")
    print()

    for i, qr in enumerate(queries, 1):
        print(f"── Query {i}: {qr['query'][:60]}")
        print(f"   {qr['label']}")
        print(f"   Ground truth: {qr['ground_truth']}")
        print()

        fts_str = ", ".join(qr["fts_ids"]) if qr["fts_ids"] else "(none)"
        print(f"   FTS5 hits ({len(qr['fts_ids'])}):  [{fts_str}]")

        if qr["vec_scored"]:
            vec_str = ", ".join(
                f"{v['id']}(cos={v['cosine']:.3f})" for v in qr["vec_scored"]
            )
        else:
            vec_str = "(none)"
        print(f"   Vector hits ({len(qr['vec_ids'])}): [{vec_str}]")

        rrf_str = ", ".join(qr["rrf_ids"]) if qr["rrf_ids"] else "(none)"
        print(f"   RRF union ({len(qr['rrf_ids'])}):   [{rrf_str}]")

        if qr["vec_only"]:
            vo_str = ", ".join(
                f"{v['id']}(cos={v['cosine']:.3f})" for v in qr["vec_only"]
            )
            print(f"   ★ Vector-only (FTS5 missed): [{vo_str}]")
        else:
            print(f"   ★ Vector-only (FTS5 missed): (none)")

        if qr["fts_only"]:
            print(f"   ★ FTS5-only (vector missed):  {qr['fts_only']}")
        else:
            print(f"   ★ FTS5-only (vector missed):  (none)")

        print(f"   ✓ GT in FTS5:  {qr['gt_in_fts']}")
        print(f"   ✓ GT in Vector: {qr['gt_in_vec']}")
        print(f"   ✓ GT in RRF:   {qr['gt_in_rrf']}")
        print()

    # Summary
    print("=" * 72)
    print("  Summary")
    print("=" * 72)
    print(f"  Avg FTS5 hits:          {summary['avg_fts_hits']}")
    print(f"  Avg vector hits:         {summary['avg_vec_hits']}")
    print(f"  Vector-unique total:     {summary['total_vec_only']}")
    print(f"  FTS5-unique total:       {summary['total_fts_only']}")
    print(f"  Ground truth (total):    {summary['ground_truth_total']}")
    print(f"  GT recall — FTS5:        {summary['ground_truth_recall_fts']:.1%}")
    print(f"  GT recall — Vector:      {summary['ground_truth_recall_vec']:.1%}")
    print(f"  GT recall — RRF union:   {summary['ground_truth_recall_rrf']:.1%}")
    print()
    recall_delta = summary['ground_truth_recall_vec'] - summary['ground_truth_recall_fts']
    if recall_delta > 0:
        print(f"  ✦ Vector adds {recall_delta:.0%} recall over FTS5 alone")
    elif recall_delta == 0:
        print(f"  ✦ Vector recall matches FTS5 (no regression)")
    print("=" * 72)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Memory-OS vector retrieval value benchmark"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON instead of a human-readable report",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=8,
        help="Max results per retrieval lane (default: 8)",
    )
    args = parser.parse_args()

    if not _check_embedder_importable():
        print(
            "sentence-transformers is not installed.  "
            "Install it with:\n"
            "  pip install sentence-transformers\n"
            "Then re-run this benchmark."
        )
        sys.exit(0)

    result = run_benchmark(limit=args.limit)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        _print_report(result)


if __name__ == "__main__":
    main()
