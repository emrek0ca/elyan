from types import SimpleNamespace

from cli.commands import channels


class _DummyProc:
    def __init__(self):
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self._alive = False

    def wait(self, timeout=None):  # noqa: ARG002
        self._alive = False
        return 0

    def kill(self):
        self._alive = False


def test_login_whatsapp_updates_config(monkeypatch, tmp_path):
    store = {"channels": []}

    monkeypatch.setattr(channels.elyan_config, "get", lambda key, default=None: store.get("channels", default) if key == "channels" else default)
    monkeypatch.setattr(channels.elyan_config, "set", lambda key, value: store.__setitem__("channels", value) if key == "channels" else None)

    monkeypatch.setattr(channels, "ensure_bridge_runtime", lambda force_install=False: None)  # noqa: ARG005
    monkeypatch.setattr(channels, "generate_bridge_token", lambda: "tok-123")
    monkeypatch.setattr(channels, "start_bridge_process", lambda **kwargs: _DummyProc())  # noqa: ARG005
    monkeypatch.setattr(channels, "wait_for_bridge", lambda **kwargs: {"ok": True, "state": {"ready": True}})  # noqa: ARG005
    monkeypatch.setattr(channels, "stop_bridge", lambda **kwargs: True)  # noqa: ARG005
    monkeypatch.setattr(channels, "_store_secret", lambda env_key, secret: f"${env_key}")  # noqa: ARG005

    ok = channels.login_whatsapp(
        channel_id="whatsapp",
        bridge_port=19992,
        session_dir=tmp_path / "wa-session",
        timeout_s=2,
    )
    assert ok is True

    configured = store["channels"][0]
    assert configured["type"] == "whatsapp"
    assert configured["bridge_url"] == "http://127.0.0.1:19992"
    assert configured["bridge_token"] == "$WHATSAPP_BRIDGE_TOKEN"
    assert configured["enabled"] is True


def test_run_add_whatsapp_delegates_login(monkeypatch):
    called = {"ok": False}
    monkeypatch.setattr(channels, "login_whatsapp", lambda channel_id="whatsapp", **kwargs: called.__setitem__("ok", True) or True)  # noqa: ARG005
    monkeypatch.setattr("builtins.input", lambda prompt="": "")  # noqa: ARG005

    args = SimpleNamespace(
        subcommand="add",
        type="whatsapp",
        channel_type=None,
        channel_id=None,
        json=False,
    )
    channels.run(args)
    assert called["ok"] is True


def test_configure_whatsapp_cloud_updates_config(monkeypatch):
    store = {"channels": []}
    monkeypatch.setattr(channels.elyan_config, "get", lambda key, default=None: store.get("channels", default) if key == "channels" else default)
    monkeypatch.setattr(channels.elyan_config, "set", lambda key, value: store.__setitem__("channels", value) if key == "channels" else None)
    monkeypatch.setattr(channels, "_store_secret", lambda env_key, secret: f"${env_key}")  # noqa: ARG005
    answers = iter(["123456", "wa-token", "verify-me"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))  # noqa: ARG005

    ok = channels.configure_whatsapp_cloud(channel_id="whatsapp")
    assert ok is True
    configured = store["channels"][0]
    assert configured["mode"] == "cloud"
    assert configured["phone_number_id"] == "123456"
    assert configured["access_token"] == "$WHATSAPP_ACCESS_TOKEN"
    assert configured["verify_token"] == "$WHATSAPP_VERIFY_TOKEN"


def test_run_list_json_masks_sensitive(monkeypatch, capsys):
    data = [
        {
            "type": "whatsapp",
            "id": "whatsapp",
            "bridge_token": "plain-secret",
            "token": "legacy-secret",
            "enabled": True,
        }
    ]
    monkeypatch.setattr(channels.elyan_config, "get", lambda key, default=None: data if key == "channels" else default)

    args = SimpleNamespace(
        subcommand="list",
        json=True,
        type=None,
        channel_type=None,
        channel_id=None,
    )
    channels.run(args)
    output = capsys.readouterr().out
    assert "***" in output
    assert "plain-secret" not in output
    assert "legacy-secret" not in output
