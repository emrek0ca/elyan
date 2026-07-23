"""Bileşik komut rotası + adımlar arası veri zinciri regresyon testleri.

"X'i araştır ve belgele" gibi tek mesajlık çok araçlı görevlerin: (1) doğru
sıralı plana bölünmesini, (2) yazıcı araçların önceki adımın çıktısını içerik
olarak devralmasını garanti eder.
"""
from __future__ import annotations

from runtime.capability_registry import _writer_source_context
from runtime.task_router import route_text_to_tool


def _step_capabilities(text: str) -> list[str]:
    routed = route_text_to_tool(text)
    assert routed is not None, f"{text!r} rotalanamadı"
    if routed.steps:
        return [str(step.get("capability", "")) for step in routed.steps]
    return [routed.tool_name]


def test_research_then_document_chain() -> None:
    assert _step_capabilities(
        "kuantum bilgisayarlarını araştır ve rapor olarak belgele"
    ) == ["web_research", "document_write"]


def test_research_writer_with_and_inside_topic_stays_compound() -> None:
    routed = route_text_to_tool(
        "Kira uyuşmazlığını ve tahliye davasını araştır ve savunma dilekçesi taslağı hazırla"
    )

    assert routed is not None
    assert routed.intent == "compound_task"
    assert [str(step.get("capability", "")) for step in routed.steps] == [
        "web_research",
        "document_write",
    ]
    assert routed.steps[0]["args"]["query"] == "Kira uyuşmazlığını ve tahliye davasını"


def test_research_analysis_then_report_stays_compound() -> None:
    routed = route_text_to_tool("Mühendislik projesini araştır analiz et ve rapor hazırla")

    assert routed is not None
    assert routed.intent == "compound_task"
    assert [str(step.get("capability", "")) for step in routed.steps] == [
        "web_research",
        "document_write",
    ]
    assert routed.steps[0]["args"]["query"] == "Mühendislik projesini"


def test_accounting_calculation_research_report_chain() -> None:
    routed = route_text_to_tool(
        "Muhasebeci gibi çalış. 12000 TL ve 8500 TL hizmet faturası için yüzde 20 KDV hesapla, "
        "KDV kurallarını araştır ve sonuçları bir rapor belgesi olarak hazırla."
    )

    assert routed is not None
    assert routed.intent == "compound_task"
    assert [str(step.get("capability", "")) for step in routed.steps] == [
        "math_solve",
        "web_research",
        "document_write",
    ]
    assert routed.steps[0]["args"]["expression"] == "(12000+8500)*0.2"
    assert routed.steps[1]["args"]["query"] == "KDV kurallarını"
    assert routed.steps[1]["dependsOn"] == ["calculate"]
    assert routed.steps[2]["dependsOn"] == ["calculate", "research"]


def test_percentage_calculation_ignores_non_currency_numbers() -> None:
    routed = route_text_to_tool(
        "Muhasebeci gibi çalış. 12000 TL ve 8500 TL hizmet faturası için yüzde 20 KDV hesapla, "
        "KDV kurallarını araştır ve rapor hazırla. Test no 1784785091."
    )

    assert routed is not None
    assert routed.steps[0]["args"]["expression"] == "(12000+8500)*0.2"


def test_student_research_then_presentation_query_is_clean() -> None:
    routed = route_text_to_tool(
        "Öğrenci gibi çalış. Kuantum annealing ile klasik optimizasyon farkını araştır, "
        "adım adım açıkla ve 5 sayfalık sunum hazırla."
    )

    assert routed is not None
    assert routed.intent == "compound_task"
    assert [str(step.get("capability", "")) for step in routed.steps] == [
        "web_research",
        "presentation_write",
    ]
    assert routed.steps[0]["args"]["query"] == "Kuantum annealing ile klasik optimizasyon farkını"
    assert routed.steps[1]["dependsOn"] == ["step_1"]


def test_research_sonra_document_chain() -> None:
    assert _step_capabilities(
        "bitcoin fiyatını araştır sonra bir word belgesi hazırla"
    ) == ["web_research", "document_write"]


def test_open_app_then_site_chain() -> None:
    assert _step_capabilities("safari'yi aç ve youtube'a gir") == [
        "open_app",
        "browser_control",
    ]


def test_compound_requires_confirmation_and_multi_step() -> None:
    routed = route_text_to_tool("kuantum bilgisayarlarını araştır ve rapor olarak belgele")
    assert routed is not None
    assert routed.is_multi_step is True
    assert routed.requires_confirmation is True
    assert routed.plan_preview is not None


def test_duplicate_read_only_data_intents_collapse_to_one_profile() -> None:
    routed = route_text_to_tool(
        "bu Excel dosyasını analiz et ve özet istatistikleri çıkar",
        selected_artifacts=[
            {
                "id": "budget",
                "name": "butce.xlsx",
                "path": "/tmp/butce.xlsx",
                "kind": "document",
            }
        ],
    )

    assert routed is not None
    assert routed.intent == "data_analyze"
    assert routed.args["mode"] == "profile"
    assert routed.requires_confirmation is False


def test_read_only_compound_math_does_not_require_confirmation() -> None:
    routed = route_text_to_tool("2+2 hesapla ve 3*3 hesapla")

    assert routed is not None
    assert routed.intent == "compound_task"
    assert routed.requires_confirmation is False


def test_duplicate_document_read_intents_collapse_to_summary() -> None:
    routed = route_text_to_tool(
        "bu PDF dosyasını oku ve özetle",
        selected_artifacts=[
            {
                "id": "report",
                "name": "report.pdf",
                "path": "/tmp/report.pdf",
                "kind": "document",
            }
        ],
    )

    assert routed is not None
    assert routed.intent == "document_read"
    assert routed.args["mode"] == "summary"
    assert routed.requires_confirmation is False


