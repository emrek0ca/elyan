from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir


_TOPIC_MARKERS: dict[str, tuple[str, ...]] = {
    "ai_agents": ("agent", "agents", "autonomous", "multi-agent"),
    "tool_orchestration": ("tool orchestration", "tooling", "orchestration", "workflow", "scheduler"),
    "memory_systems": ("memory", "vector", "rag", "retrieval", "knowledge graph"),
    "planning_algorithms": ("planning", "planner", "dag", "decomposition", "reasoning"),
    "llm_eval": ("eval", "evaluation", "benchmark", "verification", "quality gate"),
    "infra": ("docker", "kubernetes", "deployment", "ci", "runtime"),
}

_REQUIRED_SUBTOPICS: dict[str, tuple[str, ...]] = {
    "ai_agents": ("tool_orchestration", "memory_systems", "planning_algorithms"),
}

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "have",
    "will",
    "into",
    "your",
    "about",
    "you",
}


def _collect_signal_files(workspace: Path, max_files: int = 30) -> list[Path]:
    roots = [workspace, resolve_elyan_data_dir() / "notes", resolve_elyan_data_dir() / "research"]
    patterns = ("*learning*.md", "*research*.md", "*notes*.md", "*article*.md", "*youtube*.md", "*.txt")
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


def _normalize_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _extract_topics(items: list[str]) -> tuple[Counter, dict[str, set[str]]]:
    counts: Counter[str] = Counter()
    cooccur: dict[str, set[str]] = {}
    for raw in items:
        line = _normalize_line(raw).lower()
        if not line:
            continue

        matched: list[str] = []
        for topic, markers in _TOPIC_MARKERS.items():
            if any(marker in line for marker in markers):
                counts[topic] += 1
                matched.append(topic)

        # lightweight keyword capture for unseen but frequent tokens
        for token in re.findall(r"[a-z0-9][a-z0-9_\-]{2,}", line):
            if token in _STOPWORDS:
                continue
            if token in _TOPIC_MARKERS:
                continue
            if token.startswith("http"):
                continue
            if token in {"api", "sdk", "cli"}:
                counts[token] += 1

        for topic in matched:
            bucket = cooccur.setdefault(topic, set())
            for other in matched:
                if other != topic:
                    bucket.add(other)

    return counts, cooccur


def _knowledge_gaps(counts: Counter) -> list[str]:
    gaps: list[str] = []
    for parent, children in _REQUIRED_SUBTOPICS.items():
        if counts.get(parent, 0) <= 0:
            continue
        missing = [child for child in children if counts.get(child, 0) <= 0]
        if missing:
            gaps.append(f"{parent}: missing {', '.join(missing)}")
    return gaps


def _write_report(result: dict[str, Any]) -> str:
    report_dir = resolve_elyan_data_dir() / "reports" / "automatic_learning_tracker"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"learning_tracker_{stamp}.md"

    lines = [
        "# Automatic Learning Tracker",
        "",
        f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Signals analyzed: {result.get('signal_count', 0)}",
        "",
        "## Topic Graph",
    ]
    for row in result.get("topic_graph", []):
        if not isinstance(row, dict):
            continue
        lines.append(f"- {row.get('topic')}: {row.get('count')} ({', '.join(row.get('links', [])) or 'no links'})")

    lines.extend(["", "## Learning Gaps", ""])
    gaps = result.get("knowledge_gaps", [])
    if not gaps:
        lines.append("- No major gaps detected from current signals.")
    else:
        for gap in gaps:
            lines.append(f"- {gap}")

    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return str(out)


async def run_automatic_learning_tracker_module(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = payload if isinstance(payload, dict) else {}
    workspace = Path(str(req.get("workspace") or Path.cwd())).expanduser().resolve()

    raw_items = req.get("learning_items", [])
    items: list[str] = []
    if isinstance(raw_items, str):
        raw_items = [raw_items]
    if isinstance(raw_items, list):
        items.extend([_normalize_line(row) for row in raw_items if _normalize_line(str(row))])

    files_used: list[str] = []
    if not items:
        files = _collect_signal_files(workspace, max_files=int(req.get("max_files", 30) or 30))
        for path in files:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            lines = [_normalize_line(row) for row in content.splitlines() if _normalize_line(row)]
            if lines:
                items.extend(lines[:30])
                files_used.append(str(path))

    if not items:
        return {
            "success": True,
            "module_id": "automatic_learning_tracker",
            "status": "no_signals",
            "signal_count": 0,
            "topic_graph": [],
            "knowledge_gaps": [],
            "summary_lines": ["No learning signals found."],
            "files_used": [],
        }

    counts, cooccur = _extract_topics(items)
    topic_rows: list[dict[str, Any]] = []
    for topic, count in counts.most_common(12):
        links = sorted(cooccur.get(topic, set()))[:6]
        topic_rows.append({"topic": topic, "count": int(count), "links": links})

    gaps = _knowledge_gaps(counts)
    result = {
        "success": True,
        "module_id": "automatic_learning_tracker",
        "status": "ok",
        "generated_at": int(time.time()),
        "signal_count": len(items),
        "topic_graph": topic_rows,
        "knowledge_gaps": gaps,
        "summary_lines": [
            f"Top topic: {topic_rows[0]['topic']} ({topic_rows[0]['count']})" if topic_rows else "No dominant topic",
            f"Knowledge gaps: {len(gaps)}",
        ],
        "files_used": files_used,
    }
    result["report_path"] = _write_report(result)

    # compact json artifact for downstream modules
    out_dir = resolve_elyan_data_dir() / "learning" / "snapshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


__all__ = ["run_automatic_learning_tracker_module"]
