from __future__ import annotations

from elyan.bootstrap import onboard


def test_configure_selected_channel_telegram(monkeypatch):
    store = {"channels": []}

    monkeypatch.setattr(onboard.elyan_config, "get", lambda key, default=None: store.get(key, default))
    monkeypatch.setattr(onboard.elyan_config, "set", lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr(onboard.channel_cli, "_store_secret", lambda env_key, secret: f"${env_key}")  # noqa: ARG005
    monkeypatch.setattr("builtins.input", lambda prompt='': "telegram-token")

    assert onboard._configure_selected_channel("telegram", headless=False) is True
    assert store["channels"][0]["type"] == "telegram"
    assert store["channels"][0]["token"] == "$TELEGRAM_BOT_TOKEN"


def test_configure_selected_channel_whatsapp_headless(monkeypatch):
    store = {"channels": []}

    monkeypatch.setattr(onboard.elyan_config, "get", lambda key, default=None: store.get(key, default))
    monkeypatch.setattr(onboard.elyan_config, "set", lambda key, value: store.__setitem__(key, value))

    assert onboard._configure_selected_channel("whatsapp", headless=True) is True
    assert store["channels"][0]["type"] == "whatsapp"
    assert store["channels"][0]["enabled"] is True
