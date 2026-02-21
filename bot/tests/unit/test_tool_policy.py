"""Unit tests for tool policy deny-first behavior."""

from security.tool_policy import ToolPolicyEngine


def test_group_deny_blocks_tool_even_without_explicit_group():
    engine = ToolPolicyEngine()
    engine.allowed_tools = ["*"]
    engine.denied_tools = ["group:runtime"]
    assert engine.is_allowed("run_command") is False


def test_deny_overrides_allow_for_specific_tool():
    engine = ToolPolicyEngine()
    engine.allowed_tools = ["group:runtime", "run_command"]
    engine.denied_tools = ["run_command"]
    assert engine.is_allowed("run_command") is False


def test_check_access_requires_approval_from_group_policy():
    engine = ToolPolicyEngine()
    engine.allowed_tools = ["group:runtime"]
    engine.denied_tools = []
    engine.require_approval = ["group:runtime"]
    access = engine.check_access("run_command")
    assert access["allowed"] is True
    assert access["requires_approval"] is True


def test_reload_reads_require_approval_from_camel_case(monkeypatch):
    values = {
        "tools.allow": ["group:web"],
        "tools.deny": [],
        "tools.require_approval": None,
        "tools.requireApproval": ["group:web"],
    }
    monkeypatch.setattr(
        "security.tool_policy.elyan_config.get",
        lambda key, default=None: values.get(key, default),
    )
    engine = ToolPolicyEngine()
    assert "group:web" in engine.require_approval


def test_infer_group_covers_messaging_and_automation():
    engine = ToolPolicyEngine()
    assert engine.infer_group("send_email") == "messaging"
    assert engine.infer_group("create_event") == "automation"
