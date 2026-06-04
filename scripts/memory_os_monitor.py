"""Neutral Memory-OS monitor CLI wrapper.

`memory_os_3_200_monitor.py` remains the compatibility entrypoint while the
monitor is split. New runbooks should prefer this neutral name.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.memory_os_3_200_monitor import main


if __name__ == "__main__":
    raise SystemExit(main())
