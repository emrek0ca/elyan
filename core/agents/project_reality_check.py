from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _load_project_plan(workspace: Path) -> dict[str, Any]:
    candidates = [workspace / "project_plan.md", workspace / "roadmap.md", workspace / "plan.md"]
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        return {
            "name": path.stem,
            "roadmap": [row.strip("- ") for row in content.splitlines() if row.strip().startswith("-")][:30],
            "tech_plan": content[:4000],
            "market_evidence": "",
            "budget": 0,
            "team_size": 0,
            "timeline_weeks": 0,
            "source_path": str(path),
        }
    return {}


def _risk_from_scale(roadmap_len: int, team_size: int, timeline_weeks: int) -> float:
    if roadmap_len <= 0:
        return 70.0
    if team_size <= 0:
        return 65.0
    capacity = max(1.0, float(team_size * max(1, timeline_weeks)))
    load = float(roadmap_len) / capacity
    if load >= 1.6:
        return 85.0
    if load >= 1.1:
        return 65.0
    if load >= 0.7:
        return 45.0
    return 30.0


def _risk_from_budget(budget: float, team_size: int, timeline_weeks: int) -> float:
    if budget <= 0:
        return 75.0
    burn_est = max(1.0, float(team_size * max(1, timeline_weeks)) * 800.0)
    ratio = budget / burn_est
    if ratio < 0.5:
        return 85.0
    if ratio < 0.9:
        return 65.0
    if ratio < 1.2:
        return 45.0
    return 30.0


def _risk_from_market(market_evidence: str) -> float:
    text = _normalize(market_evidence).lower()
    if not text:
        return 80.0
    strong = ("customer", "users", "revenue", "pilot", "paid", "demand")
    weak = ("idea", "hypothesis", "maybe", "guess")
    score = 50.0
    if any(token in text for token in strong):
        score -= 25.0
    if any(token in text for token in weak):
        score += 20.0
    return max(15.0, min(90.0, score))


def _recommendation(score: float) -> str:
    if score >= 75:
        return "go"
    if score >= 55:
        return "revise"
    return "hold"


def _write_report(result: dict[str, Any]) -> str:
    report_dir = resolve_elyan_data_dir() / "reports" / "project_reality_check"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"project_reality_{stamp}.md"
    lines = [
        "# Project Reality Check",
        "",
        f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Feasibility score: {result.get('feasibility_score', 0)}",
        f"- Recommendation: {result.get('recommendation', '')}",
        "",
        "## Risk Register",
    ]
    for row in result.get("risk_register", []):
        lines.append(f"- {row.get('risk')}: {row.get('score')} ({row.get('note')})")
    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return str(out)


async def run_project_reality_check_module(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = payload if isinstance(payload, dict) else {}
    workspace = Path(str(req.get("workspace") or Path.cwd())).expanduser().resolve()

    project = req.get("project") if isinstance(req.get("project"), dict) else {}
    if not project:
        project = {
            "name": req.get("name"),
            "roadmap": req.get("roadmap"),
            "tech_plan": req.get("tech_plan"),
            "market_evidence": req.get("market_evidence"),
            "budget": req.get("budget"),
            "team_size": req.get("team_size"),
            "timeline_weeks": req.get("timeline_weeks"),
        }

    plan_fallback = _load_project_plan(workspace) if not any(project.values()) else {}
    if plan_fallback:
        project = {**plan_fallback, **{k: v for k, v in project.items() if v not in (None, "", [])}}

    roadmap = project.get("roadmap", [])
    if isinstance(roadmap, str):
        roadmap = [row.strip() for row in roadmap.splitlines() if row.strip()]
    if not isinstance(roadmap, list):
        roadmap = []

    try:
        budget = float(project.get("budget") or 0)
    except Exception:
        budget = 0.0
    try:
        team_size = int(project.get("team_size") or 0)
    except Exception:
        team_size = 0
    try:
        timeline_weeks = int(project.get("timeline_weeks") or 0)
    except Exception:
        timeline_weeks = 0

    tech_plan = _normalize(str(project.get("tech_plan") or ""))
    market_evidence = _normalize(str(project.get("market_evidence") or ""))

    tech_risk = _risk_from_scale(len(roadmap) + (8 if not tech_plan else 0), team_size, timeline_weeks)
    cost_risk = _risk_from_budget(budget, max(1, team_size), max(1, timeline_weeks))
    market_risk = _risk_from_market(market_evidence)

    weighted_risk = (tech_risk * 0.45) + (cost_risk * 0.25) + (market_risk * 0.30)
    feasibility = max(0.0, 100.0 - weighted_risk)
    recommendation = _recommendation(feasibility)

    risk_register = [
        {
            "risk": "technical_execution",
            "score": round(tech_risk, 2),
            "note": "Scope/team/timeline alignment",
        },
        {
            "risk": "cost_runway",
            "score": round(cost_risk, 2),
            "note": "Budget sufficiency vs estimated burn",
        },
        {
            "risk": "market_validation",
            "score": round(market_risk, 2),
            "note": "Strength of demand evidence",
        },
    ]

    result = {
        "success": True,
        "module_id": "project_reality_check",
        "status": "ok" if any(project.values()) else "insufficient_input",
        "generated_at": int(time.time()),
        "project_name": _normalize(str(project.get("name") or "")),
        "feasibility_score": round(feasibility, 2),
        "recommendation": recommendation,
        "risk_register": risk_register,
        "summary_lines": [
            f"Feasibility score: {feasibility:.1f}",
            f"Recommendation: {recommendation}",
        ],
        "input_source": project.get("source_path", "payload"),
    }
    result["report_path"] = _write_report(result)
    return result


__all__ = ["run_project_reality_check_module"]
