from core.runtime_policy import RuntimePolicyResolver


def test_runtime_policy_resolve_includes_share_attachments_default(monkeypatch):
    values = {
        "agent.runtime_policy.preset": "balanced",
        "agent.flags.agentic_v2": False,
        "agent.flags.dag_exec": False,
        "agent.flags.strict_taskspec": False,
        "agent.capability_router.enabled": True,
        "agent.capability_router.min_confidence_override": 0.5,
        "agent.planning.use_llm": True,
        "agent.planning.max_subtasks": 10,
        "agent.multi_agent.enabled": True,
        "agent.multi_agent.complexity_threshold": 0.9,
        "agent.multi_agent.capability_confidence_threshold": 0.7,
        "agent.team_mode.threshold": 0.95,
        "agent.team_mode.max_parallel": 4,
        "agent.team_mode.timeout_s": 900,
        "agent.team_mode.max_retries_per_task": 1,
        "agent.api_tools.enabled": True,
        "skills.enabled": [],
        "skills.workflows.enabled": [],
        "tools.allow": [],
        "tools.deny": [],
        "tools.requireApproval": [],
        "tools.require_approval": [],
        "agent.response_style.friendly": True,
        "agent.response_style.mode": "friendly",
        "agent.response_style.share_manifest_default": False,
        "agent.response_style.share_attachments_default": True,
        "security.operatorMode": "Confirmed",
        "agent.model.local_first": True,
        "security.defaultUserRole": "operator",
        "security.enforceRBAC": True,
        "security.pathGuard.enabled": True,
        "security.pathGuard.allowedRoots": [],
        "security.pathGuard.deniedRoots": [],
        "security.dangerousCommandPatterns": [],
        "security.enableDangerousTools": True,
        "security.requireConfirmationForRisky": True,
        "security.requireEvidenceForDangerous": True,
        "security.kvkk.strict": True,
        "security.kvkk.redactCloudPrompts": True,
        "security.kvkk.allowCloudFallback": True,
    }
    monkeypatch.setattr("core.runtime_policy.elyan_config.get", lambda key, default=None: values.get(key, default))

    policy = RuntimePolicyResolver().resolve()
    assert policy.response["share_attachments_default"] is True


def test_runtime_policy_full_autonomy_preset_sets_attachment_sharing_default(monkeypatch):
    store = {}

    def _set(key, value):
        store[key] = value

    monkeypatch.setattr("core.runtime_policy.elyan_config.set", _set)
    monkeypatch.setattr("core.runtime_policy.elyan_config.get", lambda key, default=None: store.get(key, default))

    RuntimePolicyResolver().apply_preset("full-autonomy")
    assert store.get("agent.response_style.share_manifest_default") is False
    assert store.get("agent.response_style.share_attachments_default") is False
