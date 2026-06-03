#!/usr/bin/env python3
"""Serve the read-only Memory-OS monitoring dashboard."""

from __future__ import annotations

import argparse
import functools
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DASHBOARD_DIR = REPO_ROOT / "monitor_dashboard"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 3693


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bind host. Defaults to {DEFAULT_HOST}.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Bind port. Defaults to {DEFAULT_PORT}.")
    parser.add_argument(
        "--directory",
        type=Path,
        default=DEFAULT_DASHBOARD_DIR,
        help="Dashboard directory to serve. Defaults to monitor_dashboard.",
    )
    parser.add_argument("--snapshot-hermes-home", type=Path, help="Generate dashboard snapshots from this HERMES_HOME.")
    parser.add_argument("--snapshot-profile", default="main", help="Profile for generated snapshots. Default: main.")
    parser.add_argument("--snapshot-output", type=Path, help="Snapshot JS output path. Defaults to snapshot.generated.js in the served directory.")
    parser.add_argument(
        "--snapshot-interval-seconds",
        type=int,
        default=0,
        help="Refresh snapshot.generated.js every N seconds. Default: disabled.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    directory = args.directory.expanduser().resolve()
    if not directory.is_dir():
        raise SystemExit(f"Dashboard directory does not exist: {directory}")

    stop_event = threading.Event()
    refresh_thread: threading.Thread | None = None
    if args.snapshot_hermes_home:
        snapshot_output = (args.snapshot_output or (directory / "snapshot.generated.js")).expanduser().resolve()
        _write_dashboard_snapshot(
            hermes_home=args.snapshot_hermes_home.expanduser().resolve(),
            profile=str(args.snapshot_profile or "main"),
            output=snapshot_output,
        )
        if args.snapshot_interval_seconds > 0:
            refresh_thread = threading.Thread(
                target=_refresh_snapshots,
                kwargs={
                    "hermes_home": args.snapshot_hermes_home.expanduser().resolve(),
                    "profile": str(args.snapshot_profile or "main"),
                    "output": snapshot_output,
                    "interval_seconds": int(args.snapshot_interval_seconds),
                    "stop_event": stop_event,
                },
                daemon=True,
            )
            refresh_thread.start()

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving Memory-OS monitor dashboard on http://{args.host}:{args.port}/ from {directory}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        stop_event.set()
        if refresh_thread:
            refresh_thread.join(timeout=1)
        server.server_close()
    return 0


def _refresh_snapshots(
    *,
    hermes_home: Path,
    profile: str,
    output: Path,
    interval_seconds: int,
    stop_event: threading.Event,
) -> None:
    while not stop_event.wait(interval_seconds):
        try:
            _write_dashboard_snapshot(hermes_home=hermes_home, profile=profile, output=output)
        except Exception as exc:  # pragma: no cover - long-running service guard.
            print(f"Snapshot refresh failed: {exc}", flush=True)


def _write_dashboard_snapshot(*, hermes_home: Path, profile: str, output: Path) -> None:
    from memory_os_monitor_dashboard_snapshot import build_dashboard_snapshot, render_snapshot

    snapshot = build_dashboard_snapshot(hermes_home=hermes_home, profile=profile)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.write_text(render_snapshot(snapshot, output_format="js"), encoding="utf-8")
    tmp.replace(output)


if __name__ == "__main__":
    raise SystemExit(main())
