from core.goal_graph import get_goal_graph_planner


def test_goal_graph_extracts_evidence_and_autonomy_constraints():
    planner = get_goal_graph_planner()
    graph = planner.build("Bu görevi tam otonom yap, manifest ve hash kanıtı gönder, ekran görüntüsü de ekle.")

    constraints = graph.get("constraints", {})
    assert constraints.get("requires_evidence") is True
    assert constraints.get("autonomy_preference") == "full"
    formats = constraints.get("proof_formats", [])
    assert "manifest" in formats
    assert "screenshot" in formats


def test_goal_graph_stage_and_complexity_for_multistep_prompt():
    planner = get_goal_graph_planner()
    graph = planner.build("ERP'den satışları çek ve raporla sonra PDF üret ardından yönetime mail at.")

    assert int(graph.get("stage_count", 0)) >= 3
    assert float(graph.get("complexity_score", 0.0)) >= 0.45


def test_goal_graph_ssh_phrase_does_not_trigger_evidence_mode():
    planner = get_goal_graph_planner()
    graph = planner.build("terminalden ssh root komutunu çalıştır")

    constraints = graph.get("constraints", {})
    assert constraints.get("requires_evidence") is False
    formats = constraints.get("proof_formats", [])
    assert "screenshot" not in formats
