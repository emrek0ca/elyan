#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.repo_policy import find_disallowed_markdown_paths  # noqa: E402


def _staged_paths() -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(proc.stderr.strip() or "git diff failed", file=sys.stderr)
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main() -> int:
    violations = find_disallowed_markdown_paths(_staged_paths())
    if not violations:
        return 0
    print("Repository markdown policy blocked this commit.", file=sys.stderr)
    print("Allowed project markdown files: PROGRESS.md", file=sys.stderr)
    print("Disallowed staged markdown files:", file=sys.stderr)
    for path in violations:
        print(f" - {path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
