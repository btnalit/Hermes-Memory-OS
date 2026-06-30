#!/usr/bin/env python3
"""Identify and clean up smoke-test records from crystallized memory.

Smoke records (e.g. "smoke user msg", "smoke assistant msg") that entered
the production memory store during early development/testing are noise in
owner-approved crystallized memory.  This script:

  - Scans all *.md files under the crystallized root for records whose body
    contains smoke/test patterns.
  - Reports matches with record_id, file_name, and a body snippet.
  - With ``--execute``, revokes each matched record via
    ``CrystallizedMemoryService.revoke_record()`` (governed, audited).

Usage::

  # Dry-run — list all smoke records
  python scripts/memory_os_smoke_record_cleanup.py --hermes-home /root/.hermes

  # Execute — actually revoke them
  python scripts/memory_os_smoke_record_cleanup.py --hermes-home /root/.hermes --execute

The script is safe to re-run: already-revoked records are skipped.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# -- project root (scripts/ → repo root) --
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _smoke_patterns() -> list[str]:
    """Return case-insensitive substrings that identify smoke/test records."""
    return [
        "smoke user msg",
        "smoke assistant msg",
        "smoke test message",
        "smoke test event",
    ]


def _is_smoke_body(body: str) -> tuple[bool, str]:
    """Check whether *body* matches a smoke pattern.

    Returns (is_smoke, matched_pattern).
    """
    lowered = body.lower()
    for pattern in _smoke_patterns():
        if pattern in lowered:
            return True, pattern
    return False, ""


def scan_smoke_records(hermes_home: str, *, profile: str = "default") -> list[dict[str, Any]]:
    """Scan all crystallized .md files for smoke records.

    Returns a list of dicts with ``record_id``, ``file_name``, ``body_snippet``,
    ``matched_pattern``, and ``canonical_state``.
    """
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.crystallized import CrystallizedMemoryService, MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(hermes_home, profile=profile)
    store = MemoryOSStore(roots)
    service = CrystallizedMemoryService(store)

    crystallized_root = roots.crystallized_root
    if not crystallized_root.exists():
        print(f"[cleanup] crystallized root not found: {crystallized_root}")
        return []

    matches: list[dict[str, Any]] = []
    for path in sorted(crystallized_root.glob("*.md")):
        for record in service.read_records(path.name):
            body = str(record.body or "")
            is_smoke, matched_pattern = _is_smoke_body(body)
            if not is_smoke:
                # also check frontmatter kind/tags for smoke markers
                fm = record.frontmatter or {}
                kind = str(fm.get("kind") or "").lower()
                tags = [str(t).lower() for t in (fm.get("tags") or [])]
                if "smoke" in kind or any("smoke" in t for t in tags):
                    matched_pattern = "smoke (frontmatter)"
                    is_smoke = True
            if is_smoke:
                record_id = str(record.frontmatter.get("id") or record.file_name)
                canonical_state = str(record.frontmatter.get("canonical_state") or "active")
                matches.append({
                    "record_id": record_id,
                    "file_name": record.file_name,
                    "canonical_state": canonical_state,
                    "matched_pattern": matched_pattern,
                    "body_snippet": body[:120].replace("\n", " ") + ("..." if len(body) > 120 else ""),
                })

    return matches


def execute_cleanup(
    hermes_home: str,
    matches: list[dict[str, Any]],
    *,
    profile: str = "default",
    revoked_by: str = "smoke_cleanup_script",
) -> dict[str, Any]:
    """Revoke matched smoke records via governed CrystallizedMemoryService."""
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.crystallized import CrystallizedMemoryService, MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(hermes_home, profile=profile)
    store = MemoryOSStore(roots)
    service = CrystallizedMemoryService(store)

    revoked: list[str] = []
    skipped: list[str] = []
    errors: list[dict[str, Any]] = []

    for match in matches:
        record_id = match["record_id"]
        # Skip already inactive records (idempotent)
        if match["canonical_state"] != "active":
            skipped.append(record_id)
            continue
        try:
            result = service.revoke_record(
                record_id,
                revoked_by=revoked_by,
                reason=f"smoke test record cleanup: matched pattern '{match['matched_pattern']}'",
            )
            if result.get("already_revoked"):
                skipped.append(record_id)
            else:
                revoked.append(record_id)
        except KeyError:
            errors.append({"record_id": record_id, "error": "record_id_not_found"})
        except Exception as exc:
            errors.append({"record_id": record_id, "error": str(exc)})

    return {
        "revoked_count": len(revoked),
        "revoked_ids": revoked,
        "skipped_count": len(skipped),
        "skipped_ids": skipped,
        "error_count": len(errors),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean up smoke-test records from crystallized memory")
    parser.add_argument("--hermes-home", required=True, help="Path to HERMES_HOME (e.g. /root/.hermes)")
    parser.add_argument("--profile", default="default", help="Memory-OS profile (default: 'default')")
    parser.add_argument("--execute", action="store_true", help="Actually revoke records (default: dry-run)")
    args = parser.parse_args(argv)

    hermes_home = Path(args.hermes_home).expanduser().resolve()
    if not hermes_home.is_dir():
        print(f"ERROR: HERMES_HOME does not exist: {hermes_home}", file=sys.stderr)
        return 1

    print(f"[cleanup] Scanning crystallized records in {hermes_home} (profile={args.profile})")
    matches = scan_smoke_records(str(hermes_home), profile=args.profile)

    if not matches:
        print("[cleanup] No smoke records found.")
        return 0

    print(f"\n[cleanup] Found {len(matches)} smoke record(s):\n")
    for i, match in enumerate(matches, 1):
        print(f"  {i}. [{match['canonical_state']}] {match['record_id']}")
        print(f"     File:     {match['file_name']}")
        print(f"     Pattern:  {match['matched_pattern']}")
        print(f"     Snippet:  {match['body_snippet']}")
        print()

    if not args.execute:
        print("[cleanup] DRY RUN — re-run with --execute to revoke these records.")
        return 0

    print("[cleanup] Executing revocations via CrystallizedMemoryService...")
    result = execute_cleanup(str(hermes_home), matches, profile=args.profile)

    print(f"\n[cleanup] Done:")
    print(f"  Revoked:  {result['revoked_count']}")
    for rid in result["revoked_ids"]:
        print(f"    ✓ {rid}")
    print(f"  Skipped:  {result['skipped_count']}")
    for rid in result["skipped_ids"]:
        print(f"    - {rid} (already inactive)")
    if result["error_count"]:
        print(f"  Errors:   {result['error_count']}")
        for err in result["errors"]:
            print(f"    ✗ {err['record_id']}: {err['error']}")

    return 0 if result["error_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
