"""goals.py — inspect complex goals and expose automation candidates."""

from __future__ import annotations

import json
from typing import Any

from core.goal_graph import get_goal_graph_planner


def _emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _joined_text(args) -> str:
    parts = list(getattr(args, "text", []) or [])
    return " ".join(str(part or "").strip() for part in parts if str(part or "").strip()).strip()


def run(args):
    action = str(getattr(args, "action", "analyze") or "analyze").strip().lower()
    as_json = bool(getattr(args, "json", False))
    text = _joined_text(args)
    if not text:
        message = "Metin gerekli. Örnek: elyan goals analyze ERP'den satışları çek sonra PDF üret ve mail at"
        if as_json:
            _emit_json({"ok": False, "error": message})
            return
        print(message)
        return

    if action != "analyze":
        message = f"Bilinmeyen goals aksiyonu: {action}"
        if as_json:
            _emit_json({"ok": False, "error": message})
            return
        print(message)
        return

    graph = get_goal_graph_planner().build(text)
    payload = {"ok": True, "input": text, "goal_graph": graph}
    if as_json:
        _emit_json(payload)
        return

    constraints = graph.get("constraints", {}) if isinstance(graph.get("constraints"), dict) else {}
    automation = graph.get("automation_candidate") if isinstance(graph.get("automation_candidate"), dict) else None

    print("Goal Analysis")
    print("─" * 72)
    print(f"Ana domain:   {graph.get('primary_delivery_domain', 'general')}")
    print(f"Aşama sayısı: {graph.get('stage_count', 0)}")
    print(f"Karmaşıklık:  {graph.get('complexity_score', 0.0)}")
    chain = graph.get("workflow_chain", []) if isinstance(graph.get("workflow_chain"), list) else []
    print(f"Zincir:       {', '.join(chain) if chain else '-'}")
    if automation:
        print(f"Otomasyon:    {automation.get('cron') or '-'}")
        print(f"Otomasyon işi:{automation.get('task') or '-'}")
    else:
        print("Otomasyon:    yok")
    if constraints.get("requires_evidence"):
        formats = constraints.get("proof_formats", []) if isinstance(constraints.get("proof_formats"), list) else []
        print(f"Kanıt:        gerekli ({', '.join(formats) if formats else 'format belirtilmedi'})")
    if constraints.get("autonomy_preference"):
        print(f"Otonomi:      {constraints.get('autonomy_preference')}")
    if constraints.get("preferred_output"):
        print(f"Çıktı:        {constraints.get('preferred_output')}")

    nodes = graph.get("nodes", []) if isinstance(graph.get("nodes"), list) else []
    if nodes:
        print("")
        print("Aşamalar")
        print("─" * 72)
        for idx, node in enumerate(nodes, start=1):
            if not isinstance(node, dict):
                continue
            print(f"{idx}. [{node.get('domain', 'general')}] {node.get('text', '')}")
            print(f"   objective: {node.get('objective', '')}")
