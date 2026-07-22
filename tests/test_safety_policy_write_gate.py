from __future__ import annotations

from runtime import safety_policy


def test_write_capabilities_require_confirmation() -> None:
    # file_write / file_patch onaysız BLOKLANIR, _confirmed ile geçer.
    for cap in ("file_write", "file_patch"):
        blocked = safety_policy.evaluate_tool(cap, {}, {})
        assert blocked.allowed is False
        assert blocked.code == "PERMISSION_REQUIRED"
        allowed = safety_policy.evaluate_tool(cap, {"_confirmed": True}, {})
        assert allowed.allowed is True


def test_git_mutations_require_confirmation() -> None:
    for cap in ("git_commit", "git_branch"):
        blocked = safety_policy.evaluate_tool(cap, {}, {})
        assert blocked.allowed is False
        assert blocked.code == "PERMISSION_REQUIRED"
        allowed = safety_policy.evaluate_tool(cap, {"_confirmed": True}, {})
        assert allowed.allowed is True


def test_write_side_tools_are_not_known_safe() -> None:
    # Yazma/mutasyon tool'ları asla "her zaman serbest" olmamalı.
    for cap in ("file_write", "file_patch", "git_commit", "git_branch"):
        assert cap not in safety_policy.KNOWN_SAFE_TOOLS


def test_read_side_dev_tools_are_known_safe() -> None:
    for cap in ("file_read", "file_search", "directory_tree", "git_status", "git_diff"):
        assert cap in safety_policy.KNOWN_SAFE_TOOLS
        assert safety_policy.evaluate_tool(cap, {}, {}).allowed is True


def test_permission_tools_use_single_full_access_surface() -> None:
    legacy_split_permission = {
        "account": {"dangerousAreaEnabled": True},
        "permissions": {"allow_browser_control": True},
    }
    full_access = {"runtime": {"access": {"fullAccessSession": {"enabled": True}}}}

    denied = safety_policy.evaluate_tool("browser_control", {}, legacy_split_permission)
    allowed = safety_policy.evaluate_tool("browser_control", {}, full_access)

    assert denied.allowed is False
    assert denied.code == "PERMISSION_REQUIRED"
    assert allowed.allowed is True
