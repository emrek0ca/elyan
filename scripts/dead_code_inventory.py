#!/usr/bin/env python3
"""Generate a lightweight dead-code and unused-import inventory for Elyan."""

from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "site",
    "artifacts",
    "logs",
    "bot",  # legacy mirror tree, high-noise for cleanup inventory
    "bot/site",
}

DEFAULT_INCLUDE_DIRS = (
    "core",
    "cli",
    "tools",
    "security",
    "config",
    "handlers",
    "utils",
    "scripts",
)


@dataclass
class DefItem:
    path: str
    name: str
    line: int
    kind: str


def _normalize_rel(path: str) -> str:
    return str(path).replace("\\", "/").strip("/")


def _should_skip(path: Path, root: Path, *, exclude_dirs: set[str], include_tests: bool) -> bool:
    rel = _normalize_rel(path.relative_to(root))
    if not include_tests and rel.startswith("tests/"):
        return True
    for d in exclude_dirs:
        d_norm = _normalize_rel(d)
        if not d_norm:
            continue
        if rel == d_norm or rel.startswith(f"{d_norm}/"):
            return True
    return False


def _iter_scan_roots(root: Path, include_dirs: list[str]) -> Iterable[Path]:
    if not include_dirs:
        yield root
        return
    for inc in include_dirs:
        candidate = (root / inc).resolve()
        if candidate.exists() and candidate.is_dir() and candidate != root:
            yield candidate


def _iter_py_files(
    root: Path,
    *,
    include_dirs: list[str],
    exclude_dirs: set[str],
    include_tests: bool,
) -> Iterable[Path]:
    for scan_root in _iter_scan_roots(root, include_dirs):
        for p in scan_root.rglob("*.py"):
            if _should_skip(p, root, exclude_dirs=exclude_dirs, include_tests=include_tests):
                continue
            yield p


