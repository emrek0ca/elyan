
import pytest
from core.multi_agent.specialists import get_specialist_registry
from core.multi_agent.orchestrator import AgentOrchestrator

def test_specialist_selection():
    registry = get_specialist_registry()

    # Kod yazma uzmanı seçilmeli (builder/building domain)
    s1 = registry.select_for_input("Python ile bir script yazıp debug eder misin?")
    assert s1.domain == "building"
    assert "Geliştirici" in s1.role or "Yazılımcı" in s1.name
    
    # Araştırma uzmanı seçilmeli
    s2 = registry.select_for_input("Küresel ısınma hakkında derin bir araştırma yap")
    assert s2.domain == "research"
    assert "Araştırma" in s2.name or "araştırma" in s2.role.lower()

    # Sistem/operasyon uzmanı seçilmeli
    s3 = registry.select_for_input("Terminalde çalışan prosesleri listele")
    assert s3.domain in ("system", "operations")
    assert "Operasyon" in s3.name or "Sistem" in s3.role or "Uzmanı" in s3.role

def test_registry_get():
    registry = get_specialist_registry()
    coder = registry.get("coder")
    assert coder is not None
    assert coder.domain == "building"

    none_agent = registry.get("non_existent")
    assert none_agent is None


def test_orchestrator_compact_plan_hint_handles_structured_steps():
    orch = AgentOrchestrator(object())
    hint = orch._compact_plan_hint(
        [
            {"title": "Scaffold", "action": "create_web_project_scaffold", "depends_on": []},
            {"title": "Write HTML", "action": "write_file", "depends_on": ["subtask_1"]},
        ]
    )
    assert "Scaffold" in hint
    assert "write_file" in hint
    assert "subtask_1" in hint


def test_orchestrator_builds_deterministic_fallback_payload():
    orch = AgentOrchestrator(object())
    payload = orch._build_fallback_execution_payload(
        template_id="web_site_job",
        original_input="Kediler icin site",
        workspace_dir="~/Desktop/test-job",
        plan_hint="1. scaffold",
    )
    assert "artifact_map" in payload
    assert "execution_plan" in payload
    assert payload["artifact_map"]["artifacts"]
    assert payload["execution_plan"][0]["action"] == "create_folder"
