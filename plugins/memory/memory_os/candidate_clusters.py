"""Deterministic crystallized-candidate clustering for owner review throughput.

This module is intentionally read-only. It groups near-duplicate candidates so an
operator can review high-frequency clusters, but it never approves, rejects,
demotes, archives, or crystallizes candidates by similarity/frequency alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from .crystallized import CrystallizedCandidate, read_candidate_queue
from .store import MemoryOSStore

CANDIDATE_CLUSTER_SCHEMA_VERSION = "memory-os.candidate_clusters.v0"
DEFAULT_CLUSTER_MIN_SIMILARITY = 0.62
DEFAULT_CLUSTER_LIMIT = 10
_MIN_TRIGRAM_OVERLAP = 3

_BOUNDARY = {
    "actual_send": False,
    "actual_execute": False,
    "actual_identity_write": False,
    "actual_unapproved_crystallized_approval": False,
}

_SENSITIVITY_RANK = {
    "public": 0,
    "internal": 1,
    "private": 2,
    "sensitive": 3,
}


@dataclass(frozen=True)
class CandidateCluster:
    cluster_id: str
    representative_body: str
    member_candidate_ids: list[str]
    member_count: int
    evidence_count: int
    source_event_ids: list[str]
    kinds: dict[str, int]
    tags: dict[str, int]
    sensitivity: str
    created_at_min: str
    created_at_max: str
    similarity_threshold: float
    review_state: str
    boundary: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "representative_body": self.representative_body,
            "member_candidate_ids": list(self.member_candidate_ids),
            "member_count": self.member_count,
            "evidence_count": self.evidence_count,
            "source_event_ids": list(self.source_event_ids),
            "kinds": dict(self.kinds),
            "tags": dict(self.tags),
            "sensitivity": self.sensitivity,
            "created_at_min": self.created_at_min,
            "created_at_max": self.created_at_max,
            "similarity_threshold": self.similarity_threshold,
            "review_state": self.review_state,
            "boundary": dict(self.boundary),
        }


def build_candidate_clusters(
    candidates: list[CrystallizedCandidate],
    *,
    min_similarity: float = DEFAULT_CLUSTER_MIN_SIMILARITY,
) -> list[CandidateCluster]:
    """Group near-duplicate candidates into deterministic review clusters.

    The function is read-only and deterministic. It does not mutate the queue,
    does not write triage records, and does not infer approval from frequency.
    """
    threshold = _normalize_threshold(min_similarity)
    buckets: list[dict[str, Any]] = []
    for candidate in sorted(_dedupe_candidates(candidates), key=lambda item: (item.created_at or "", item.candidate_id)):
        body_key = _normalize(candidate.body)
        trigrams = _trigrams(body_key)
        best_bucket: dict[str, Any] | None = None
        best_score = 0.0
        for bucket in buckets:
            score = _dice(trigrams, bucket["trigrams"])
            if score > best_score:
                best_score = score
                best_bucket = bucket
        if best_bucket is not None and best_score >= threshold:
            best_bucket["members"].append(candidate)
            # Keep the most information-rich representative for future comparisons.
            if len(_normalize(candidate.body)) > len(_normalize(best_bucket["representative"].body)):
                best_bucket["representative"] = candidate
                best_bucket["trigrams"] = trigrams
            continue
        buckets.append({"representative": candidate, "trigrams": trigrams, "members": [candidate]})

    clusters = [_cluster_from_bucket(bucket, threshold) for bucket in buckets]
    clusters.sort(
        key=lambda cluster: (
            -cluster.member_count,
            -cluster.evidence_count,
            cluster.created_at_min,
            cluster.cluster_id,
        )
    )
    return clusters


def _dedupe_candidates(candidates: list[CrystallizedCandidate]) -> list[CrystallizedCandidate]:
    by_id: dict[str, CrystallizedCandidate] = {}
    for candidate in candidates:
        existing = by_id.get(candidate.candidate_id)
        if existing is None:
            by_id[candidate.candidate_id] = candidate
            continue
        body = candidate.body if len(_normalize(candidate.body)) > len(_normalize(existing.body)) else existing.body
        source_event_ids = sorted(set(existing.source_event_ids) | set(candidate.source_event_ids))
        tags = sorted(set(existing.tags or []) | set(candidate.tags or []))
        created_values = sorted(value for value in (existing.created_at, candidate.created_at) if value)
        by_id[candidate.candidate_id] = CrystallizedCandidate(
            candidate_id=candidate.candidate_id,
            kind=existing.kind or candidate.kind,
            body=body,
            source_event_ids=source_event_ids,
            sensitivity=_max_sensitivity([existing.sensitivity, candidate.sensitivity]),
            tags=tags,
            bridge_state=existing.bridge_state or candidate.bridge_state,
            created_at=created_values[0] if created_values else "",
            rejection_count=max(existing.rejection_count, candidate.rejection_count),
        )
    return list(by_id.values())


def candidate_cluster_report(
    store: MemoryOSStore,
    *,
    limit: int = DEFAULT_CLUSTER_LIMIT,
    min_similarity: float = DEFAULT_CLUSTER_MIN_SIMILARITY,
) -> dict[str, Any]:
    """Build a bounded, read-only top-K candidate cluster review report."""
    bounded_limit = max(int(limit), 0)
    threshold = _normalize_threshold(min_similarity)
    candidates = read_candidate_queue(store)
    clusters = build_candidate_clusters(candidates, min_similarity=threshold)
    return {
        "schema_version": CANDIDATE_CLUSTER_SCHEMA_VERSION,
        "status": "ok",
        "profile": store.roots.profile or "default",
        "candidate_count": len(candidates),
        "cluster_count": len(clusters),
        "limit": bounded_limit,
        "min_similarity": threshold,
        "sort": "member_count desc, evidence_count desc, created_at_min asc, cluster_id asc",
        "review_contract": "owner_review_required; clustering never approves/rejects/demotes/archives by itself",
        "boundary": dict(_BOUNDARY),
        "clusters": [cluster.to_dict() for cluster in clusters[:bounded_limit]],
    }


def _cluster_from_bucket(bucket: dict[str, Any], threshold: float) -> CandidateCluster:
    members: list[CrystallizedCandidate] = list(bucket["members"])
    representative: CrystallizedCandidate = bucket["representative"]
    member_ids = sorted(member.candidate_id for member in members)
    source_ids = sorted({source for member in members for source in member.source_event_ids})
    created_values = sorted(str(member.created_at or "") for member in members if str(member.created_at or ""))
    return CandidateCluster(
        cluster_id=_cluster_id(member_ids),
        representative_body=representative.body,
        member_candidate_ids=member_ids,
        member_count=len(member_ids),
        evidence_count=len(source_ids),
        source_event_ids=source_ids,
        kinds=_count(member.kind for member in members),
        tags=_count(tag for member in members for tag in (member.tags or [])),
        sensitivity=_max_sensitivity(member.sensitivity for member in members),
        created_at_min=created_values[0] if created_values else "",
        created_at_max=created_values[-1] if created_values else "",
        similarity_threshold=threshold,
        review_state="owner_review_required",
        boundary=dict(_BOUNDARY),
    )


def _cluster_id(member_candidate_ids: list[str]) -> str:
    payload = "\n".join(sorted(member_candidate_ids))
    return "ccluster_" + sha256(payload.encode("utf-8")).hexdigest()[:16]


def _normalize_threshold(value: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = DEFAULT_CLUSTER_MIN_SIMILARITY
    return max(0.0, min(1.0, numeric))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").lower())


def _trigrams(normalized: str) -> set[str]:
    if len(normalized) < 3:
        return {normalized} if normalized else set()
    return {normalized[index : index + 3] for index in range(len(normalized) - 2)}


def _dice(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    if overlap < _MIN_TRIGRAM_OVERLAP and min(len(left), len(right)) >= _MIN_TRIGRAM_OVERLAP:
        return 0.0
    return (2.0 * overlap) / (len(left) + len(right))


def _count(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _max_sensitivity(values: Any) -> str:
    best = "private"
    best_rank = _SENSITIVITY_RANK[best]
    for value in values:
        text = str(value or "private").strip().lower()
        rank = _SENSITIVITY_RANK.get(text, _SENSITIVITY_RANK["private"])
        if rank > best_rank:
            best = text
            best_rank = rank
    return best
