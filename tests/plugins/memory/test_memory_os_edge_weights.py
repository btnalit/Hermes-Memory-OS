"""P3 — 出生权重分层的守卫测试。

词表漂移教训(CLAUDE.md):gate/表配置的名字必须对照 producer 实际产出
双向校验,否则漂移后的表什么也不约束。本文件钉死:
- 出生权重表的数值不变量(≥ 注入下限、< 1.0 不可达 cap);
- structural 四个产边分支逐一走真实 producer,权重 ∈ 表;
- 短语词表 relation 全集 == producer relation 全集(双向);
- shadow outcome 封闭集普查;
- birth_weight 未知键 fail loud;
- 源码级双向:每个表键有 producer 调用点,每个调用点的键在表内。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from plugins.memory.memory_os.edge_weights import (
    EDGE_BIRTH_WEIGHTS,
    LLM_BIRTH_BASE,
    LLM_BIRTH_CONFIDENCE_SPAN,
    birth_weight,
    llm_birth_weight,
)
from plugins.memory.memory_os.prefetch import (
    GRAPH_FALLBACK_PHRASE,
    GRAPH_INJECTION_WEIGHT_FLOOR,
    GRAPH_RELATION_PHRASES,
    GRAPH_SHADOW_OUTCOMES,
)

_PLUGIN_ROOT = Path(__file__).resolve().parents[3] / "plugins" / "memory" / "memory_os"

# producer relation 全集(llm 的 _AUTO_ACTIVE_TYPES ∪ structural ∪
# provenance ∪ vector)。新 relation 必须同时登记短语表两方向。
_PRODUCER_RELATIONS = frozenset(
    {"co_occurs", "depends_on", "refines", "evidence_for", "contradicts"}
)


def test_birth_weight_table_invariants():
    values = list(EDGE_BIRTH_WEIGHTS.values())
    assert values, "birth weight table must not be empty"
    assert min(values) >= GRAPH_INJECTION_WEIGHT_FLOOR, (
        "注入下限是不设防安全底线 — 任何出生权重都不得低于它(否则新边"
        "出生即被静默过滤,「计算了却无人读」的死指标形态)"
    )
    assert max(values) < 1.0, (
        "出生权重必须 < 1.0:weight==1.0 是「未迁移遗留行」的可判定诊断"
    )
    # llm 公式上下界同样受两条不变量约束
    assert llm_birth_weight(0.0) == pytest.approx(LLM_BIRTH_BASE)
    assert llm_birth_weight(1.0) == pytest.approx(
        LLM_BIRTH_BASE + LLM_BIRTH_CONFIDENCE_SPAN
    )
    assert llm_birth_weight(0.0) >= GRAPH_INJECTION_WEIGHT_FLOOR
    assert llm_birth_weight(1.0) < 1.0
    # 越界/非法输入按 0 处理(不抛、不越界)
    assert llm_birth_weight(2.5) == pytest.approx(LLM_BIRTH_BASE + LLM_BIRTH_CONFIDENCE_SPAN)
    assert llm_birth_weight(-1) == pytest.approx(LLM_BIRTH_BASE)
    assert llm_birth_weight("not-a-number") == pytest.approx(LLM_BIRTH_BASE)


def test_birth_weight_unknown_key_fails_loud():
    with pytest.raises(KeyError):
        birth_weight("structural", "no_such_evidence_kind")
    with pytest.raises(KeyError):
        birth_weight("no_such_proposer", "explicit_reference")


def test_structural_producer_branches_emit_registered_weights():
    """真实 producer 逐分支:四个产边位点的权重全部来自表(反事实:任一
    位点回退硬编码 1.0 即红)。"""
    from plugins.memory.memory_os.structural_edge_proposer import _detect_relation

    base = {
        "kind": "note",
        "tags_json": "[]",
        "created_at": "2026-08-07T00:00:00+00:00",
    }

    # ① 共享 source_event → co_occurs 0.55
    edges = _detect_relation(
        {**base, "id": "cry_a", "body": "完全不同的内容甲", "source_event_ids_json": '["evt_shared"]'},
        {**base, "id": "cry_b", "body": "毫无重叠的另一段乙", "source_event_ids_json": '["evt_shared"]'},
    )
    shared = [e for e in edges if e["relation_type"] == "co_occurs"]
    assert shared and shared[0]["weight"] == pytest.approx(
        birth_weight("structural", "shared_source_event")
    )

    # ② 显式引用 → depends_on 0.70
    edges = _detect_relation(
        {**base, "id": "cry_ref_a", "body": "本记录依赖 cry_ref_b 的结论", "source_event_ids_json": "[]"},
        {**base, "id": "cry_ref_b", "body": "底层结论内容", "source_event_ids_json": "[]"},
    )
    dep = [e for e in edges if e["relation_type"] == "depends_on"]
    assert dep and dep[0]["weight"] == pytest.approx(
        birth_weight("structural", "explicit_reference")
    )

    # ③ 词面相似(dice)→ co_occurs 0.45
    same_body = "memory os graph layer injection weight ranking exploration slots"
    edges = _detect_relation(
        {**base, "id": "cry_sim_a", "body": same_body, "source_event_ids_json": "[]"},
        {**base, "id": "cry_sim_b", "body": same_body + " extra", "source_event_ids_json": "[]"},
    )
    sim = [e for e in edges if e["relation_type"] == "co_occurs"]
    assert sim and sim[0]["weight"] == pytest.approx(
        birth_weight("structural", "body_similarity")
    )

    # ④ 仅时间邻近(无其他信号)→ co_occurs 0.35
    edges = _detect_relation(
        {**base, "id": "cry_t_a", "body": "内容完全不同的一段甲",
         "source_event_ids_json": "[]", "created_at": "2026-08-07T00:00:00+00:00"},
        {**base, "id": "cry_t_b", "body": "彼此毫无词面重叠乙",
         "source_event_ids_json": "[]", "created_at": "2026-08-07T00:10:00+00:00"},
    )
    temporal = [e for e in edges if e["relation_type"] == "co_occurs"]
    assert temporal and temporal[0]["weight"] == pytest.approx(
        birth_weight("structural", "temporal_proximity")
    )

    # 全部产出权重 ∈ 表值(无任何分支漏改)
    all_values = set(EDGE_BIRTH_WEIGHTS.values())
    for e in edges:
        assert float(e["weight"]) in all_values


def test_relation_phrase_vocabulary_matches_producers():
    """短语词表 relation 全集 == producer relation 全集,且每个 relation
    两个方向都有短语(方向敏感渲染的完整性)。"""
    from plugins.memory.memory_os.llm_edge_proposer import _AUTO_ACTIVE_TYPES

    phrase_relations = {rel for rel, _direction in GRAPH_RELATION_PHRASES}
    assert phrase_relations == _PRODUCER_RELATIONS, (
        f"phrase table drifted from producer vocabulary: "
        f"{phrase_relations ^ _PRODUCER_RELATIONS}"
    )
    assert set(_AUTO_ACTIVE_TYPES) <= _PRODUCER_RELATIONS
    for rel in phrase_relations:
        assert (rel, "anchor_is_from") in GRAPH_RELATION_PHRASES, rel
        assert (rel, "anchor_is_to") in GRAPH_RELATION_PHRASES, rel
    assert GRAPH_FALLBACK_PHRASE, "unknown relations need a direction-free fallback"


def test_shadow_outcomes_census():
    """封闭 outcome 集普查:新 outcome 必须在此登记(监控的 outcome 分布
    与 R4 的 injected 过滤都消费该集合)。"""
    assert GRAPH_SHADOW_OUTCOMES == frozenset({
        "emitted_full",
        "emitted_stub",
        "below_weight_floor",
        "target_inactive",
        "non_crystallized_target",
        "unresolved",
        "not_selected",
        "knob_disabled",
    })


def test_birth_weight_call_sites_bidirectional_source_scan():
    """源码级双向守卫:每个 birth_weight(a, b) 调用点的键在表内;每个表键
    在某个 producer 源码里有调用点(镜像方向 — 表里躺着无 producer 的键
    正是词表漂移的形态)。"""
    call_re = re.compile(r'birth_weight\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')
    producer_files = [
        _PLUGIN_ROOT / "structural_edge_proposer.py",
        _PLUGIN_ROOT / "edge_provenance.py",
    ]
    found_keys: set[tuple[str, str]] = set()
    for path in producer_files:
        source = path.read_text(encoding="utf-8")
        for match in call_re.finditer(source):
            key = (match.group(1), match.group(2))
            assert key in EDGE_BIRTH_WEIGHTS, (
                f"{path.name} calls birth_weight{key} but the key is not registered"
            )
            found_keys.add(key)
    missing = set(EDGE_BIRTH_WEIGHTS) - found_keys
    assert not missing, (
        f"registered birth-weight keys with NO producer call site: {missing}"
    )

    # llm 走公式而非表:写入点必须消费 confidence,且不得回退硬编码 1.0
    llm_source = (_PLUGIN_ROOT / "llm_edge_proposer.py").read_text(encoding="utf-8")
    assert "llm_birth_weight(confidence)" in llm_source, (
        "llm proposer must derive birth weight from the captured confidence"
    )
    assert "weight=1.0" not in llm_source, (
        "llm proposer must not fall back to the saturated legacy weight"
    )
