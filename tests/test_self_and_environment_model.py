"""Öz-model + dünya modeli sözleşmesi.

Değişmezler:
  1. Öz-kart KODDAN türer (elle yazılmış liste yok) ve kapalı izinleri AÇIKÇA
     bildirir — model "yapabilirim" deyip izin duvarına çarpmaz.
  2. Ortam gerçekleri TTL'li cache'ten gelir; bayat/eksik cache yeniden keşfe
     düşer, keşif çökerse asgari bilgiyle döner (uydurma yok).
"""

from __future__ import annotations

import datetime as dt

from runtime import environment_model
from runtime.self_model import build_self_card, self_card_is_informative


def test_self_card_derives_capabilities_from_registry() -> None:
    card = build_self_card({})
    assert card["capabilityCount"] > 0
    assert isinstance(card["capabilityGroups"], list) and card["capabilityGroups"]
    assert self_card_is_informative(card)


def test_self_card_reports_denied_permissions_explicitly() -> None:
    card = build_self_card(
        {"permissions": {"allow_shell": False, "allow_screen_analysis": True}}
    )
    assert "terminal" in card["permissionsDenied"]
    assert "ekran okuma" in card["permissionsGranted"]


def test_self_card_omits_unknown_permission_keys() -> None:
    card = build_self_card({"permissions": {}})
    assert "permissionsGranted" not in card
    assert "permissionsDenied" not in card


def test_environment_discovery_reports_this_machine() -> None:
    facts = environment_model.discover_environment()
    assert facts["platform"] in {"darwin", "linux", "windows"}
    assert facts["shell"]
    assert facts["discoveredAt"]


def test_fresh_cache_is_reused_without_rediscovery() -> None:
    cached = {
        "contract": environment_model.ENVIRONMENT_CONTRACT,
        "platform": "linux",
        "shell": "bash",
        "discoveredAt": dt.datetime.now().isoformat(timespec="seconds"),
    }
    facts = environment_model.environment_facts(
        {"runtime": {"environment": cached}}, persist=False
    )
    assert facts is cached


def test_stale_cache_triggers_rediscovery() -> None:
    stale = {
        "contract": environment_model.ENVIRONMENT_CONTRACT,
        "platform": "linux",
        "discoveredAt": (
            dt.datetime.now()
            - dt.timedelta(minutes=environment_model.ENVIRONMENT_TTL_MINUTES + 60)
        ).isoformat(timespec="seconds"),
    }
    facts = environment_model.environment_facts(
        {"runtime": {"environment": stale}}, persist=False
    )
    assert facts is not stale
    assert facts["discoveredAt"] != stale["discoveredAt"]


def test_prompt_context_drops_timestamps_and_bounds_tools() -> None:
    payload = environment_model.to_prompt_context(
        {
            "platform": "darwin",
            "shell": "zsh",
            "packageManager": "brew",
            "discoveredAt": "2026-07-25T00:00:00",
            "tools": [f"tool{i}" for i in range(30)],
        }
    )
    assert "discoveredAt" not in payload
    assert len(payload["availableTools"]) == 12
    assert payload["packageManager"] == "brew"


def test_understanding_receives_self_and_environment_context() -> None:
    from runtime import intent_gate

    captured: dict = {}

    def send_prompt(prompt: str) -> str:
        captured["prompt"] = prompt
        return '{"intent":"chat","confidence":0.9}'

    intent_gate.understand("selam", send_prompt=send_prompt, state={"permissions": {"allow_shell": False}})
    assert "selfModel" in captured["prompt"]
    assert "environment" in captured["prompt"]