def test_ve_inside_single_topic_not_split() -> None:
    # "tuz ve biber araştır" tek araştırma görevi kalmalı.
    routed = route_text_to_tool("tuz ve biber araştır")
    assert routed is not None
    assert routed.tool_name == "web_research"
    assert routed.intent != "compound_task"


def test_time_expression_sonra_not_split() -> None:
    routed = route_text_to_tool("5 dakika sonra hatırlatıcı ekle")
    assert routed is not None
    assert routed.tool_name == "add_reminder"


# ── Devam segmentleri: zamirle kurulan ikinci eylemler ────────────────────────


def test_pronoun_continuation_document() -> None:
    assert _step_capabilities(
        "yapay zeka ajanlarını araştır ve bunu belgele"
    ) == ["web_research", "document_write"]


def test_continuation_report_verb() -> None:
    assert _step_capabilities(
        "elyan projesini araştır ve bulduklarını rapor et"
    ) == ["web_research", "document_write"]


def test_continuation_word_save() -> None:
    assert _step_capabilities(
        "türkiye ekonomisini araştır ve bir word belgesi olarak kaydet"
    ) == ["web_research", "document_write"]


def test_continuation_spreadsheet() -> None:
    assert _step_capabilities(
        "dolar kurunu araştır ve tabloya dök"
    ) == ["web_research", "spreadsheet_write"]


def test_continuation_presentation() -> None:
    assert _step_capabilities(
        "iklim değişikliğini araştır ve sonuçları sunuma çevir"
    ) == ["web_research", "presentation_write"]


def test_continuation_self_mail() -> None:
    routed = route_text_to_tool("bitcoin fiyatını araştır ve sonucu bana mail at")
    assert routed is not None
    caps = [str(step.get("capability", "")) for step in routed.steps]
    assert caps == ["web_research", "email_draft", "email_send"]
    assert routed.privacy_class == "side_effect"
    assert routed.requires_confirmation is True
    # "bana" alıcısı yürütmede hesap e-postasına çözülecek "me" yer tutucusudur.
    draft_args = routed.steps[1].get("args", {})
    assert draft_args.get("to") == ["me"]


def test_continuation_explicit_mail_recipient() -> None:
    routed = route_text_to_tool(
        "kuantum bilgisayarları araştır ve sonucu ali@ornek.com adresine gönder"
    )
    assert routed is not None
    caps = [str(step.get("capability", "")) for step in routed.steps]
    assert caps == ["web_research", "email_draft", "email_send"]


def test_continuation_not_applied_to_first_segment() -> None:
    # İlk segment zamir tabanlı tüketiciyse ("sonucu ... mail at") önce gelen
    # bir çıktı olmadığı için devam çözümü uygulanmamalı; bölme iptal edilip
    # metin tek görev olarak işlenmeli.
    routed = route_text_to_tool("sonucu bana mail at ve yapay zekayı araştır")
    assert routed is not None
    assert routed.intent != "compound_task"


# ── "me" alıcı yer tutucusunun çözümü ─────────────────────────────────────────


def test_email_me_placeholder_resolves_to_account_email(monkeypatch) -> None:
    import actions.email as email_mod

    monkeypatch.setattr(email_mod, "_account_email", lambda: "kisi@ornek.com")
    assert email_mod._resolve_recipients(["me"]) == ["kisi@ornek.com"]
    assert email_mod._resolve_recipients(["bana", "dis@ornek.com"]) == [
        "kisi@ornek.com",
        "dis@ornek.com",
    ]


def test_email_me_placeholder_errors_without_account_email(monkeypatch) -> None:
    import pytest

    import actions.email as email_mod
    from runtime.capability_registry import SafeCapabilityError

    monkeypatch.setattr(email_mod, "_account_email", lambda: "")
    with pytest.raises(SafeCapabilityError):
        email_mod._resolve_recipients(["me"])


# ── Yazıcı araçların zincir bağlamı ────────────────────────────────────────────


def test_writer_context_prefers_explicit_source_context() -> None:
    args = {"sourceContext": "açık içerik", "_previousOutput": "önceki çıktı"}
    assert _writer_source_context(args) == "açık içerik"


def test_writer_context_falls_back_to_previous_result() -> None:
    args = {
        "_previousResult": {
            "kind": "web_research",
            "summary": "Kuantum bilgisayarlar hızla gelişiyor.",
            "sources": [
                {"title": "Nature", "snippet": "Yeni kubit rekoru."},
                {"url": "https://example.com", "snippet": "Endüstri raporu."},
            ],
        },
        "_previousOutput": "ham çıktı",
    }
    context = _writer_source_context(args)
    assert "Kuantum bilgisayarlar hızla gelişiyor." in context
    assert "Nature" in context
    assert "Kaynaklar:" in context


def test_writer_context_uses_requested_document_read_shape() -> None:
    context = _writer_source_context(
        {
            "_dependencyResults": {
                "read": {
                    "kind": "document_read",
                    "mode": "summary",
                    "summary": "Kısa belge özeti.",
                    "text": "Yazıcıya taşınmaması gereken uzun tam metin.",
                }
            }
        }
    )

    assert context == "Kısa belge özeti."


def test_writer_context_falls_back_to_previous_output() -> None:
    args = {"_previousOutput": "önceki adımın metni"}
    assert _writer_source_context(args) == "önceki adımın metni"


def test_writer_context_empty_when_nothing_available() -> None:
    assert _writer_source_context({}) == ""
