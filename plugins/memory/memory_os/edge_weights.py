"""Edge birth weights — 按证据强度分层的出生权重(P3 2026-08-07)。

背景:三个 proposer 曾全部以 weight=1.0 产边 = 反馈 cap。后果:
`query_edges` 的 `order by weight desc` 全并列,退化成「最新优先」;
命中强化(cap 1.0)永远抬不动已在顶的边 — R4 提升半环生来 no-op,
只有 60 天遗忘半环在工作;注入的 weight<0.3 噪声下限过滤不了任何
东西。出生权重按证据强度分层且留出爬升空间后,权重才真正承担排序
职责:命中的边向 1.0 渐近(乘性强化,cap 不可达),没命中的停在
出生位直到遗忘。

守卫契约(见 test_memory_os_edge_weights.py):
- 每个 producer 产边分支的 (proposed_by, evidence_kind) 必须在表内
  (未知键 KeyError,fail loud);
- min(出生权重) >= prefetch.GRAPH_INJECTION_WEIGHT_FLOOR(下限是不设防
  安全底线,不是真实过滤);
- max(出生权重及 llm 上界) < 1.0(weight==1.0 从此可判定为未迁移
  遗留行 — 重归一脚本与监控依赖此不变量);
- vector 例外:weight=cosine 相似度(本就有区分度),不走本表。
"""
from __future__ import annotations

# (proposed_by, evidence_kind) → 出生权重。证据强度排序:
#   explicit_reference      正文显式引用对方 record_id(硬证据,误报率最低)
#   source_event_provenance event→crystallized 溯源(硬证据)
#   shared_source_event     共享 source_event(同源 ≠ 相关)
#   body_similarity         词面重叠(dice)
#   temporal_proximity      仅时间邻近(最弱信号,「无其他信号」兜底分支)
EDGE_BIRTH_WEIGHTS: dict[tuple[str, str], float] = {
    ("structural", "explicit_reference"): 0.70,
    ("structural", "shared_source_event"): 0.55,
    ("structural", "body_similarity"): 0.45,
    ("structural", "temporal_proximity"): 0.35,
    ("provenance", "source_event_provenance"): 0.70,
}

# llm 边:confidence 本就被 _call_llm 采集,旧实现在写入时硬编码 1.0
# 丢弃(「confidence is provenance only」)— 复用而非重建。
# confidence ∈ [0,1] → weight ∈ [0.45, 0.75]。
LLM_BIRTH_BASE = 0.45
LLM_BIRTH_CONFIDENCE_SPAN = 0.30


def birth_weight(proposed_by: str, evidence_kind: str) -> float:
    """查表出生权重;未知键抛 KeyError — 新 producer 分支必须先登记,
    守卫测试对照 producer 实际产出钉死(词表漂移的 gate 什么也不检查)。"""
    return EDGE_BIRTH_WEIGHTS[(str(proposed_by), str(evidence_kind))]


def llm_birth_weight(confidence: object) -> float:
    """llm 边出生权重:0.45 + 0.30 × confidence(越界/非法值按 0)。"""
    try:
        bounded = min(1.0, max(0.0, float(confidence)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        bounded = 0.0
    return round(LLM_BIRTH_BASE + LLM_BIRTH_CONFIDENCE_SPAN * bounded, 4)
