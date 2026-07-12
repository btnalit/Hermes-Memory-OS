"""Lightweight index canonical_state update hook.

Extracted from ``index.py`` to break the crystallized ↔ index import cycle
(C2 lifecycle hook fault).  Both ``crystallized.py`` and ``index.py`` import
this module; it depends only on stdlib ``sqlite3`` and ``pathlib`` — never on
``crystallized`` or ``index`` — so no cycle is possible.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def update_canonical_state_in_index(
    index_path: Path,
    record_id: str,
    canonical_state: str,
) -> bool:
    """Update ``canonical_state`` in the index's ``crystallized_records`` table.

    Best-effort — if the index doesn't exist or the record isn't in it,
    the index sync will pick up the correct state on its next run.
    Returns ``True`` if a row was updated.
    """
    if not index_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(index_path))
        conn.execute("pragma journal_mode=WAL")
        conn.execute(
            "update crystallized_records set canonical_state = ? where id = ?",
            (canonical_state, record_id),
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error:
        return False
