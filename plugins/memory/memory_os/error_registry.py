"""
Versioned error-code registry for Memory-OS.

Consolidates bare string error codes into module-level constants
and a versioned semantic registry.  Every error code records its
producer, consumer, production severity, clean-host severity, and
recoverability.

Usage:
    from .error_registry import ErrorCode, register_error_code, lookup_error_code

    # Register a new error code
    register_error_code(
        ErrorCode(
            code="crystallized_file_unparseable",
            producer="crystallized.py",
            consumer="monitor",
            production_severity="warning",
            clean_host_severity="error",
            recoverability="auto",
            description="A crystallized markdown file could not be parsed",
        )
    )

    # Look up an error code
    info = lookup_error_code("crystallized_file_unparseable")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ERROR_REGISTRY_SCHEMA_VERSION = "memory-os.error_registry.v1"


@dataclass(frozen=True)
class ErrorCode:
    """One registered error code with metadata."""

    code: str
    producer: str = ""
    consumer: str = ""
    production_severity: str = "warning"
    clean_host_severity: str = "error"
    recoverability: str = "manual"
    description: str = ""


# ── In-memory registry ─────────────────────────────────────────────────────
_registry: dict[str, ErrorCode] = {}


def register_error_code(error: ErrorCode) -> None:
    """Register an error code in the registry."""
    _registry[error.code] = error


def lookup_error_code(code: str) -> ErrorCode | None:
    """Look up an error code by its string value."""
    return _registry.get(code)


def list_error_codes() -> list[ErrorCode]:
    """Return all registered error codes."""
    return list(_registry.values())


def unregistered_error_code(code: str) -> ErrorCode:
    """Return a synthetic ErrorCode for an unregistered code."""
    return ErrorCode(
        code=code,
        producer="unknown",
        consumer="unknown",
        production_severity="unknown",
        clean_host_severity="unknown",
        recoverability="unknown",
        description=f"Unregistered error code: {code}",
    )


def build_registry_report() -> dict[str, Any]:
    """Build a structured report of the error registry."""
    return {
        "schema_version": ERROR_REGISTRY_SCHEMA_VERSION,
        "registered_count": len(_registry),
        "codes": [
            {
                "code": ec.code,
                "producer": ec.producer,
                "consumer": ec.consumer,
                "production_severity": ec.production_severity,
                "clean_host_severity": ec.clean_host_severity,
                "recoverability": ec.recoverability,
                "description": ec.description[:80],
            }
            for ec in sorted(_registry.values(), key=lambda e: e.code)
        ],
    }


# ── Built-in error codes ───────────────────────────────────────────────────
_BUILTIN_ERROR_CODES: list[ErrorCode] = [
    ErrorCode(
        code="crystallized_file_unparseable",
        producer="crystallized.py",
        consumer="monitor",
        production_severity="warning",
        clean_host_severity="error",
        recoverability="manual",
        description="A crystallized markdown file could not be parsed",
    ),
    ErrorCode(
        code="source_cursor_not_found",
        producer="exposure_rollup.py",
        consumer="exposure_rollup",
        production_severity="warning",
        clean_host_severity="error",
        recoverability="auto",
        description="Source cursor record not found in source records (compaction)",
    ),
    ErrorCode(
        code="legacy_source_cursor_missing",
        producer="exposure_rollup.py",
        consumer="exposure_rollup",
        production_severity="info",
        clean_host_severity="warning",
        recoverability="auto",
        description="Legacy rollup row without source_cursor_record_id",
    ),
    ErrorCode(
        code="execution_gate_permit_invalid",
        producer="exposure_rollup.py",
        consumer="execution_gate",
        production_severity="error",
        clean_host_severity="error",
        recoverability="manual",
        description="Execution gate permit is invalid or expired",
    ),
    ErrorCode(
        code="v2_exposure_schema_era_unhealthy",
        producer="monitor",
        consumer="monitor",
        production_severity="fail",
        clean_host_severity="fail",
        recoverability="manual",
        description="V2 exposure schema-era readiness check failed",
    ),
    ErrorCode(
        code="candidate_queue_read_error",
        producer="crystallized.py",
        consumer="candidate_clusters",
        production_severity="warning",
        clean_host_severity="error",
        recoverability="auto",
        description="Candidate queue could not be read",
    ),
    ErrorCode(
        code="index_sync_error",
        producer="index.py",
        consumer="index_sync",
        production_severity="warning",
        clean_host_severity="error",
        recoverability="auto",
        description="Index sync operation failed",
    ),
    ErrorCode(
        code="embedder_unavailable",
        producer="embedder.py",
        consumer="vector_edge_proposer",
        production_severity="info",
        clean_host_severity="warning",
        recoverability="auto",
        description="Embedder model is not available",
    ),
    ErrorCode(
        code="jsonl_read_error",
        producer="jsonl_io.py",
        consumer="jsonl_io",
        production_severity="warning",
        clean_host_severity="error",
        recoverability="auto",
        description="JSONL file could not be read or parsed",
    ),
    ErrorCode(
        code="owner_review_reply_tool_not_called",
        producer="__init__.py",
        consumer="owner_actions",
        production_severity="warning",
        clean_host_severity="warning",
        recoverability="manual",
        description="Owner review reply was not processed by the tool",
    ),
    ErrorCode(
        code="lane_disabled",
        producer="llm_contradiction_lane.py",
        consumer="cognitive_loop",
        production_severity="info",
        clean_host_severity="info",
        recoverability="auto",
        description="Automatic lane is disabled via knob",
    ),
    ErrorCode(
        code="llm_unavailable",
        producer="llm_contradiction_lane.py",
        consumer="cognitive_loop",
        production_severity="info",
        clean_host_severity="warning",
        recoverability="auto",
        description="LLM is not available for this lane",
    ),
]

for _ec in _BUILTIN_ERROR_CODES:
    register_error_code(_ec)