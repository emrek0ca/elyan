from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir


_ACTION_PATTERNS = (
    "todo",
    "action",
    "aksiyon",
    "assign",
    "sorumlu",
    "deadline",
    "takip",
)


def _collect_transcript_files(workspace: Path, max_files: int = 20) -> list[Path]:
    roots = [workspace, resolve_elyan_data_dir() / "meetings", resolve_elyan_data_dir() / "notes"]
    patterns = ("*meeting*.md", "*toplanti*.md", "*transcript*.txt", "*minutes*.md")
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


def _split_lines(text: str) -> list[str]:
    lines = []
    for row in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", row).strip()
        if line:
            lines.append(line)
    return lines


def _line_relevance(line: str, focus_topics: list[str]) -> float:
    if not line:
        return 0.0
    low = line.lower()
    if not focus_topics:
        return 0.5
    score = 0.0
    for topic in focus_topics:
        token = str(topic or "").strip().lower()
        if not token:
            continue
        if token in low:
            score += 1.0
        else:
            parts = [p for p in re.split(r"[^a-z0-9]+", token) if p]
            if parts and any(part in low for part in parts):
                score += 0.5
    max_score = max(1.0, float(len(focus_topics)))
    return min(1.0, score / max_score)


def _extract_actions(lines: list[str], limit: int = 20) -> list[str]:
    actions: list[str] = []
    for line in lines:
        low = line.lower()
        if any(marker in low for marker in _ACTION_PATTERNS):
            actions.append(line)
        if len(actions) >= limit:
            break
    return actions


def _write_report(result: dict[str, Any]) -> str:
    report_dir = resolve_elyan_data_dir() / "reports" / "invisible_meeting_assistant"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"meeting_assistant_{stamp}.md"
    lines = [
        "# Invisible Meeting Assistant",
        "",
        f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Meetings analyzed: {result.get('meetings_analyzed', 0)}",
        f"- Relevant line ratio: {result.get('relevant_ratio_pct', 0)}%",
        f"- Irrelevant share: {result.get('irrelevant_ratio_pct', 0)}%",
        "",
        "## Summary",
    ]
    for row in result.get("summary_lines", []):
        lines.append(f"- {row}")

    lines.extend(["", "## Action Items", ""])
    for row in result.get("action_items", []):
        lines.append(f"- {row}")
    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return str(out)


async def run_invisible_meeting_assistant_module(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = payload if isinstance(payload, dict) else {}
    workspace = Path(str(req.get("workspace") or Path.cwd())).expanduser().resolve()
    focus_topics = req.get("focus_topics", [])
    if isinstance(focus_topics, str):
        focus_topics = [focus_topics]
    topics = [str(item).strip() for item in focus_topics if str(item).strip()]

    files = _collect_transcript_files(workspace, max_files=int(req.get("max_files", 20) or 20))
    if not files:
        return {
            "success": True,
            "module_id": "invisible_meeting_assistant",
            "status": "no_transcripts",
            "meetings_analyzed": 0,
            "summary_lines": ["No meeting transcripts found."],
            "action_items": [],
            "relevant_ratio_pct": 0,
            "irrelevant_ratio_pct": 0,
        }

    total_lines = 0
    relevant_lines = 0
    all_lines: list[str] = []
    per_file: list[dict[str, Any]] = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        lines = _split_lines(content)
        if not lines:
            continue
        rel = [line for line in lines if _line_relevance(line, topics) >= 0.45]
        total_lines += len(lines)
        relevant_lines += len(rel)
        all_lines.extend(lines)
        per_file.append(
            {
                "path": str(path),
                "line_count": len(lines),
                "relevant_count": len(rel),
            }
        )

    if total_lines <= 0:
        return {
            "success": True,
            "module_id": "invisible_meeting_assistant",
            "status": "empty_transcripts",
            "meetings_analyzed": len(per_file),
            "summary_lines": ["Transcript files were found but contained no usable lines."],
            "action_items": [],
            "relevant_ratio_pct": 0,
            "irrelevant_ratio_pct": 0,
        }

    relevant_ratio = (float(relevant_lines) / float(total_lines)) * 100.0
    irrelevant_ratio = max(0.0, 100.0 - relevant_ratio)
    actions = _extract_actions(all_lines, limit=20)
    summary = [
        f"Toplam satir: {total_lines}",
        f"Ilgili satir: {relevant_lines} ({relevant_ratio:.1f}%)",
        f"Sana alakasiz kisim: %{irrelevant_ratio:.1f}",
    ]
    if actions:
        summary.append(f"Aksiyon adaylari: {len(actions)}")

    result = {
        "success": True,
        "module_id": "invisible_meeting_assistant",
        "status": "ok",
        "generated_at": int(time.time()),
        "focus_topics": topics,
        "meetings_analyzed": len(per_file),
        "files": per_file,
        "summary_lines": summary,
        "action_items": actions,
        "relevant_ratio_pct": round(relevant_ratio, 2),
        "irrelevant_ratio_pct": round(irrelevant_ratio, 2),
    }
    result["report_path"] = _write_report(result)
    return result


__all__ = ["run_invisible_meeting_assistant_module"]
