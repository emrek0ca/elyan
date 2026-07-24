from __future__ import annotations

from runtime import capability_registry
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


def test_capability_metadata_exposes_only_single_full_access_permission_surface() -> None:
    for capability in capability_registry.capability_names():
        metadata = capability_registry.capability_metadata(capability)
        permissions = metadata.get("requiredPermissions", [])
        if not permissions:
            continue
        assert permissions == ["full_computer_access"], capability


def test_default_output_paths_are_unique(tmp_path) -> None:
    from actions import _write_common

    # Varsayılan çıktı artık masaüstüne gider; testte izole bir dizinle
    # (desktop_resolver) benzersizlik davranışı doğrulanır.
    desktop_resolver = lambda: tmp_path
    first = _write_common.ensure_allowed_output_path("", extension=".docx", hint="rapor", desktop_resolver=desktop_resolver)
    first.write_text("x", encoding="utf-8")
    second = _write_common.ensure_allowed_output_path("", extension=".docx", hint="rapor", desktop_resolver=desktop_resolver)

    assert first.name == "rapor.docx"
    assert second.name == "rapor-2.docx"
    assert first.parent == tmp_path


def test_default_output_targets_desktop(monkeypatch, tmp_path) -> None:
    from actions import _write_common

    fake_desktop = tmp_path / "Desktop"
    monkeypatch.setattr(_write_common, "desktop_dir", lambda: fake_desktop)
    resolved = _write_common.ensure_allowed_output_path("", extension=".txt", hint="notlar")
    assert resolved.parent == fake_desktop.resolve()
    assert resolved.name == "notlar.txt"
