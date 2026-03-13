from __future__ import annotations

import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir


_SUCCESS_MARKERS = ("success", "won", "positive", "completed", "good", "dogru")
_FAILURE_MARKERS = ("fail", "failed", "negative", "dropped", "wrong", "yanlis")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _collect_decision_files(workspace: Path, max_files: int = 20) -> list[Path]:
    roots = [workspace, resolve_elyan_data_dir() / "notes", resolve_elyan_data_dir() / "journal"]
    patterns = ("*decision*.md", "*journal*.md", "*retrospective*.md", "*postmortem*.md")
    found: list[tuple[float, Path]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for pattern in patterns:
            for path in root.rglob(pattern):
                if not path.is_file():
                    continue
                key = str(path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                try:
                    mtime = float(path.stat().st_mtime)
                except Exception:
                    mtime = 0.0
                found.append((mtime, path))
    found.sort(key=lambda item: item[0], reverse=True)
    return [row[1] for row in found[: max(1, max_files)]]


def _detect_outcome(text: str) -> str:
    low = text.lower()
    if any(marker in low for marker in _SUCCESS_MARKERS):
        return "success"
    if any(marker in low for marker in _FAILURE_MARKERS):
        return "failure"
    return "unknown"


def _extract_category(text: str) -> str:
    low = text.lower()
    if "investment" in low or "yatirim" in low:
        return "investment"
    if "technical" in low or "architecture" in low or "teknik" in low:
        return "technical"
    if "hiring" in low or "team" in low:
        return "team"
    if "product" in low or "roadmap" in low:
        return "product"
    return "general"


def _write_report(result: dict[str, Any]) -> str:
    report_dir = resolve_elyan_data_dir() / "reports" / "ai_decision_journal"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"decision_journal_{stamp}.md"
    lines = [
        "# AI Decision Journal",
        "",
        f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Decisions tracked: {result.get('decision_count', 0)}",
        f"- Known outcome ratio: {result.get('known_outcome_ratio_pct', 0)}%",
        f"- Success ratio: {result.get('success_ratio_pct', 0)}%",
        "",
        "## Category Breakdown",
    ]
    for row in result.get("category_breakdown", []):
        lines.append(f"- {row.get('category')}: {row.get('count')}")
    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return str(out)


async def run_ai_decision_journal_module(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = payload if isinstance(payload, dict) else {}
    workspace = Path(str(req.get("workspace") or Path.cwd())).expanduser().resolve()

    raw_decisions = req.get("decisions", [])
    rows: list[dict[str, Any]] = []
    if isinstance(raw_decisions, dict):
        raw_decisions = [raw_decisions]
    if isinstance(raw_decisions, list):
        for item in raw_decisions:
            if isinstance(item, dict):
                rows.append(dict(item))
            elif isinstance(item, str) and _normalize(item):
                rows.append({"decision": _normalize(item)})

    files_used: list[str] = []
    if not rows:
        files = _collect_decision_files(workspace, max_files=int(req.get("max_files", 20) or 20))
        for path in files:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            lines = [_normalize(row) for row in content.splitlines() if _normalize(row)]
            for line in lines[:40]:
                rows.append({"decision": line})
            if lines:
                files_used.append(str(path))

    if not rows:
        return {
            "success": True,
            "module_id": "ai_decision_journal",
            "status": "no_decisions",
            "decision_count": 0,
            "known_outcome_ratio_pct": 0,
            "success_ratio_pct": 0,
            "category_breakdown": [],
            "files_used": [],
        }

    enriched: list[dict[str, Any]] = []
    category_counter: Counter[str] = Counter()
    known = 0
    successes = 0
    for row in rows:
        text = _normalize(str(row.get("decision") or row.get("summary") or ""))
        if not text:
            continue
        category = _normalize(str(row.get("category") or "")) or _extract_category(text)
        outcome = _normalize(str(row.get("outcome") or "")) or _detect_outcome(text)
        if outcome in {"success", "failure"}:
            known += 1
            if outcome == "success":
                successes += 1
        category_counter[category] += 1
        enriched.append(
            {
                "decision": text[:220],
                "category": category,
                "outcome": outcome,
            }
        )

    total = len(enriched)
    known_ratio = (known / total * 100.0) if total > 0 else 0.0
    success_ratio = (successes / known * 100.0) if known > 0 else 0.0
    category_rows = [{"category": k, "count": int(v)} for k, v in category_counter.most_common(8)]

    result = {
        "success": True,
        "module_id": "ai_decision_journal",
        "status": "ok",
        "generated_at": int(time.time()),
        "decision_count": total,
        "decisions": enriched[:120],
        "known_outcome_ratio_pct": round(known_ratio, 2),
        "success_ratio_pct": round(success_ratio, 2),
        "category_breakdown": category_rows,
        "summary_lines": [
            f"Tracked {total} decisions.",
            f"Known outcomes: {known}.",
            f"Historical success rate: {success_ratio:.1f}%" if known > 0 else "Historical success rate unavailable.",
        ],
        "files_used": files_used,
    }
    result["report_path"] = _write_report(result)
    return result


__all__ = ["run_ai_decision_journal_module"]
