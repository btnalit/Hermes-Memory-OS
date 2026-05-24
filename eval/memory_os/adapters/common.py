"""Adapter helpers."""

from __future__ import annotations

import re
from typing import Any

from eval.memory_os.runner.safety import forbidden_field_count
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score


def terms_present(text: str, expected_terms: tuple[str, ...]) -> bool:
    if not expected_terms:
        return True
    lower = str(text or "").lower()
    return any(str(term).lower() in lower for term in expected_terms if str(term).strip())


def make_score(
    *,
    adapter: str,
    case: Rh31Case,
    passed: bool,
    metric_scope: str = "context",
    actual_route: str = "",
    actual_headings: list[str] | tuple[str, ...] = (),
    failure_class: str = "retrieval_miss",
    notes: list[str] | tuple[str, ...] = (),
    source_classes: list[str] | tuple[str, ...] = (),
    details: dict[str, Any] | None = None,
) -> Rh31Score:
    payload = {
        "adapter": adapter,
        "case_id": case.case_id,
        "actual_route": actual_route,
        "actual_headings": list(actual_headings),
        "notes": list(notes),
        "source_classes": list(source_classes),
        "details": details or {},
    }
    forbidden = forbidden_field_count(payload)
    return Rh31Score(
        adapter=adapter,
        case_id=case.case_id,
        status="pass" if passed and forbidden == 0 else "fail",
        metric_scope=metric_scope,
        expected_class=case.expected_class,
        actual_route=actual_route,
        actual_headings=tuple(actual_headings),
        failure_class=None if passed and forbidden == 0 else failure_class,
        boundary_true=False,
        forbidden_field_count=forbidden,
        live_behavior_changed=False,
        notes=tuple(notes),
        source_classes=tuple(source_classes),
        details=details or {},
    )


def matching_documents(case: Rh31Case, corpus: list[Rh31Document]) -> list[Rh31Document]:
    return [document for document in corpus if terms_present(document.text, case.expected_terms)]


def headings_from_context(context: str) -> list[str]:
    return re.findall(r"^### (.+)$", context, flags=re.M)
