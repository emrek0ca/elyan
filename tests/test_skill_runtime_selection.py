from __future__ import annotations

import copy

from runtime import state_store
from runtime.skill_runtime import rank_skills_for_text, record_skill_usage


def _skill(
    skill_id: str,
    *,
    name: str,
    description: str,
    category: str,
    adapter: str,
    libraries: list[str] | None = None,
    required: list[str] | None = None,
    expected_inputs: list[str] | None = None,
    requires_confirmation: bool = False,
    selection_priority: int = 50,
    available: bool = True,
) -> dict[str, object]:
    return {
        "id": skill_id,
        "name": name,
        "description": description,
        "category": category,
        "adapter": adapter,
        "libraries": libraries or [],
        "requiredParameters": required or [],
        "expectedInputs": expected_inputs or [],
        "requiresConfirmation": requires_confirmation,
        "selectionPriority": selection_priority,
        "available": available,
        "enabled": True,
    }


def test_rank_skills_for_text_prefers_matching_skill() -> None:
    skills = [
        _skill(
            "document.summary",
            name="Document Summary",
            description="Belgeyi kısa özet olarak çıkarır.",
            category="document",
            adapter="document_read",
            libraries=["pymupdf"],
            required=["path"],
            expected_inputs=["path"],
            selection_priority=88,
        ),
        _skill(
            "canvas.write",
            name="Canvas Write",
            description="Metin, tablo ve görselleri tek bir PDF veya PNG canvas çıktısında birleştirir.",
            category="document",
            adapter="canvas_write",
            libraries=["reportlab", "Pillow"],
            required=["outputPath"],
            expected_inputs=["prompt", "blocks", "sections"],
            selection_priority=90,
        ),
        _skill(
            "web.research",
            name="Web Research",
            description="Public web üzerinde kaynak toplayıp kısa bir araştırma özeti üretir.",
            category="research",
            adapter="web_research",
            libraries=["httpx"],
            required=["query"],
            expected_inputs=["query", "maxResults"],
            selection_priority=82,
        ),
        _skill(
            "math.solve",
            name="Math Solve",
            description="Denklem ve ifadeleri çözer, sadeleştirir.",
            category="math",
            adapter="math_solve",
            libraries=["sympy"],
            required=["expression"],
            expected_inputs=["expression"],
            selection_priority=92,
        ),
    ]

    ranked = rank_skills_for_text("pdf dosyasını özetle", skills=skills)

    assert ranked[0]["id"] == "document.summary"
    assert ranked[0]["score"] > ranked[1]["score"]


def test_rank_skills_for_text_prefers_canvas_skill_for_canvas_queries() -> None:
    skills = [
        _skill(
            "document.summary",
            name="Document Summary",
            description="Belgeyi kısa özet olarak çıkarır.",
            category="document",
            adapter="document_read",
            libraries=["pymupdf"],
            required=["path"],
            expected_inputs=["path"],
            selection_priority=88,
        ),
        _skill(
            "canvas.write",
            name="Canvas Write",
            description="Metin, tablo ve görselleri tek bir PDF veya PNG canvas çıktısında birleştirir.",
            category="document",
            adapter="canvas_write",
            libraries=["reportlab", "Pillow"],
            required=["outputPath"],
            expected_inputs=["prompt", "blocks", "sections"],
            selection_priority=94,
        ),
    ]

    ranked = rank_skills_for_text("canvas tablo ve görsel düzeni oluştur", skills=skills)

    assert ranked[0]["id"] == "canvas.write"


def test_rank_skills_for_text_prefers_summary_save_skill_for_save_requests() -> None:
    skills = [
        _skill(
            "document.summary",
            name="Document Summary",
            description="Belgeyi kısa özet olarak çıkarır.",
            category="document",
            adapter="document_read",
            libraries=["pymupdf"],
            required=["path"],
            expected_inputs=["path"],
            selection_priority=88,
        ),
        _skill(
            "document.summary_and_save",
            name="Document Summary and Save",
            description="Belgeyi veya paylaşılan metni özetler ve masaüstüne DOCX olarak kaydeder.",
            category="document",
            adapter="document_write",
            libraries=["pymupdf", "python-docx"],
            required=["outputPath"],
            expected_inputs=["path", "text", "selectedPaths", "outputPath"],
            requires_confirmation=True,
            selection_priority=96,
        ),
    ]

    ranked = rank_skills_for_text("bu pdf'i özetleyip masaüstüne kaydet", skills=skills)

    assert ranked[0]["id"] == "document.summary_and_save"
    assert ranked[0]["score"] > ranked[1]["score"]


def test_rank_new_compound_skills_win_their_trigger_phrases() -> None:
    from runtime.skill_runtime import _builtin_skill_manifests

    skills = _builtin_skill_manifests()

    cases = {
        "bu konuyu araştır ve sunum yap": "research.present",
        "veriyi analiz et ve grafiğini çiz": "data.analyze_and_chart",
        "ekranda ne var açıkla": "screen.explain",
        "bu görseli açıkla": "image.describe",
    }
    for query, expected_id in cases.items():
        ranked = rank_skills_for_text(query, skills=skills)
        assert ranked, f"{query!r} için hiç skill sıralanmadı"
        assert ranked[0]["id"] == expected_id, (
            f"{query!r} -> {ranked[0]['id']} (beklenen {expected_id})"
        )


def test_record_skill_usage_updates_recent_runs_and_stats(monkeypatch) -> None:
    base_state = {
        "skills": {
            "activeSkills": [],
            "mcpServers": [],
            "toolPermissions": {},
            "defaultSkill": "",
            "toolSafety": "balanced",
            "usage": {
                "recentRuns": [],
                "skillStats": {},
                "lastSuccessfulSkillId": "",
                "lastSuccessfulAt": "",
                "lastFailedSkillId": "",
                "lastFailedAt": "",
            },
        }
    }
    captured: dict[str, object] = {}

    monkeypatch.setattr(state_store, "snapshot", lambda: copy.deepcopy(base_state))
    monkeypatch.setattr(state_store, "save_state", lambda payload: captured.setdefault("payload", copy.deepcopy(payload)))

    record_skill_usage("document.summary", success=True, source="skill_runtime", duration_ms=123)

    payload = captured["payload"]
    assert isinstance(payload, dict)
    usage = payload["skills"]["usage"]
    assert usage["recentRuns"][0]["skillId"] == "document.summary"
    assert usage["skillStats"]["document.summary"]["successCount"] == 1
    assert usage["skillStats"]["document.summary"]["lastDurationMs"] == 123
    assert usage["lastSuccessfulSkillId"] == "document.summary"
