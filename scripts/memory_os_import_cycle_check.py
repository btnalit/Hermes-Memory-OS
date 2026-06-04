#!/usr/bin/env python3
"""Static import-cycle check for Memory-OS core and module packages."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any, Iterable


IMPORT_CYCLE_SCHEMA_VERSION = "memory-os.import_cycle_check.v0"
DEFAULT_SCAN_ROOTS = ("plugins/memory/memory_os", "plugins/modules")


def run_import_cycle_check(repo_root: Path, *, scan_roots: Iterable[str | Path] = DEFAULT_SCAN_ROOTS) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    modules = _module_map(root, scan_roots)
    edges = {module: _imports_for(path, modules, module) for module, path in modules.items()}
    cycles = _strongly_connected_components(edges)
    return {
        "schema_version": IMPORT_CYCLE_SCHEMA_VERSION,
        "status": "pass" if not cycles else "fail",
        "cycle_count": len(cycles),
        "cycles": [{"modules": cycle} for cycle in cycles],
        "module_count": len(modules),
    }


def _module_map(repo_root: Path, scan_roots: Iterable[str | Path]) -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for scan_root in scan_roots:
        base = Path(scan_root)
        if not base.is_absolute():
            base = repo_root / base
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(repo_root).with_suffix("")
            modules[".".join(rel.parts)] = path
    return modules


def _imports_for(path: Path, modules: dict[str, Path], module_name: str) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in modules:
                    imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_import_from(module_name, node)
            if not resolved:
                continue
            if resolved in modules:
                imports.add(resolved)
            for alias in node.names:
                candidate = f"{resolved}.{alias.name}"
                if candidate in modules:
                    imports.add(candidate)
    return imports


def _resolve_import_from(module_name: str, node: ast.ImportFrom) -> str:
    if node.level <= 0:
        return node.module or ""
    parts = module_name.split(".")
    if node.level > len(parts):
        return node.module or ""
    base = parts[: -node.level]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _strongly_connected_components(edges: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in edges.get(node, set()):
            if target not in indexes:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indexes[target])
        if lowlinks[node] == indexes[node]:
            component: list[str] = []
            while True:
                item = stack.pop()
                on_stack.remove(item)
                component.append(item)
                if item == node:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for node in sorted(edges):
        if node not in indexes:
            visit(node)
    return sorted(components, key=lambda item: (len(item), item))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Repository root to scan.")
    parser.add_argument("--scan-root", action="append", dest="scan_roots", help="Relative or absolute root to scan.")
    args = parser.parse_args()
    report = run_import_cycle_check(
        Path(args.repo_root),
        scan_roots=args.scan_roots or DEFAULT_SCAN_ROOTS,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
