from core.security.runtime_guard import RuntimeSecurityGuard


def test_runtime_guard_blocks_denied_path():
    guard = RuntimeSecurityGuard()
    policy = {
        "security": {
            "enforce_rbac": False,
            "operator_mode": "Operator",
            "path_guard_enabled": True,
            "allowed_roots": ["/tmp"],
            "denied_roots": ["/etc"],
            "dangerous_tools_enabled": True,
        }
    }
    res = guard.evaluate(
        tool_name="write_file",
        params={"path": "/etc/passwd"},
        user_id="u1",
        runtime_policy=policy,
        metadata={"user_role": "operator"},
    )
    assert res["allowed"] is False
    assert "denied" in str(res["reason"]).lower()


def test_runtime_guard_blocks_dangerous_command_pattern():
    guard = RuntimeSecurityGuard()
    policy = {
        "security": {
            "enforce_rbac": False,
            "operator_mode": "Operator",
            "path_guard_enabled": False,
            "dangerous_tools_enabled": True,
            "dangerous_command_patterns": ["rm -rf"],
        }
    }
    res = guard.evaluate(
        tool_name="run_safe_command",
        params={"command": "rm -rf /tmp/x"},
        user_id="u2",
        runtime_policy=policy,
        metadata={"user_role": "operator"},
    )
    assert res["allowed"] is False
    assert "dangerous command pattern" in str(res["reason"]).lower()


def test_runtime_guard_requires_approval_for_guarded_action():
    guard = RuntimeSecurityGuard()
    policy = {
        "security": {
            "enforce_rbac": False,
            "operator_mode": "Confirmed",
            "path_guard_enabled": False,
            "dangerous_tools_enabled": True,
            "require_confirmation_for_risky": True,
        }
    }
    res = guard.evaluate(
        tool_name="run_safe_command",
        params={"command": "echo ok"},
        user_id="u3",
        runtime_policy=policy,
        metadata={"user_role": "operator"},
    )
    assert res["allowed"] is True
    assert res["requires_approval"] is False


def test_runtime_guard_requires_approval_for_dangerous_action():
    guard = RuntimeSecurityGuard()
    policy = {
        "security": {
            "enforce_rbac": False,
            "operator_mode": "Confirmed",
            "path_guard_enabled": False,
            "dangerous_tools_enabled": True,
            "require_confirmation_for_risky": True,
        }
    }
    res = guard.evaluate(
        tool_name="shutdown_system",
        params={},
        user_id="u3b",
        runtime_policy=policy,
        metadata={"user_role": "operator"},
    )
    assert res["allowed"] is True
    assert res["requires_approval"] is True


def test_runtime_guard_full_autonomy_disables_confirmation():
    guard = RuntimeSecurityGuard()
    policy = {
        "security": {
            "enforce_rbac": False,
            "operator_mode": "Operator",
            "path_guard_enabled": False,
            "dangerous_tools_enabled": True,
            "require_confirmation_for_risky": False,
        }
    }
    res = guard.evaluate(
        tool_name="run_safe_command",
        params={"command": "echo ok"},
        user_id="u4",
        runtime_policy=policy,
        metadata={"user_role": "operator"},
    )
    assert res["allowed"] is True
    assert res["requires_approval"] is False


def test_runtime_guard_blocks_dangerous_pattern_with_extra_spaces():
    guard = RuntimeSecurityGuard()
    policy = {
        "security": {
            "enforce_rbac": False,
            "operator_mode": "Operator",
            "path_guard_enabled": False,
            "dangerous_tools_enabled": True,
            "dangerous_command_patterns": ["rm -rf"],
        }
    }
    res = guard.evaluate(
        tool_name="run_safe_command",
        params={"command": "rm      -rf /tmp/x"},
        user_id="u5",
        runtime_policy=policy,
        metadata={"user_role": "operator"},
    )
    assert res["allowed"] is False
    assert "dangerous command pattern" in str(res["reason"]).lower()


def test_runtime_guard_blocks_invalid_pathlike_parameter():
    guard = RuntimeSecurityGuard()
    policy = {
        "security": {
            "enforce_rbac": False,
            "operator_mode": "Operator",
            "path_guard_enabled": True,
            "allowed_roots": ["/tmp"],
            "denied_roots": [],
            "dangerous_tools_enabled": True,
        }
    }
    res = guard.evaluate(
        tool_name="write_file",
        params={"path": "file:///etc/passwd"},
        user_id="u6",
        runtime_policy=policy,
        metadata={"user_role": "operator"},
    )
    assert res["allowed"] is False
    assert "invalid path-like parameter" in str(res["reason"]).lower()
