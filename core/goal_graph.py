"""
Goal graph extraction for complex multi-step user requests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .capability_router import get_capability_router


@dataclass
class GoalNode:
    node_id: str
    text: str
    domain: str
    objective: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "text": self.text,
            "domain": self.domain,
            "objective": self.objective,
        }


class GoalGraphPlanner:
    """Extracts staged intent graph from long user goals."""

    _SPLIT_PATTERNS = [
        r"\s+ve\s+sonra\s+",
        r"\s+ardından\s+",
        r"\s+ardindan\s+",
        r"\s+sonra\s+",
        r"\s+then\s+",
        r"\s+and then\s+",
        r"\s+\+\s+",
        r"\s*->\s*",
    ]

    def __init__(self):
        self.router = get_capability_router()

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "").strip())

    def _split_stages(self, text: str) -> list[str]:
        clean = self._normalize(text)
        if not clean:
            return []
        pattern = "(" + "|".join(self._SPLIT_PATTERNS) + ")"
        parts = [p.strip(" ,.;:") for p in re.split(pattern, clean) if p and not re.fullmatch(pattern, p)]
        # Fallback: explicit conjunctions and punctuation for very long prompts
        if len(parts) <= 1 and len(clean.split()) >= 14:
            rough = re.split(r"[.;]\s+|\s+ve\s+|\s+ve de\s+", clean)
            parts = [p.strip(" ,.;:") for p in rough if p and len(p.strip()) > 2]
        return parts[:8]

    def _extract_constraints(self, text: str) -> dict[str, Any]:
        t = text.lower()
        constraints: dict[str, Any] = {
            "preferred_output": "",
            "urgency": "",
            "quality_mode": "",
            "deliverables": [],
            "requires_evidence": False,
            "autonomy_preference": "",
            "proof_formats": [],
        }

        if any(k in t for k in ["pdf"]):
            constraints["preferred_output"] = "pdf"
        elif any(k in t for k in ["docx", "word"]):
            constraints["preferred_output"] = "docx"
        elif any(k in t for k in ["json", "yaml", "csv", "excel"]):
            constraints["preferred_output"] = "structured"
        elif any(k in t for k in ["sunum", "presentation", "ppt"]):
            constraints["preferred_output"] = "presentation"

        if any(k in t for k in ["acil", "hemen", "ivedi", "asap", "urgent"]):
            constraints["urgency"] = "high"

        if any(k in t for k in ["detaylı", "detayli", "kapsamlı", "kapsamli", "profesyonel", "publish-ready"]):
            constraints["quality_mode"] = "high"
        elif any(k in t for k in ["hızlı", "hizli", "kısa", "kisa", "özet", "ozet"]):
            constraints["quality_mode"] = "compact"

        deliverable_map = {
            "report": ["rapor", "report"],
            "document": ["dokuman", "doküman", "belge", "docx", "pdf"],
            "website": ["website", "web sitesi", "site", "landing page"],
            "app": ["uygulama", "app"],
            "game": ["oyun", "game"],
            "code": ["kod", "code", "script"],
            "visual_pack": ["görsel", "gorsel", "asset", "visual"],
            "research_brief": ["araştır", "arastir", "research", "analiz"],
            "summary": ["özet", "ozet", "summary"],
        }
        ds: list[str] = []
        for key, kws in deliverable_map.items():
            if any(kw in t for kw in kws):
                ds.append(key)
        constraints["deliverables"] = ds

        evidence_patterns = (
            r"\bkanıt\b",
            r"\bkanit\b",
            r"\bproof\b",
            r"\bmanifest\b",
            r"\bhash\b",
            r"\bsha256\b",
            r"\bss\b",
            r"\bscreenshot\b",
            r"ekran görüntüsü",
            r"ekran goruntusu",
            r"dosya paylaş",
            r"dosya paylas",
        )
        if any(re.search(pat, t, re.IGNORECASE) for pat in evidence_patterns):
            constraints["requires_evidence"] = True

        screenshot_patterns = (
            r"\bscreenshot\b",
            r"\bss\b",
            r"ekran görünt",
            r"ekran gorunt",
        )
        if any(re.search(pat, t, re.IGNORECASE) for pat in screenshot_patterns):
            constraints["proof_formats"].append("screenshot")
        if any(k in t for k in ("manifest", "hash", "sha256", "log")):
            constraints["proof_formats"].append("manifest")

        if any(k in t for k in ("tam otonom", "full autonomy", "full-autonomy", "onaysız", "onaysiz", "izin sorma")):
            constraints["autonomy_preference"] = "full"
        elif any(k in t for k in ("onay", "approval", "izin al", "izinli")):
            constraints["autonomy_preference"] = "guarded"
        return constraints

    def build(self, user_input: str) -> dict[str, Any]:
        text = self._normalize(user_input)
        parts = self._split_stages(text)
        if not parts:
            parts = [text] if text else []

        nodes: list[GoalNode] = []
        for i, part in enumerate(parts, start=1):
            route = self.router.route(part)
            nodes.append(
                GoalNode(
                    node_id=f"g{i}",
                    text=part,
                    domain=route.domain,
                    objective=route.objective,
                )
            )

        edges = []
        for i in range(len(nodes) - 1):
            edges.append({"from": nodes[i].node_id, "to": nodes[i + 1].node_id, "type": "sequential"})

        workflow_chain: list[str] = []
        for n in nodes:
            if n.domain == "general":
                continue
            if n.domain not in workflow_chain:
                workflow_chain.append(n.domain)

        # Complexity estimate for planner routing decisions.
        verb_like = len(re.findall(r"\b(yap|et|oluştur|olustur|incele|araştır|arastir|özetle|ozetle|write|build|debug)\w*\b", text.lower()))
        complexity_score = min(1.0, (len(nodes) * 0.22) + (verb_like * 0.06))

        primary_delivery = nodes[-1].domain if nodes else "general"
        if primary_delivery == "general" and workflow_chain:
            primary_delivery = workflow_chain[-1]
        constraints = self._extract_constraints(text)

        return {
            "nodes": [n.to_dict() for n in nodes],
            "edges": edges,
            "workflow_chain": workflow_chain,
            "primary_delivery_domain": primary_delivery,
            "stage_count": len(nodes),
            "complexity_score": round(complexity_score, 2),
            "constraints": constraints,
        }


_goal_graph_planner: GoalGraphPlanner | None = None


def get_goal_graph_planner() -> GoalGraphPlanner:
    global _goal_graph_planner
    if _goal_graph_planner is None:
        _goal_graph_planner = GoalGraphPlanner()
    return _goal_graph_planner
