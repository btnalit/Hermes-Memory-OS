"""Machine-readable V7 promotion matrix metadata.

The long-form operator matrix lives in ignored local documentation. Runtime
monitors use this compact contract so public checkouts do not depend on private
docs for the V7 promotion-matrix component signal.
"""

from __future__ import annotations

from typing import Any


PROMOTION_MATRIX_SCHEMA_VERSION = "memory-os.v7_promotion_matrix.v0"

PROMOTION_MATRIX_COMPONENT: dict[str, Any] = {
    "schema_version": PROMOTION_MATRIX_SCHEMA_VERSION,
    "component": "promotion_matrix",
    "task_installed": True,
    "pipeline_liveness": "live-shadow",
    "autonomy_level": "shadow",
    "live_guard_registered": True,
    "live_applied": False,
    "actual_send": False,
    "actual_execute": False,
    "actual_identity_write": False,
    "actual_crystallized_approval": False,
}


def promotion_matrix_component() -> dict[str, Any]:
    return dict(PROMOTION_MATRIX_COMPONENT)
