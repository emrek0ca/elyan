from __future__ import annotations

import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir


_TOPIC_MARKERS: dict[str, tuple[str, ...]] = {
    "ai_agents": ("agent", "agents", "autonomous", "orchestration"),
    "automation": ("automation", "workflow", "scheduler", "cron"),
    "saas_architecture": ("saas", "architecture", "multitenant", "backend", "api"),
    "ml_systems": ("ml", "model", "inference", "training", "eval"),
    "devops": ("docker", "kubernetes", "ci", "deployment", "infra"),
    "product_strategy": ("pricing", "go-to-market", "market", "roadmap", "strategy"),
}

_ALLOWED_SUFFIXES = {".md", ".txt", ".py", ".json", ".yaml", ".yml", ".ts", ".js"}


def _collect_candidate_files(workspace: Path, max_files: int = 120) -> list[Path]:
    roots = [workspace, resolve_elyan_data_dir() / "notes", resolve_elyan_data_dir() / "knowledge"]
    found: list[tuple[float, Path]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in _ALLOWED_SUFFIXES:
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


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _topic_hits(text: str) -> set[str]:
    low = text.lower()
    hits: set[str] = set()
    for topic, markers in _TOPIC_MARKERS.items():
        if any(marker in low for marker in markers):
            hits.add(topic)
    return hits


def _write_report(result: dict[str, Any]) -> str:
    report_dir = resolve_elyan_data_dir() / "reports" / "personal_knowledge_miner"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"knowledge_miner_{stamp}.md"
    lines = [
        "# AI Personal Knowledge Miner",
        "",
        f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Files analyzed: {result.get('files_analyzed', 0)}",
        "",
        "## Expertise Map",
    ]
    for row in result.get("expertise", []):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {row.get('topic')}: confidence={row.get('confidence')} coverage={row.get('file_coverage')}"
        )
    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return str(out)


async def run_personal_knowledge_miner_module(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = payload if isinstance(payload, dict) else {}
    workspace = Path(str(req.get("workspace") or Path.cwd())).expanduser().resolve()
    max_files = int(req.get("max_files", 120) or 120)

    raw_paths = req.get("file_paths", [])
    files: list[Path] = []
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    if isinstance(raw_paths, list):
        for item in raw_paths:
            path = Path(str(item or "")).expanduser()
            if path.exists() and path.is_file():
                files.append(path)

    if not files:
        files = _collect_candidate_files(workspace, max_files=max_files)

    if not files:
        return {
            "success": True,
            "module_id": "personal_knowledge_miner",
            "status": "no_files",
            "files_analyzed": 0,
            "expertise": [],
            "summary_lines": ["No candidate files found."],
        }

    topic_counter: Counter[str] = Counter()
    topic_file_hits: dict[str, set[str]] = {}

    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        sample = _normalize(content[:12000])
        hits = _topic_hits(sample)
        for topic in hits:
            topic_counter[topic] += 1
            topic_file_hits.setdefault(topic, set()).add(str(path))

    total_files = max(1, len(files))
    expertise_rows: list[dict[str, Any]] = []
    for topic, count in topic_counter.most_common(12):
        coverage = len(topic_file_hits.get(topic, set()))
        confidence = min(0.99, (coverage / total_files) * 1.4)
        expertise_rows.append(
            {
                "topic": topic,
                "count": int(count),
                "file_coverage": coverage,
                "confidence": round(confidence, 2),
            }
        )

    result = {
        "success": True,
        "module_id": "personal_knowledge_miner",
        "status": "ok" if expertise_rows else "weak_signals",
        "generated_at": int(time.time()),
        "files_analyzed": len(files),
        "expertise": expertise_rows,
        "summary_lines": [
            f"Analyzed {len(files)} files.",
            f"Expertise topics detected: {len(expertise_rows)}",
        ],
    }
    result["report_path"] = _write_report(result)
    return result


__all__ = ["run_personal_knowledge_miner_module"]
