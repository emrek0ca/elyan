import pytest

from core.ux_engine import get_ux_engine


@pytest.mark.asyncio
async def test_group_idle_does_not_respond():
    engine = get_ux_engine()
    plan = engine.should_respond(
        user_message="merhaba millet",
        session_id="tg:group:1",
        channel_type="telegram",
        metadata={"is_group": True, "mentioned": False, "bot_username": "elyanbot"},
        attachments=[],
        user_id="u1",
    )
    assert plan.should_respond is False


@pytest.mark.asyncio
async def test_inline_reply_is_allowed_and_naturalized():
    engine = get_ux_engine()
    result = await engine.postprocess_response(
        raw_response="✨ Premium UX Response\n\nMerhaba. Size nasıl yardımcı olabilirim? Bu işi hallettim.",
        user_message="buna bakar mısın",
        session_id="tg:reply:1",
        user_id="u1",
        channel_type="telegram",
        metadata={"is_group": True, "is_inline_reply": True, "mentioned": False},
    )
    assert result.should_respond is True
    assert "Premium UX Response" not in result.response
    assert "nasıl yardımcı olabilirim" not in result.response.lower()


@pytest.mark.asyncio
async def test_maximum_privacy_disables_learning(monkeypatch):
    engine = get_ux_engine()
    monkeypatch.setattr(engine._settings, "get", lambda key, default=None: "maximum" if key == "conversation_privacy_mode" else default)
    calls = []

    def _record(*args, **kwargs):
        calls.append((args, kwargs))
        return {}

    monkeypatch.setattr(engine._profiles, "update_conversation_profile", _record)
    result = await engine.postprocess_response(
        raw_response="Tamam. Yarın saat 10 için takvimine göre uygunsun.",
        user_message="yarın boş muyum",
        session_id="desktop:privacy",
        user_id="local",
        channel_type="desktop",
        metadata={"channel_type": "desktop"},
    )
    assert result.trust_summary.startswith("Maximum Privacy")
    assert calls == []


@pytest.mark.asyncio
async def test_attachment_gets_short_ack():
    engine = get_ux_engine()
    result = await engine.postprocess_response(
        raw_response="Dosyayı taradım ve sorun görünmüyor.",
        user_message="buna bak",
        session_id="desktop:file",
        user_id="local",
        channel_type="desktop",
        metadata={"channel_type": "desktop"},
        attachments=["/tmp/demo.png"],
    )
    assert result.response.startswith("Aldım, bakıyorum.")


@pytest.mark.asyncio
async def test_verified_turn_exposes_provider_lane_and_source_suggestion():
    engine = get_ux_engine()
    result = await engine.postprocess_response(
        raw_response="Repo özeti hazır.",
        user_message="bu repo'yu araştır ve kaynaklarla doğrula",
        session_id="desktop:verified",
        user_id="local",
        channel_type="desktop",
        metadata={"channel_type": "desktop"},
    )

    assert result.context_used["provider_lane"] in {"verified_cloud", "local_verified"}
    assert "Kaynakla doğrula" in result.suggestions


@pytest.mark.asyncio
async def test_solver_turn_gets_more_operator_like_response():
    engine = get_ux_engine()
    result = await engine.postprocess_response(
        raw_response="Sorunu inceliyorum.",
        user_message="bunu çöz ve düzgün hale getir",
        session_id="desktop:solver",
        user_id="local",
        channel_type="desktop",
        metadata={"channel_type": "desktop"},
    )
    assert result.operator_mode == "solver"
    assert "çözelim" in result.response.lower() or "üstüne gidiyorum" in result.response.lower()
    assert "Alternatif yol dene" in result.suggested_replies


@pytest.mark.asyncio
async def test_blocked_turn_offers_alternative_method():
    engine = get_ux_engine()
    result = await engine.postprocess_response(
        raw_response="Bu yoldan olmadı.",
        user_message="çalışmıyor, başka türlü çöz",
        session_id="desktop:blocked",
        user_id="local",
        channel_type="desktop",
        metadata={"channel_type": "desktop"},
    )
    assert result.operator_mode == "blocked_recovery"
    assert "alternatif" in result.response.lower() or "ikinci bir yöntem" in result.response.lower()


@pytest.mark.asyncio
async def test_presence_turn_feels_more_alive():
    engine = get_ux_engine()
    result = await engine.postprocess_response(
        raw_response="Hazırım.",
        user_message="burada mısın",
        session_id="desktop:presence",
        user_id="local",
        channel_type="desktop",
        metadata={"channel_type": "desktop"},
    )
    assert result.operator_mode == "presence"
    assert "buradayım" in result.response.lower()
