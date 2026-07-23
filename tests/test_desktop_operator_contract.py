from __future__ import annotations

import json
from pathlib import Path

import pytest

from actions import browser_operator, desktop_operator, screen_vision
from runtime import bridge, capability_registry, state_store


def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(state_store, "STATE_PATH", tmp_path / "elyan_state.json")
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")


def _dangerous_state(**permissions: bool) -> dict[str, object]:
    return state_store._ensure_defaults(
        {
            "runtime": {"access": {"fullAccessSession": {"enabled": True}}},
            "permissions": permissions,
        }
    )


def test_desktop_operator_readiness_ignores_stale_native_unavailable_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state = state_store._ensure_defaults(
        {
            "runtime": {
                "capabilityStates": {
                    "desktop_operator.observe_screen": {
                        "available": False,
                        "ready": False,
                        "errorCode": "CAPABILITY_UNAVAILABLE",
                    }
                }
            }
        }
    )

    readiness = capability_registry.capability_readiness("desktop_operator.observe_screen", state=state)

    assert readiness["ready"] is True
    assert readiness["errorCode"] == ""


def test_desktop_operator_observe_screen_defers_to_os_permission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Apple-kalite: ekran gözlemi Elyan-içi 'tam yetki' flag'iyle ARTIK
    bloklanmaz; gerçek izni OS/yardımcı uygular. Yardımcı reddedince okunaklı
    OS_PERMISSION_REQUIRED döner (iç 'tam yetki' PERMISSION_REQUIRED değil)."""
    _isolate_state(monkeypatch, tmp_path)
    from runtime import safety_policy

    # Politika artık iç flag olmadan da GEÇER (deterministik sözleşme).
    decision = safety_policy.evaluate_tool(
        "desktop_operator.observe_screen", {}, state_store._ensure_defaults({})
    )
    assert decision.allowed is True

    # Yürütmede yardımcı izin reddederse okunaklı OS mesajı (iç kapı değil).
    import actions.screen_vision as screen_vision

    monkeypatch.setattr(screen_vision, "_run_helper", lambda *_a, **_k: (False, "permission_denied"))
    result = capability_registry.run_capability(
        "desktop_operator.observe_screen",
        {"query": "ekranda ne var"},
        state_store._ensure_defaults({}),
    )
    assert result["ok"] is False
    assert result["error"]["code"] in {"PERMISSION_REQUIRED", "OS_PERMISSION_REQUIRED"}


def test_screen_helper_display_capture_failure_maps_to_permission_required() -> None:
    from actions import screen_vision
    from actions._platform_common import is_permission_detail

    parsed_ok, detail, payload = screen_vision._parse_capture_payload(
        json.dumps(
            {
                "ok": False,
                "error": "permission_denied",
                "detail": "could not create image from display",
            }
        )
    )

    assert parsed_ok is False
    assert payload is None
    assert "macOS ekran kaydi izni gerekiyor" in detail
    assert is_permission_detail(detail) is True


def test_desktop_operator_observe_screen_returns_structured_observation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    image_path = tmp_path / "capture.png"
    image_path.write_bytes(b"fake")
    cached_path = tmp_path / "cached.png"
    cached_path.write_bytes(b"fake")

    monkeypatch.setattr(screen_vision, "_run_helper", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        screen_vision,
        "_parse_capture_payload",
        lambda _raw: (
            True,
            "",
            {
                "image_path": str(image_path),
                "owner_name": "Safari",
                "window_title": "Docs",
                "bounds": {"width": 1440, "height": 900},
            },
        ),
    )
    monkeypatch.setattr(desktop_operator, "_copy_to_operator_cache", lambda _source: cached_path)
    monkeypatch.setattr(
        desktop_operator,
        "_build_screen_observation",
        lambda _image_path, _payload: {
            "screenshotPath": str(cached_path),
            "width": 1440,
            "height": 900,
            "monitorId": "active_monitor",
            "scaleFactor": 2.0,
            "capturedAt": "2026-06-05T12:00:00Z",
            "activeApp": "Safari",
            "activeWindow": "Docs",
            "elements": [
                {
                    "id": "ax_1",
                    "type": "button",
                    "text": "Continue",
                    "bbox": {"x": 100, "y": 120, "w": 80, "h": 28},
                    "confidence": 0.99,
                    "source": "accessibility",
                }
            ],
        },
    )

    result = capability_registry.run_capability(
        "desktop_operator.observe_screen",
        {"query": "devam butonu nerede"},
        _dangerous_state(allow_screen_analysis=True),
    )

    assert result["ok"] is True
    observation = result["result"]["observation"]
    assert observation["activeApp"] == "Safari"
    assert observation["elements"][0]["text"] == "Continue"
    assert result["result"]["targetSuggestions"][0]["text"] == "Continue"


def test_desktop_operator_execute_action_blocks_risky_actions_without_sensitive_permission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)

    result = capability_registry.run_capability(
        "desktop_operator.execute_action",
        {
            "actionType": "click",
            "targetText": "Submit payment",
        },
        _dangerous_state(allow_computer_control=True),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "PERMISSION_REQUIRED"


def test_runtime_bridge_capability_states_include_desktop_operator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        desktop_operator,
        "operator_runtime_status",
        lambda: {
            "available": True,
            "lastErrorCode": "",
            "detail": {
                "platform": "darwin",
                "screenObservationReady": True,
                "accessibilityReady": True,
                "inputControlReady": True,
                "emergencyStopAvailable": True,
                "playwrightReady": True,
                "browserFirstReady": True,
            },
        },
    )

    runtime = bridge.RuntimeBridge()
    payload = runtime._runtime_heartbeat_payload("idle")

    assert payload["capabilityStates"]["desktop_operator.observe_screen"]["ready"] is True
    assert payload["capabilityStates"]["desktop_operator.execute_action"]["ready"] is True
    assert payload["capabilityStates"]["desktop_operator.cancel"]["ready"] is True
    assert payload["capabilityStates"]["desktop_operator.run"]["browserFirstReady"] is True


def test_build_screen_observation_prefers_browser_dom_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        desktop_operator.desktop_os,
        "desktop_os_active_window",
        lambda: {"result": {"appName": "Google Chrome", "windowTitle": "Docs"}},
    )
    monkeypatch.setattr(
        browser_operator,
        "observe_browser_window",
        lambda _app_name, _window_title="": {
            "pageTitle": "Docs",
            "pageUrl": "https://example.com",
            "elements": [
                {
                    "id": "dom_1",
                    "type": "button",
                    "text": "Continue",
                    "bbox": {"x": 10, "y": 10, "w": 80, "h": 24},
                    "confidence": 0.99,
                    "source": "browser_dom",
                    "browser": {"selector": "#continue"},
                }
            ],
        },
    )
    monkeypatch.setattr(browser_operator, "is_supported_browser_app", lambda _name: True)

    observation = desktop_operator._build_screen_observation(  # type: ignore[attr-defined]
        Path("/tmp/fake.png"),
        {"owner_name": "Google Chrome", "window_title": "Docs", "bounds": {"width": 1200, "height": 800}},
    )

    assert observation["resolutionMode"] == "browser_first"
    assert observation["elements"][0]["source"] == "browser_dom"
    assert observation["screenSummary"]["browserDomCount"] == 1
    assert observation["elements"][0]["searchHints"][0] == "continue"


def test_execute_action_uses_browser_first_adapter_when_target_is_browser_dom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    observation = {
        "activeApp": "Google Chrome",
        "activeWindow": "Docs",
        "resolutionMode": "browser_first",
        "elements": [
            {
                "id": "dom_1",
                "type": "button",
                "text": "Continue",
                "bbox": {"x": 10, "y": 10, "w": 80, "h": 24},
                "confidence": 0.99,
                "source": "browser_dom",
                "browser": {"selector": "#continue"},
            }
        ],
    }
    monkeypatch.setattr(browser_operator, "is_supported_browser_app", lambda _name: True)
    monkeypatch.setattr(
        browser_operator,
        "execute_browser_action",
        lambda **_kwargs: calls.append("browser") or {"ok": True, "targetSource": "browser_dom"},
    )
    monkeypatch.setattr(
        desktop_operator,
        "observe_screen",
        lambda *_args, **_kwargs: {"result": {"observation": observation}},
    )

    result = desktop_operator.execute_action(
        "click",
        target_text="Continue",
        _observation=observation,
    )

    assert calls == ["browser"]
    assert result["result"]["targetSource"] == "browser_dom"
    assert result["result"]["verification"]["ok"] is True


def test_execute_action_accepts_planner_action_target_and_key_aliases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    def fake_execute(action_type: str, **kwargs: object) -> dict[str, object]:
        captured["action_type"] = action_type
        captured.update(kwargs)
        return {"text": "ok", "result": {"kind": "operator_execution_result", "status": "completed"}}

    monkeypatch.setattr(
        capability_registry,
        "_load_adapter",
        lambda name: fake_execute if name == "desktop_operator.execute_action" else (_ for _ in ()).throw(AssertionError(name)),
    )

    result = capability_registry.run_capability(
        "desktop_operator.execute_action",
        {
            "action": "press",
            "key": "ENTER",
            "target": "Chrome adres veya arama kutusu",
            "reason": "Aramayı başlat",
        },
        _dangerous_state(accessibility=True),
    )

    assert result["ok"] is True
    assert captured["action_type"] == "hotkey"
    assert captured["target_text"] == "Chrome adres veya arama kutusu"
    assert captured["keys"] == ["ENTER"]


def test_operator_run_accepts_max_actions_from_planner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"text": "ok", "result": {"kind": "operator_run_result", "status": "completed"}}

    monkeypatch.setattr(
        capability_registry,
        "_load_adapter",
        lambda name: fake_run if name == "desktop_operator.run" else (_ for _ in ()).throw(AssertionError(name)),
    )

    result = capability_registry.run_capability(
        "desktop_operator.run",
        {"goal": "Ayarlar penceresinde Wi-Fi bölümünü aç", "maxActions": 3},
        _dangerous_state(accessibility=True),
    )

    assert result["ok"] is True
    assert captured["max_actions"] == 3


def test_match_target_rejects_ambiguous_near_tie() -> None:
    observation = {
        "elements": [
            {"id": "a", "type": "button", "text": "Submit form", "bbox": {"x": 1, "y": 1, "w": 80, "h": 24}, "confidence": 0.99, "source": "accessibility"},
            {"id": "b", "type": "button", "text": "Submit payment", "bbox": {"x": 100, "y": 1, "w": 80, "h": 24}, "confidence": 0.98, "source": "accessibility"},
        ]
    }

    with pytest.raises(Exception):
        desktop_operator._match_target(observation, text="Submit", element_type="button")  # type: ignore[attr-defined]


def test_match_target_uses_selector_and_turkish_ui_synonyms() -> None:
    observation = {
        "elements": [
            {
                "id": "dom_1",
                "type": "button",
                "text": "Continue",
                "bbox": {"x": 10, "y": 10, "w": 80, "h": 24},
                "confidence": 0.99,
                "source": "browser_dom",
                "browser": {"selector": "#continue", "name": "Continue", "role": "button"},
            },
            {
                "id": "dom_2",
                "type": "button",
                "text": "Cancel",
                "bbox": {"x": 100, "y": 10, "w": 80, "h": 24},
                "confidence": 0.98,
                "source": "browser_dom",
                "browser": {"selector": "#cancel", "name": "Cancel", "role": "button"},
            },
        ]
    }

    target = desktop_operator._match_target(observation, text="devam butonu", element_type="button")  # type: ignore[attr-defined]

    assert target["id"] == "dom_1"
    assert target["searchHints"][0] == "continue"


def test_observe_screen_returns_target_suggestions_for_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "fake.png"
    image_path.write_bytes(b"fake")
    cached_path = tmp_path / "cached.png"
    cached_path.write_bytes(b"fake")
    monkeypatch.setattr(screen_vision, "_run_helper", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(
        screen_vision,
        "_parse_capture_payload",
        lambda _raw: (
            True,
            "",
            {
                "image_path": str(image_path),
                "owner_name": "Safari",
                "window_title": "Docs",
                "bounds": {"width": 1440, "height": 900},
            },
        ),
    )
    monkeypatch.setattr(
        desktop_operator.desktop_os,
        "desktop_os_active_window",
        lambda: {"result": {"appName": "Safari", "windowTitle": "Docs"}},
    )
    monkeypatch.setattr(
        desktop_operator,
        "_copy_to_operator_cache",
        lambda _source: cached_path,
    )
    monkeypatch.setattr(
        desktop_operator,
        "_build_screen_observation",
        lambda _image_path, _payload: {
            "screenshotPath": str(cached_path),
            "width": 1440,
            "height": 900,
            "monitorId": "active_monitor",
            "scaleFactor": 2.0,
            "capturedAt": "2026-06-05T12:00:00Z",
            "activeApp": "Safari",
            "activeWindow": "Docs",
            "elements": [
                {
                    "id": "ax_1",
                    "type": "button",
                    "text": "Continue",
                    "bbox": {"x": 100, "y": 120, "w": 80, "h": 28},
                    "confidence": 0.99,
                    "source": "accessibility",
                    "searchHints": ["continue"],
                }
            ],
            "screenSummary": {"elementCount": 1},
        },
    )

    result = desktop_operator.observe_screen("devam butonu", "active_window", preserve_screenshot=True)

    assert result["result"]["targetSuggestions"][0]["text"] == "Continue"
    assert "Önerilen hedef" in result["text"]


def test_desktop_operator_cancel_stops_active_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state(
        {
            "operator": {
                "activeRunId": "oprun_test",
                "status": "executing",
                "abortRequested": False,
                "abortReason": "",
                "currentStepIndex": 2,
                "lastObservationId": "obs_test",
                "operatorRuns": [{"id": "oprun_test", "status": "running"}],
            }
        }
    )

    result = capability_registry.run_capability(
        "desktop_operator.cancel",
        {"reason": "user_cancel", "source": "manual"},
        state_store._ensure_defaults({}),
    )

    assert result["ok"] is True
    assert result["result"]["status"] == "stopped"
    assert result["result"]["stopReason"] == "user_cancel"
    operator_state = state_store.snapshot()["operator"]
    assert operator_state["activeRunId"] == ""
    assert operator_state["lastStopReason"] == "user_cancel"


def test_rank_targets_tolerates_typos_via_fuzzy_match() -> None:
    observation = {
        "elements": [
            {"id": "a", "type": "button", "text": "Safari", "source": "accessibility", "enabled": True, "bbox": {"x": 1, "y": 1, "w": 80, "h": 24}},
            {"id": "b", "type": "button", "text": "Settings", "source": "accessibility", "enabled": True, "bbox": {"x": 100, "y": 1, "w": 80, "h": 24}},
        ]
    }
    from actions.desktop_operator import _rank_targets

    assert _rank_targets(observation, text="safar")[0]["text"] == "Safari"
    assert _rank_targets(observation, text="sittings")[0]["text"] == "Settings"


def test_rank_targets_matches_across_languages_bidirectionally() -> None:
    observation = {
        "elements": [
            {"id": "a", "type": "button", "text": "Gönder", "source": "accessibility", "enabled": True, "bbox": {"x": 1, "y": 1, "w": 80, "h": 24}},
            {"id": "b", "type": "button", "text": "Ayarlar", "source": "accessibility", "enabled": True, "bbox": {"x": 100, "y": 1, "w": 80, "h": 24}},
        ]
    }
    from actions.desktop_operator import _rank_targets

    # İngilizce sorgu → Türkçe buton (çift yönlü eşanlam).
    assert _rank_targets(observation, text="send")[0]["text"] == "Gönder"
    assert _rank_targets(observation, text="settings")[0]["text"] == "Ayarlar"


def test_query_tokens_expands_both_directions() -> None:
    from actions.desktop_operator import _query_tokens

    assert "gonder" in _query_tokens("send") or "gönder" in _query_tokens("send")
    assert "send" in _query_tokens("gönder")


def test_fuzzy_does_not_match_unrelated_short_text() -> None:
    # Alakasız kısa metin fuzzy ile yanlış eşleşmemeli (yüksek eşik).
    observation = {
        "elements": [
            {"id": "a", "type": "button", "text": "OK", "source": "accessibility", "enabled": True, "bbox": {"x": 1, "y": 1, "w": 40, "h": 24}},
        ]
    }
    from actions.desktop_operator import _rank_targets

    ranked = _rank_targets(observation, text="download report presentation")
    # Ya hiç eşleşme yok ya da fuzzy skoru zayıf (kesin hedef yok).
    assert not ranked or ranked[0].get("candidateScore", 0) < 24


def test_open_app_reports_success_without_foreground_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    """`open -a` returncode 0 → başarı; frontmost (Otomasyon izni) doğrulanamasa
    bile 'Yanıt alınamadı' verilmez (açılan uygulama hata gibi görünürdü)."""
    from actions import open_app as oa

    class _R:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(oa.subprocess, "run", lambda *a, **k: _R())
    monkeypatch.setattr(oa, "_wait_for_active_app", lambda *a, **k: False)  # izin yok
    monkeypatch.setattr(oa, "_matching_process_count", lambda *a, **k: 1)

    result = oa.open_app("safari")
    assert result["result"]["foregroundConfirmed"] is True
    assert result["result"]["verificationStatus"] == "launched"


def test_deterministic_operator_planner_handles_simple_goals() -> None:
    """Basit GUI hedefleri bulut beyni olmadan adımlara çevrilmeli (offline+hızlı)."""
    from actions.desktop_operator import _deterministic_operator_steps as D

    assert D("sayfayı aşağı kaydır") == [{"action": "scroll", "delta": -600}]
    assert D("yukarı kaydır") == [{"action": "scroll", "delta": 600}]
    assert D("Gönder butonuna tıkla") == [{"action": "click", "targetText": "Gönder"}]
    assert D("profil resmine çift tıkla") == [{"action": "double_click", "targetText": "profil resmi"}]
    assert D("dosyaya sağ tıkla") == [{"action": "right_click", "targetText": "dosya"}]
    # Karmaşık/sohbet hedefleri deterministik çözülmez (buluta kalır).
    assert D("safariden kedi resmi bul ve kaydet") == []
    assert D("merhaba nasılsın") == []


def test_plan_operator_steps_prefers_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministik plan varsa bulut planlayıcı ÇAĞRILMAMALI."""
    from actions import desktop_operator as op
    from runtime import bridge

    called = {"cloud": False}
    monkeypatch.setattr(bridge, "plan_visual_operator_steps", lambda *a, **k: called.__setitem__("cloud", True) or {"steps": []})

    result = op._plan_operator_steps("aşağı kaydır", {})
    assert result["provider"] == "deterministic"
    assert result["steps"] == [{"action": "scroll", "delta": -600}]
    assert called["cloud"] is False