def _module_ast(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        return None


def _collect_defs_and_uses(path: Path, tree: ast.AST) -> tuple[list[DefItem], set[str], list[dict]]:
    defs: list[DefItem] = []
    uses: set[str] = set()
    imports: list[dict] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.append(DefItem(path=str(path), name=node.name, line=node.lineno, kind="function"))
        elif isinstance(node, ast.ClassDef):
            defs.append(DefItem(path=str(path), name=node.name, line=node.lineno, kind="class"))
        elif isinstance(node, ast.Name):
            uses.add(node.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({
                    "module": alias.name,
                    "name": alias.asname or alias.name.split(".")[-1],
                    "line": node.lineno,
                })
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                imports.append({
                    "module": f"{node.module or ''}",
                    "name": alias.asname or alias.name,
                    "line": node.lineno,
                })

    return defs, uses, imports


def build_inventory(
    root: Path,
    *,
    include_dirs: list[str] | None = None,
    exclude_dirs: set[str] | None = None,
    include_tests: bool = False,
) -> dict:
    include_dirs = list(include_dirs or list(DEFAULT_INCLUDE_DIRS))
    exclude_dirs = set(exclude_dirs or set(DEFAULT_EXCLUDE_DIRS))

    defs: list[DefItem] = []
    global_uses: set[str] = set()
    unused_imports: list[dict] = []
    python_files_scanned = 0

    for file in _iter_py_files(
        root,
        include_dirs=include_dirs,
        exclude_dirs=exclude_dirs,
        include_tests=include_tests,
    ):
        python_files_scanned += 1
        tree = _module_ast(file)
        if tree is None:
            continue

        file_defs, file_uses, file_imports = _collect_defs_and_uses(file, tree)
        defs.extend(file_defs)
        global_uses.update(file_uses)

        for imp in file_imports:
            name = imp["name"]
            if name.startswith("_"):
                continue
            if name not in file_uses:
                unused_imports.append(
                    {
                        "path": str(file.relative_to(root)),
                        "name": name,
                        "module": imp["module"],
                        "line": imp["line"],
                    }
                )

    def_count = defaultdict(int)
    for item in defs:
        def_count[item.name] += 1

    dead_candidates = []
    for item in defs:
        if item.name.startswith("_"):
            continue
        if item.name in {"main", "run", "setup"}:
            continue
        if item.name not in global_uses:
            dead_candidates.append(
                {
                    "path": str(Path(item.path).relative_to(root)),
                    "name": item.name,
                    "line": item.line,
                    "kind": item.kind,
                    "note": "definition name not referenced in AST name usage",
                }
            )

    # second pass: definitions with a single occurrence are more suspicious
    dead_candidates.sort(key=lambda x: (x["path"], x["line"]))
    for c in dead_candidates:
        c["definition_count"] = int(def_count.get(c["name"], 1))

    # quick wins: very likely low-risk cleanup candidates
    quick_dead = [c for c in dead_candidates if int(c.get("definition_count", 1)) == 1][:120]
    quick_unused = unused_imports[:200]

    return {
        "root": str(root),
        "scope": {
            "include_dirs": include_dirs,
            "exclude_dirs": sorted(exclude_dirs),
            "include_tests": include_tests,
        },
        "dead_code_candidates": dead_candidates,
        "unused_imports": unused_imports,
        "quick_wins": {
            "dead_code_candidates": quick_dead,
            "unused_imports": quick_unused,
            "summary": {
                "dead_code_candidates": len(quick_dead),
                "unused_imports": len(quick_unused),
            },
        },
        "summary": {
            "python_files_scanned": python_files_scanned,
            "dead_code_candidates": len(dead_candidates),
            "unused_imports": len(unused_imports),
        },
    }


def write_reports(inventory: dict, out_json: Path, out_md: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    out_json.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = inventory.get("summary", {})
    dead = inventory.get("dead_code_candidates", [])[:80]
    unused = inventory.get("unused_imports", [])[:120]
    quick = inventory.get("quick_wins", {})
    quick_dead = quick.get("dead_code_candidates", [])[:40]
    quick_unused = quick.get("unused_imports", [])[:40]
    scope = inventory.get("scope", {})

    lines = [
        "# Dead Code Inventory",
        "",
        "## Scan Scope",
        "",
        f"- Include dirs: {', '.join(scope.get('include_dirs', [])) or '(all)'}",
        f"- Exclude dirs: {', '.join(scope.get('exclude_dirs', [])) or '(none)'}",
        f"- Include tests: {scope.get('include_tests', False)}",
        "",
        "## Summary",
        "",
        f"- Files scanned: {summary.get('python_files_scanned', 0)}",
        f"- Dead code candidates: {summary.get('dead_code_candidates', 0)}",
        f"- Unused imports: {summary.get('unused_imports', 0)}",
        f"- Quick wins (dead code): {quick.get('summary', {}).get('dead_code_candidates', 0)}",
        f"- Quick wins (unused imports): {quick.get('summary', {}).get('unused_imports', 0)}",
        "",
        "## Dead Code Candidates (top 80)",
        "",
    ]
    if dead:
        for item in dead:
            lines.append(
                f"- {item['path']}:{item['line']} `{item['kind']} {item['name']}` (defs={item.get('definition_count', 1)})"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Unused Imports (top 120)", ""])
    if unused:
        for item in unused:
            lines.append(f"- {item['path']}:{item['line']} `{item['name']}` from `{item['module']}`")
    else:
        lines.append("- None")

    lines.extend(["", "## Quick Wins (top 40 + 40)", ""])
    if quick_dead:
        lines.append("### Dead Code")
        for item in quick_dead:
            lines.append(
                f"- {item['path']}:{item['line']} `{item['kind']} {item['name']}` (defs={item.get('definition_count', 1)})"
            )
    else:
        lines.append("- Dead Code: None")
    if quick_unused:
        lines.append("")
        lines.append("### Unused Imports")
        for item in quick_unused:
            lines.append(f"- {item['path']}:{item['line']} `{item['name']}` from `{item['module']}`")
    else:
        lines.append("- Unused Imports: None")

    out_md.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Dead code inventory generator")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out-json", default="artifacts/dead_code_inventory.json")
    parser.add_argument("--out-md", default="artifacts/dead_code_inventory.md")
    parser.add_argument(
        "--include-dir",
        action="append",
        default=[],
        help="Directory to include (repeatable). Defaults to focused core dirs when omitted.",
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help="Directory to exclude (repeatable).",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include tests/ tree in the inventory scan.",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    include_dirs = [d.strip() for d in (args.include_dir or []) if str(d).strip()]
    extra_excludes = {d.strip() for d in (args.exclude_dir or []) if str(d).strip()}
    exclude_dirs = set(DEFAULT_EXCLUDE_DIRS).union(extra_excludes)

    inventory = build_inventory(
        root,
        include_dirs=include_dirs or list(DEFAULT_INCLUDE_DIRS),
        exclude_dirs=exclude_dirs,
        include_tests=bool(args.include_tests),
    )
    write_reports(inventory, Path(args.out_json).expanduser().resolve(), Path(args.out_md).expanduser().resolve())

    print(json.dumps(inventory.get("summary", {}), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
