from __future__ import annotations

import runtime.bridge as bridge


def test_flag_reads_env(monkeypatch) -> None:
    monkeypatch.delenv("ELYAN_DETERMINISTIC_ONLY", raising=False)
    assert bridge._deterministic_only_enabled() is False
    monkeypatch.setenv("ELYAN_DETERMINISTIC_ONLY", "1")
    assert bridge._deterministic_only_enabled() is True
    monkeypatch.setenv("ELYAN_DETERMINISTIC_ONLY", "true")
    assert bridge._deterministic_only_enabled() is True
    monkeypatch.setenv("ELYAN_DETERMINISTIC_ONLY", "0")
    assert bridge._deterministic_only_enabled() is False


def test_fallback_reply_shape() -> None:
    reply = bridge._deterministic_fallback_reply("bilinmeyen komut")
    assert reply["ok"] is True
    assert reply["executionMode"] == "deterministic_fallback"
    assert reply["provider"] == "local_deterministic"
    assert reply["needsConfirmation"] is False
    assert "yapabilirim" in reply["content"].lower()


def test_route_chat_unmatched_stays_local_in_deterministic_mode(monkeypatch) -> None:
    # Deterministik mod AÇIK: eşleşmeyen komut backend/LLM'e GİTMEZ.
    monkeypatch.setenv("ELYAN_DETERMINISTIC_ONLY", "1")

    def _boom(*args, **kwargs):  # backend beynine gidilirse test patlar
        raise AssertionError("deterministik modda semantic/backend çağrılmamalı")

    monkeypatch.setattr(bridge, "_semantic_route", _boom)
    result = bridge._route_chat({}, [], "bana bir fıkra anlat", conversation_id="")
    assert result["executionMode"] == "deterministic_fallback"
    assert result["ok"] is True


def test_route_chat_matched_command_still_executes_in_deterministic_mode(monkeypatch) -> None:
    monkeypatch.setenv("ELYAN_DETERMINISTIC_ONLY", "1")
    result = bridge._route_chat({}, [], "git durumu", conversation_id="")
    # Eşleşen komut yürütülür (local_tool) — fallback'e düşmez.
    assert result.get("executionMode") == "local_tool"
