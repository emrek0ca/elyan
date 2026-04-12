from __future__ import annotations

import asyncio
import time
from difflib import get_close_matches
from typing import Any

from config.elyan_config import elyan_config
from core.command_hardening import requires_screen_state, screen_state_is_actionable
from core.feature_flags import get_feature_flag_registry
from core.self_healing import get_healing_engine
from core.knowledge_base import get_knowledge_base
from core.pipeline_state import get_pipeline_state
from core.process_profiles import PREAPPROVAL_BLOCKED_TOOLS, normalize_workflow_profile
from core.proactive.intervention import get_intervention_manager
from core.repair.state_machine import classify_error
from core.security.runtime_guard import runtime_security_guard
from core.timeout_guard import RESEARCH_TIMEOUT, TOOL_TIMEOUT, friendly_timeout_message
from core.tool_request import get_tool_request_log
from core.tool_usage import record_tool_usage
from core.runtime_modes import get_agent_mode_policy, normalize_agent_mode
from security.privacy_guard import is_external_provider, redact_text
from security.tool_policy import tool_policy
from utils.logger import get_logger

from .contracts import ExecutionOutcome, ExecutionRequest, ToolSpec, VerificationEnvelope

logger = get_logger("tool_runtime_executor")


def _agent_runtime():
    from core import agent as agent_module

    return agent_module


def _available_tools():
    return _agent_runtime().AVAILABLE_TOOLS


class ToolRuntimeExecutor:
    @staticmethod
    def _evaluate_mode_policy(tool_name: str, runtime_policy: dict[str, Any], *, user_id: str = "") -> dict[str, Any]:
        policy = dict(runtime_policy or {})
        metadata = policy.get("metadata", {}) if isinstance(policy.get("metadata"), dict) else {}
        flag_enabled = get_feature_flag_registry().is_enabled(
            "capability_mode_policy",
            runtime_policy=policy,
            user_id=str(user_id or ""),
            context=metadata,
        )
        mode = normalize_agent_mode(
            metadata.get("agent_mode")
            or (policy.get("execution", {}) if isinstance(policy.get("execution"), dict) else {}).get("agent_mode")
            or "chat"
        )
        mode_policy = get_agent_mode_policy(mode)
        tool_group = tool_policy.infer_group(tool_name) or ""
        allowed = mode_policy.allows_tool(tool_name, tool_group)
        if not flag_enabled:
            allowed = True
        return {
            "enabled": bool(flag_enabled),
            "mode": mode,
            "tool_group": tool_group,
            "allowed": bool(allowed),
            "reason": "" if allowed else f"Agent mode '{mode}' bu aracı desteklemiyor.",
            "policy": mode_policy.to_dict(),
        }

    def _resolve_spec(self, agent: Any, request: ExecutionRequest) -> ToolSpec:
        safe_params = request.params if isinstance(request.params, dict) else {}
        clean_params = {k: v for k, v in safe_params.items() if k not in ("action", "type")}
        mapped_tool = dict(request.action_aliases or {}).get(request.tool_name, request.tool_name)
        resolved_tool = agent._resolve_tool_name(mapped_tool)
        if resolved_tool:
            mapped_tool = resolved_tool
        if mapped_tool == "advanced_research" and agent._should_upgrade_research_to_delivery(
            f"{request.step_name} {request.user_input}",
            clean_params,
        ):
            mapped_tool = "research_document_delivery"
        clean_params = agent._normalize_param_aliases(mapped_tool, clean_params)
        return ToolSpec(
            requested_name=str(request.tool_name or ""),
            resolved_name=str(mapped_tool or request.tool_name or ""),
            params=dict(clean_params or {}),
            source="agent",
        )

    async def execute_outcome(self, agent: Any, request: ExecutionRequest) -> ExecutionOutcome:
        spec = self._resolve_spec(agent, request)
        result = await self.execute(agent, request)
        success = not (isinstance(result, dict) and result.get("success") is False)
        error_text = str(result.get("error") or "") if isinstance(result, dict) else ""
        return ExecutionOutcome(
            spec=spec,
            result=dict(result or {}) if isinstance(result, dict) else {"success": success, "message": str(result or "")},
            success=success,
            error_text=error_text,
            verification=VerificationEnvelope.from_result(result),
        )

    async def execute(self, agent: Any, request: ExecutionRequest) -> dict[str, Any]:
        tool_name = str(request.tool_name or "")
        params = dict(request.params or {}) if isinstance(request.params, dict) else {}
        user_input = str(request.user_input or "")
        step_name = str(request.step_name or "")
        pipeline_state = request.pipeline_state
        pipeline = pipeline_state or get_pipeline_state()
        params = pipeline.resolve_placeholders(params)

        safe_params = params if isinstance(params, dict) else {}
        clean_params = {k: v for k, v in safe_params.items() if k not in ("action", "type")}
        mapped_tool = dict(request.action_aliases or {}).get(tool_name, tool_name)
        resolved_tool = agent._resolve_tool_name(mapped_tool)
        if resolved_tool:
            mapped_tool = resolved_tool
        if mapped_tool == "advanced_research" and agent._should_upgrade_research_to_delivery(
            f"{step_name} {user_input}",
            clean_params,
        ):
            mapped_tool = "research_document_delivery"
        clean_params = agent._normalize_param_aliases(mapped_tool, clean_params)
        try:
            from core.reliability_integration import sanitize_and_validate_params

            param_ok, clean_params, validation_error = sanitize_and_validate_params(mapped_tool, clean_params)
            if not param_ok and validation_error is not None:
                _agent_runtime()._push_tool_event(
                    "end",
                    mapped_tool,
                    step=step_name,
                    request_id="",
                    success=False,
                    payload={
                        "error": validation_error.message,
                        "error_code": validation_error.code,
                        "validation": validation_error.to_dict(),
                    },
                )
                return {
                    "success": False,
                    "error": validation_error.message,
                    "error_code": validation_error.code,
                    "validation": validation_error.to_dict(),
                }
        except Exception as validation_exc:
            logger.debug(f"Tool validation skipped for {mapped_tool}: {validation_exc}")
        start = time.perf_counter()
        success = False
        err_text = ""
        used_tool = mapped_tool
        task_category = str(step_name or mapped_tool or "default").strip().lower() or "default"
        runtime_facade = None
        try:
            from core.elyan_runtime import get_elyan_runtime

            runtime_facade = get_elyan_runtime()
        except Exception:
            runtime_facade = None
        circuit_breaker = None
        if runtime_facade is not None:
            try:
                circuit_breaker = runtime_facade.circuit_registry.get_or_create(mapped_tool)
            except Exception:
                circuit_breaker = None

        request_log = get_tool_request_log()
        request_record = request_log.start_request(
            mapped_tool,
            clean_params,
            source="agent",
            user_input=user_input,
            step_name=step_name,
        )
        _agent_runtime()._push_tool_event(
            "start",
            mapped_tool,
            step=step_name,
            request_id=str(getattr(request_record, "request_id", "") or ""),
            payload={"params": clean_params, "user_input": str(user_input or "")[:140]},
        )

        uid = str(agent.current_user_id or "").strip()
        runtime_policy = agent._current_runtime_policy()
        runtime_meta = runtime_policy.get("metadata", {}) if isinstance(runtime_policy.get("metadata"), dict) else {}
        workflow_cfg = runtime_policy.get("workflow", {}) if isinstance(runtime_policy.get("workflow"), dict) else {}
        workflow_session = runtime_meta.get("workflow_session", {}) if isinstance(runtime_meta.get("workflow_session"), dict) else {}
        runtime_uid = str(runtime_meta.get("user_id") or "").strip()
        if not uid or uid.lower() in {"local", "none", "null", "0"}:
            uid = runtime_uid or uid or "local"
        channel = str(runtime_meta.get("channel", "") or runtime_meta.get("channel_type", "") or "").strip()
        workflow_profile = normalize_workflow_profile(
            runtime_meta.get("workflow_profile") or workflow_cfg.get("profile") or workflow_session.get("workflow_profile")
        )
        workflow_phase = str(
            runtime_meta.get("workflow_phase")
            or workflow_session.get("workflow_phase")
            or "intake"
        ).strip().lower()
        workflow_domain = str(
            runtime_meta.get("capability_domain")
            or workflow_session.get("capability_domain")
            or ""
        ).strip().lower()
        runtime_meta["user_input"] = str(user_input or "")
        runtime_meta["tool_name"] = mapped_tool

        if requires_screen_state(mapped_tool):
            screen_state_payload = runtime_meta.get("screen_state") or runtime_meta.get("screen_state_payload")
            if not screen_state_payload:
                try:
                    screen_state_payload = pipeline.get("screen_state")
                except Exception:
                    screen_state_payload = None
            actionable, screen_reason = screen_state_is_actionable(screen_state_payload)
            if not actionable:
                err_text = f"screen_state_required:{screen_reason}"
                _agent_runtime()._push_tool_event(
                    "end",
                    mapped_tool,
                    step=step_name,
                    request_id=str(getattr(request_record, "request_id", "") or ""),
                    success=False,
                    payload={"error": err_text},
                )
                return {
                    "success": False,
                    "error": "Ekran durumu yeterli değil. Önce görünür ve etkileşilebilir bir ekran bağlamı üret.",
                    "error_code": "SCREEN_STATE_UNAVAILABLE",
                }

        approval_required_for_workflow = bool(workflow_cfg.get("require_explicit_approval", True))
        allowed_workflow_domains = {
            str(x or "").strip().lower()
            for x in list(workflow_cfg.get("allowed_domains") or [])
            if str(x or "").strip()
        }
        if (
            workflow_profile != "default"
            and approval_required_for_workflow
            and workflow_phase not in {"approved", "plan_ready", "executing", "finished"}
            and (not allowed_workflow_domains or workflow_domain in allowed_workflow_domains)
            and mapped_tool in PREAPPROVAL_BLOCKED_TOOLS
        ):
            return {
                "success": False,
                "error": "Superpowers workflow aktif: bu araç explicit approval olmadan çalıştırılamaz.",
                "error_code": "WORKFLOW_APPROVAL_REQUIRED",
            }

        typed_tools_strict = False
        try:
            typed_tools_strict = bool(elyan_config.get("agent.flags.typed_tools_strict", False))
        except Exception:
            logger.debug("typed_tools_strict config lookup skipped")
        try:
            ff = runtime_policy.get("feature_flags", {}) if isinstance(runtime_policy.get("feature_flags"), dict) else {}
            if "typed_tools_strict" in ff:
                typed_tools_strict = bool(ff.get("typed_tools_strict"))
        except Exception:
            logger.debug("typed_tools_strict runtime override skipped")
        if typed_tools_strict:
            try:
                from core.pipeline_upgrade.executor import validate_tool_io

                in_gate = validate_tool_io(mapped_tool, clean_params if isinstance(clean_params, dict) else {}, {})
                if not in_gate.ok:
                    err_text = f"typed_tool_input_rejected:{';'.join(in_gate.errors)}"
                    _agent_runtime()._push_tool_event(
                        "end",
                        mapped_tool,
                        step=step_name,
                        request_id=str(getattr(request_record, "request_id", "") or ""),
                        success=False,
                        payload={"error": err_text},
                    )
                    return {"success": False, "error": err_text, "error_code": "TOOL_INPUT_SCHEMA"}
            except Exception:
                logger.debug(f"typed tool gate skipped for {mapped_tool}")

        guard = runtime_security_guard.evaluate(
            tool_name=mapped_tool,
            params=clean_params,
            user_id=uid,
            runtime_policy=runtime_policy,
            metadata=runtime_meta,
        )
        if not guard.get("allowed", False):
            err_text = str(guard.get("reason") or "Security policy blocked this action.")
            agent._audit_security_event(uid, f"runtime_guard_block:{mapped_tool}", err_text, params={"tool": mapped_tool, "risk": guard.get("risk")}, channel=channel)
            return {"success": False, "error": err_text, "error_code": "SECURITY_BLOCKED"}

        policy_check = tool_policy.check_access(mapped_tool)
        if not policy_check.get("allowed", False):
            deny_raw = elyan_config.get("tools.deny", []) or []
            deny = {str(x).strip() for x in deny_raw if str(x).strip()}
            group = tool_policy.infer_group(mapped_tool)
            explicitly_denied = (
                "*" in deny
                or mapped_tool in deny
                or (group is not None and f"group:{group}" in deny)
            )
            if explicitly_denied:
                err_text = str(policy_check.get("reason") or "Tool policy blocked this action.")
                agent._audit_security_event(uid, f"tool_policy_block:{mapped_tool}", err_text, params={"tool": mapped_tool}, channel=channel)
                return {"success": False, "error": err_text, "error_code": "TOOL_POLICY_BLOCKED"}
            policy_check = {"allowed": True, "requires_approval": False, "reason": "allowlist_soft_compat"}

        mode_policy_check = self._evaluate_mode_policy(mapped_tool, runtime_policy, user_id=uid)
        if not mode_policy_check.get("allowed", False):
            err_text = str(mode_policy_check.get("reason") or "Mode policy blocked this action.")
            agent._audit_security_event(
                uid,
                f"mode_policy_block:{mapped_tool}",
                err_text,
                params={
                    "tool": mapped_tool,
                    "mode": str(mode_policy_check.get("mode") or ""),
                    "tool_group": str(mode_policy_check.get("tool_group") or ""),
                },
                channel=channel,
            )
            _agent_runtime()._push_tool_event(
                "end",
                mapped_tool,
                step=step_name,
                request_id=str(getattr(request_record, "request_id", "") or ""),
                success=False,
                payload={
                    "error": err_text,
                    "error_code": "MODE_POLICY_BLOCKED",
                    "mode": str(mode_policy_check.get("mode") or ""),
                },
            )
            return {"success": False, "error": err_text, "error_code": "MODE_POLICY_BLOCKED"}

        requires_approval = bool(policy_check.get("requires_approval") or guard.get("requires_approval"))
        risk_level = str(guard.get("risk") or "").strip().lower()
        try:
            sec_cfg = runtime_policy.get("security", {}) if isinstance(runtime_policy.get("security"), dict) else {}
            critical_only = bool(sec_cfg.get("approval_critical_only", True))
        except Exception:
            critical_only = True
        if critical_only and requires_approval and risk_level != "dangerous":
            requires_approval = False
            agent._audit_security_event(
                uid,
                f"approval_auto_noncritical:{mapped_tool}",
                "critical_only_policy_auto_approved",
                params={"tool": mapped_tool, "risk": risk_level},
                channel=channel,
            )
        try:
            policy_name = str(runtime_policy.get("name") or "").strip().lower()
            sec_cfg = runtime_policy.get("security", {}) if isinstance(runtime_policy.get("security"), dict) else {}
            full_autonomy = (
                policy_name in {"full-autonomy", "full_autonomy", "full"}
                or not bool(sec_cfg.get("require_confirmation_for_risky", True))
            )
            auto_ok_tools = {
                "open_app",
                "close_app",
                "open_url",
                "take_screenshot",
                "analyze_screen",
                "capture_region",
                "type_text",
                "press_key",
                "key_combo",
                "mouse_move",
                "mouse_click",
                "computer_use",
                "run_safe_command",
            }
            if full_autonomy and mapped_tool in auto_ok_tools:
                requires_approval = False
                agent._audit_security_event(
                    uid,
                    f"approval_auto_full_autonomy:{mapped_tool}",
                    "full_autonomy_auto_approved",
                    params={"tool": mapped_tool, "risk": guard.get("risk")},
                    channel=channel,
                )
        except Exception:
            pass
        if requires_approval:
            should_ask = True
            sec_cfg = runtime_policy.get("security", {}) if isinstance(runtime_policy.get("security"), dict) else {}
            interactive_approval = bool(sec_cfg.get("interactive_approval_default", False))
            if "interactive_approval" in runtime_meta:
                interactive_approval = bool(runtime_meta.get("interactive_approval"))

            if not interactive_approval:
                err_text = "Bu islem icin interaktif onay gerekiyor."
                agent._audit_security_event(
                    uid,
                    f"approval_required_noninteractive:{mapped_tool}",
                    "approval_required_noninteractive",
                    params={"tool": mapped_tool, "risk": guard.get("risk")},
                    channel=channel,
                )
                return {"success": False, "error": err_text, "error_code": "APPROVAL_REQUIRED"}

            if agent.learning and hasattr(agent.learning, "check_approval_confidence"):
                confidence = agent.learning.check_approval_confidence(mapped_tool, clean_params)
                if confidence.get("auto_approve"):
                    should_ask = False
                    logger.info(f"Smart Approval: Auto-approved {mapped_tool} ({confidence.get('reason')})")
                    _agent_runtime()._push("security", "brain", f"Auto-approved: {mapped_tool} based on history", True)

            if should_ask:
                manager = get_intervention_manager()
                target_desc = str(clean_params.get("path") or clean_params.get("file_path") or clean_params)
                choice = await manager.ask_human(
                    prompt=f"Kritik işlem onayı gerekiyor: '{mapped_tool}'\nHedef/Detay: {target_desc}\nBu işlemi onaylıyor musun?",
                    context={
                        "tool": mapped_tool,
                        "params": clean_params,
                        "policy_reason": policy_check.get("reason"),
                        "runtime_guard_reason": guard.get("reason"),
                        "risk": guard.get("risk"),
                        "user_id": runtime_uid or uid,
                        "channel": channel,
                        "channel_type": str(runtime_meta.get("channel_type") or channel or "").strip(),
                        "channel_id": str(runtime_meta.get("channel_id") or runtime_meta.get("chat_id") or "").strip(),
                    },
                    options=["Onayla", "İptal Et"],
                )
                if agent.learning:
                    is_approved = choice == "Onayla"
                    try:
                        agent.learning.record_interaction(
                            mapped_tool,
                            clean_params,
                            {
                                "approval_choice": choice,
                                "feedback": "Explicit Approval" if is_approved else "Explicit Rejection",
                            },
                            is_approved,
                            0.0,
                        )
                    except Exception:
                        pass
                if choice != "Onayla":
                    err_text = "İşlem kullanıcı tarafından iptal edildi."
                    agent._audit_security_event(uid, f"approval_rejected:{mapped_tool}", err_text, params={"tool": mapped_tool}, channel=channel)
                    return {"success": False, "error": err_text, "error_code": "USER_ABORTED"}

        if mapped_tool in ("chat", "respond", "answer"):
            prompt = safe_params.get("message") or user_input
            try:
                from core.resilience.fallback_manager import fallback_manager

                contextual = agent._fast_contextual_chat_reply(prompt)
                if contextual:
                    return contextual
                quick = agent._fast_chat_reply(prompt)
                if quick:
                    return quick
                prompt_to_send = prompt
                if agent._is_information_question(prompt):
                    prompt_to_send = agent._build_information_question_prompt(prompt)
                if agent._ensure_llm():
                    llm_cfg, allowed_providers = agent._resolve_llm_config_for_runtime("inference")
                    if llm_cfg.get("type") == "none":
                        result = "KVKK/güvenlik politikası gereği bulut modele fallback kapalı ve yerel model erişilebilir değil."
                    else:
                        provider = str(llm_cfg.get("type") or llm_cfg.get("provider") or "").strip().lower()
                        flags = agent._runtime_security_flags()
                        redacted_prompt = prompt_to_send
                        if bool(flags.get("kvkk_strict_mode")) and bool(flags.get("redact_cloud_prompts")) and is_external_provider(provider):
                            redacted_prompt = redact_text(str(prompt_to_send or ""))
                        result = await fallback_manager.execute_with_fallback(
                            agent,
                            llm_cfg,
                            redacted_prompt,
                            user_id=uid,
                            allowed_providers=allowed_providers if allowed_providers else None,
                        )
                else:
                    result = agent._fallback_chat_without_llm(prompt)
                success = True
                return agent._sanitize_chat_reply(result)
            except Exception as exc:
                err_text = str(exc)
                try:
                    from core.llm.factory import get_llm_client

                    alt_client = get_llm_client("ollama", "llama3.2:3b")
                    result = await alt_client.generate(prompt_to_send, user_id=uid)
                    success = True
                    return agent._sanitize_chat_reply(result)
                except Exception:
                    success = True
                    return agent._fallback_chat_without_llm(prompt)
            finally:
                latency = int((time.perf_counter() - start) * 1000)
                record_tool_usage(used_tool, success=success, latency_ms=latency, source="agent", error=err_text)
                request_log.finish_request(request_record, result if success else {}, latency_ms=latency, success=success, error=err_text)

        clean_params = agent._prepare_tool_params(mapped_tool, clean_params, user_input=user_input, step_name=step_name)

        try:
            timeout_seconds = RESEARCH_TIMEOUT if "research" in mapped_tool else TOOL_TIMEOUT

            async def _run_kernel_tool():
                return await _agent_runtime().with_timeout(
                    agent.kernel.tools.execute(mapped_tool, clean_params),
                    seconds=timeout_seconds,
                    fallback=None,
                    context=f"tool:{mapped_tool}",
                )

            try:
                if circuit_breaker is not None:
                    result = await circuit_breaker.call(_run_kernel_tool)
                else:
                    result = await _run_kernel_tool()
            except Exception as breaker_exc:
                from core.resilience.circuit_breaker import CircuitOpenError

                if isinstance(breaker_exc, CircuitOpenError):
                    if runtime_facade is not None:
                        try:
                            runtime_facade.tool_bandit.disable_tool(task_category, mapped_tool)
                        except Exception:
                            pass
                    fallback_candidates = [name for name in _available_tools().keys() if name != mapped_tool]
                    close_matches = get_close_matches(mapped_tool, fallback_candidates, n=2, cutoff=0.55)
                    fallback_tool = close_matches[0] if close_matches else ""
                    if fallback_tool:
                        used_tool = fallback_tool
                        result = await with_timeout(
                            agent.kernel.tools.execute(fallback_tool, clean_params),
                            seconds=timeout_seconds,
                            fallback=None,
                            context=f"tool:{fallback_tool}",
                        )
                        result = agent._normalize_tool_execution_result(fallback_tool, result, source="agent_kernel_execute_fallback")
                    else:
                        logger.warning(f"Circuit open for {mapped_tool}; falling back to direct execution.")
                        result = await _run_kernel_tool()
                else:
                    raise
            result = agent._normalize_tool_execution_result(mapped_tool, result, source="agent_kernel_execute")
            if isinstance(result, dict) and result.get("success") is False:
                err_text = str(result.get("error", "") or "")
                if not result.get("error_code"):
                    result["error_code"] = classify_error(RuntimeError(err_text or "tool_error"))
                _agent_runtime()._push_tool_event(
                    "update",
                    mapped_tool,
                    step=step_name,
                    request_id=str(getattr(request_record, "request_id", "") or ""),
                    payload={"status": "initial_failure", "error": err_text[:220]},
                )

                healing_engine = get_healing_engine()
                diagnosis = healing_engine.diagnose(err_text)
                kb = get_knowledge_base()
                known_solution = kb.find_solution(mapped_tool, diagnosis.name if diagnosis else err_text)

                if known_solution and "params" in known_solution:
                    logger.info(f"Proven solution found in Knowledge Base for '{mapped_tool}'. Retrying with proven params.")
                    _agent_runtime()._push_tool_event(
                        "update",
                        mapped_tool,
                        step=step_name,
                        request_id=str(getattr(request_record, "request_id", "") or ""),
                        payload={"status": "kb_retry"},
                    )
                    retry_result = agent._normalize_tool_execution_result(
                        mapped_tool,
                        await agent.kernel.tools.execute(mapped_tool, known_solution["params"]),
                        source="agent_kernel_execute",
                    )
                    if isinstance(retry_result, dict) and retry_result.get("success"):
                        result = retry_result
                        result["_healed"] = True
                        result["_healing_message"] = "Geçmiş deneyimlere dayanarak sorun otomatik giderildi."
                        return result

                if diagnosis:
                    ctx = {"tool_name": mapped_tool, "params": clean_params}
                    plan = await healing_engine.get_healing_plan(diagnosis, err_text, ctx)
                    logger.info(f"Self-Healing: {plan['description']} (Can fix: {plan['can_auto_fix']})")
                    _agent_runtime()._push_tool_event(
                        "update",
                        mapped_tool,
                        step=step_name,
                        request_id=str(getattr(request_record, "request_id", "") or ""),
                        payload={"status": "self_healing_plan", "description": str(plan.get("description") or "")[:180]},
                    )
                    if plan["can_auto_fix"]:
                        if "fix_command" in plan:
                            logger.info(f"Executing healing command: {plan['fix_command']}")
                            import subprocess

                            subprocess.run(plan["fix_command"].split(), check=False)

                        if "wait_time" in plan:
                            logger.info(f"Self-Healing: Waiting {plan['wait_time']} seconds...")
                            await asyncio.sleep(plan["wait_time"])

                        retry_params = plan.get("suggested_params", clean_params)
                        if "suggested_provider" in plan:
                            retry_params["_provider_override"] = plan["suggested_provider"]

                        retry_result = agent._normalize_tool_execution_result(
                            mapped_tool,
                            await agent.kernel.tools.execute(mapped_tool, retry_params),
                            source="agent_kernel_execute",
                        )
                        result = retry_result
                        clean_params = retry_params
                        if isinstance(result, dict) and result.get("success") is False:
                            err_text = str(result.get("error", "") or err_text)
                        else:
                            result["_healed"] = True
                            result["_healing_message"] = plan.get("message", "Hata otomatik giderildi.")
                            try:
                                kb = get_knowledge_base()
                                kb.record_success(
                                    task_type=mapped_tool,
                                    problem=diagnosis.name if diagnosis else "unknown_error",
                                    solution={"params": retry_params},
                                    context={"platform": "mac", "auto_fix": True},
                                )
                            except Exception as kb_err:
                                logger.debug(f"KB record failed: {kb_err}")
                if not result.get("_healed"):
                    repaired_params = agent._repair_tool_params_from_error(
                        mapped_tool,
                        clean_params,
                        error_text=err_text,
                        user_input=user_input,
                        step_name=step_name,
                    )
                    if repaired_params:
                        _agent_runtime()._push_tool_event(
                            "update",
                            mapped_tool,
                            step=step_name,
                            request_id=str(getattr(request_record, "request_id", "") or ""),
                            payload={"status": "deterministic_repair_retry"},
                        )
                        retry_result = agent._normalize_tool_execution_result(
                            mapped_tool,
                            await agent.kernel.tools.execute(mapped_tool, repaired_params),
                            source="agent_kernel_execute",
                        )
                        result = retry_result
                        clean_params = repaired_params
                        if isinstance(result, dict) and result.get("success") is False:
                            err_text = str(result.get("error", "") or err_text)

            result = agent._postprocess_tool_result(mapped_tool, clean_params, result, user_input=user_input)

            if mapped_tool == "set_wallpaper" and isinstance(result, dict) and result.get("success"):
                try:
                    if "take_screenshot" in _available_tools():
                        stamp = int(time.time() * 1000)
                        proof = agent._normalize_tool_execution_result(
                            "take_screenshot",
                            await agent.kernel.tools.execute("take_screenshot", {"filename": f"wallpaper_proof_{stamp}.png"}),
                            source="agent_kernel_execute",
                        )
                        if isinstance(proof, dict) and proof.get("success"):
                            result.setdefault("_proof", {})["screenshot"] = proof.get("path") or proof.get("file_path")
                except Exception:
                    pass

            try:
                if (
                    isinstance(result, dict)
                    and result.get("success")
                    and str(guard.get("risk") or "") in {"guarded", "dangerous"}
                    and bool(getattr(guard.get("profile"), "require_evidence_for_dangerous", False))
                    and bool(runtime_policy)
                    and "take_screenshot" in _available_tools()
                ):
                    proof_map = result.get("_proof", {}) if isinstance(result.get("_proof"), dict) else {}
                    if not proof_map.get("screenshot"):
                        stamp = int(time.time() * 1000)
                        shot = agent._normalize_tool_execution_result(
                            "take_screenshot",
                            await agent.kernel.tools.execute("take_screenshot", {"filename": f"proof_{mapped_tool}_{stamp}.png"}),
                            source="agent_kernel_execute",
                        )
                        if isinstance(shot, dict) and shot.get("success"):
                            result.setdefault("_proof", {})["screenshot"] = shot.get("path") or shot.get("file_path")
            except Exception:
                pass

            if mapped_tool in {"set_wallpaper", "take_screenshot", "analyze_screen", "capture_region"}:
                result = agent._postprocess_tool_result(mapped_tool, clean_params, result, user_input=user_input)

            if isinstance(result, dict) and result.get("verified") is False:
                write_tools = {"write_file", "write_word", "write_excel", "create_web_project_scaffold"}
                if mapped_tool in write_tools and not clean_params.get("_retry_attempted"):
                    logger.warning(f"Verification failed for {mapped_tool}. Retrying operation...")
                    clean_params["_retry_attempted"] = True
                    try:
                        exec_params = {k: v for k, v in clean_params.items() if not k.startswith("_")}
                        retry_res = agent._normalize_tool_execution_result(
                            mapped_tool,
                            await agent.kernel.tools.execute(mapped_tool, exec_params),
                            source="agent_kernel_execute",
                        )
                        result = agent._postprocess_tool_result(mapped_tool, clean_params, retry_res, user_input=user_input)
                        if result.get("verified"):
                            result["_healed"] = True
                            result["_healing_message"] = "Dosya yazma ilk denemede doğrulanamadı, ikinci denemede başarılı oldu."
                    except Exception as exc:
                        logger.error(f"Retry failed for {mapped_tool}: {exc}")

            if isinstance(result, dict) and result.get("_repair_actions") and not clean_params.get("_repair_attempted"):
                repair_actions = result.get("_repair_actions")
                repair_hints = result.get("verification_warning", "")
                logger.info(f"Contract failure for {mapped_tool}. Attempting {len(repair_actions)} repair actions. Hints: {repair_hints}")

                for repair in repair_actions:
                    r_action = repair.get("action")
                    r_params = dict(repair.get("params", {}))
                    r_params["_repair_attempted"] = True
                    r_params["_repair_context"] = {
                        "previous_error": result.get("error", ""),
                        "verification_failure": repair_hints,
                        "failed_reason": repair.get("reason", ""),
                    }

                    try:
                        exec_r_params = {k: v for k, v in r_params.items() if not k.startswith("_")}
                        repair_res = await self.execute(
                            agent,
                            ExecutionRequest(
                                tool_name=r_action,
                                params=exec_r_params,
                                user_input=user_input,
                                step_name=f"Onarım: {r_action}",
                                pipeline_state=pipeline,
                                action_aliases=request.action_aliases,
                            ),
                        )
                        if isinstance(repair_res, dict) and repair_res.get("success"):
                            result = repair_res
                            break
                    except Exception:
                        pass
                if isinstance(result, dict) and result.get("success"):
                    result["_repair_successful"] = True

            try:
                from core.voice.audio_feedback import get_audio_feedback

                audio = get_audio_feedback()
                is_success = not (isinstance(result, dict) and result.get("success") is False)
                if not is_success:
                    audio.play_error()
                else:
                    impactful_prefixes = ("write", "create", "delete", "move", "copy", "run", "execute", "send", "generate")
                    if mapped_tool.startswith(impactful_prefixes) or "screenshot" in mapped_tool:
                        audio.play_success()
            except Exception:
                pass

            if typed_tools_strict:
                try:
                    from core.pipeline_upgrade.executor import validate_tool_io

                    out_gate = validate_tool_io(mapped_tool, clean_params if isinstance(clean_params, dict) else {}, result)
                    if not out_gate.ok:
                        err_text = f"typed_tool_output_rejected:{';'.join(out_gate.errors)}"
                        result = agent._normalize_tool_execution_result(
                            mapped_tool,
                            {"success": False, "status": "failed", "error": err_text},
                            source="agent_kernel_execute",
                            error_code="TOOL_OUTPUT_SCHEMA",
                        )
                except Exception:
                    pass

            success = not (isinstance(result, dict) and result.get("success") is False)
            if success:
                agent._update_file_context_after_tool(mapped_tool, clean_params, result)
                agent._log_data_access_if_needed(uid, mapped_tool, clean_params)
                agent._audit_security_event(
                    uid,
                    f"tool_execute:{mapped_tool}",
                    "ok",
                    params={"tool": mapped_tool, "risk": guard.get("risk"), "approved": bool(requires_approval)},
                    channel=channel,
                )
                pipeline.store(mapped_tool, result)
                if step_name:
                    pipeline.store(step_name, result)
            else:
                result = agent._attach_error_code(result)
                agent._audit_security_event(
                    uid,
                    f"tool_execute_failed:{mapped_tool}",
                    str(result.get("error") if isinstance(result, dict) else "failed"),
                    params={"tool": mapped_tool, "risk": guard.get("risk")},
                    channel=channel,
                )
            return agent._attach_error_code(result)
        except ValueError:
            tool_func = _available_tools().get(mapped_tool)
            if not tool_func:
                resolved = agent._resolve_tool_name(mapped_tool)
                if resolved:
                    used_tool = resolved
                    tool_func = _available_tools().get(resolved)
                    clean_params = agent._prepare_tool_params(resolved, clean_params, user_input=user_input, step_name=step_name)
                if not tool_func:
                    err_text = f"Tool '{mapped_tool}' not found or unavailable."
                    return agent._attach_error_code(
                        agent._normalize_tool_execution_result(
                            mapped_tool,
                            {
                                "success": False,
                                "status": "failed",
                                "error": err_text,
                                "errors": ["UNKNOWN_TOOL"],
                                "data": {"error_code": "UNKNOWN_TOOL"},
                            },
                            source="agent_fallback_lookup",
                            error_code="UNKNOWN_TOOL",
                        )
                    )
            try:
                invoke_params = agent._adapt_params_for_tool_signature(
                    tool_func, mapped_tool, clean_params, user_input=user_input, step_name=step_name
                )
                result = agent._normalize_tool_execution_result(
                    used_tool,
                    await agent._invoke_tool_callable(tool_func, invoke_params),
                    source="agent_fallback_callable",
                )
                if isinstance(result, dict) and result.get("success") is False:
                    err_text = str(result.get("error", "") or "")
                    repaired_params = agent._repair_tool_params_from_error(
                        used_tool,
                        invoke_params,
                        error_text=err_text,
                        user_input=user_input,
                        step_name=step_name,
                    )
                    if repaired_params:
                        result = agent._normalize_tool_execution_result(
                            used_tool,
                            await agent._invoke_tool_callable(tool_func, repaired_params),
                            source="agent_fallback_callable",
                        )
                        invoke_params = repaired_params
                        if isinstance(result, dict) and result.get("success") is False:
                            err_text = str(result.get("error", "") or err_text)
                success = not (isinstance(result, dict) and result.get("success") is False)
                if isinstance(result, dict) and result.get("success") is False:
                    err_text = str(result.get("error", ""))
                result = agent._postprocess_tool_result(used_tool, invoke_params, result, user_input=user_input)
                if typed_tools_strict:
                    try:
                        from core.pipeline_upgrade.executor import validate_tool_io

                        out_gate = validate_tool_io(used_tool, invoke_params if isinstance(invoke_params, dict) else {}, result)
                        if not out_gate.ok:
                            err_text = f"typed_tool_output_rejected:{';'.join(out_gate.errors)}"
                            result = agent._normalize_tool_execution_result(
                                used_tool,
                                {"success": False, "status": "failed", "error": err_text},
                                source="agent_fallback_callable",
                                error_code="TOOL_OUTPUT_SCHEMA",
                            )
                    except Exception:
                        pass
                success = not (isinstance(result, dict) and result.get("success") is False)
                if success:
                    agent._update_file_context_after_tool(used_tool, invoke_params, result)
                return agent._attach_error_code(result)
            except Exception as exc:
                repaired_params = agent._repair_tool_params_from_error(
                    used_tool,
                    invoke_params,
                    error_text=str(exc),
                    user_input=user_input,
                    step_name=step_name,
                )
                if repaired_params:
                    try:
                        result = agent._normalize_tool_execution_result(
                            used_tool,
                            await agent._invoke_tool_callable(tool_func, repaired_params),
                            source="agent_fallback_callable",
                        )
                        success = not (isinstance(result, dict) and result.get("success") is False)
                        if isinstance(result, dict) and result.get("success") is False:
                            err_text = str(result.get("error", ""))
                        result = agent._postprocess_tool_result(used_tool, repaired_params, result, user_input=user_input)
                        if typed_tools_strict:
                            try:
                                from core.pipeline_upgrade.executor import validate_tool_io

                                out_gate = validate_tool_io(used_tool, repaired_params if isinstance(repaired_params, dict) else {}, result)
                                if not out_gate.ok:
                                    err_text = f"typed_tool_output_rejected:{';'.join(out_gate.errors)}"
                                    result = agent._normalize_tool_execution_result(
                                        used_tool,
                                        {"success": False, "status": "failed", "error": err_text},
                                        source="agent_fallback_callable",
                                        error_code="TOOL_OUTPUT_SCHEMA",
                                    )
                            except Exception:
                                pass
                        success = not (isinstance(result, dict) and result.get("success") is False)
                        if success:
                            agent._update_file_context_after_tool(used_tool, repaired_params, result)
                        return agent._attach_error_code(result)
                    except Exception as retry_exc:
                        logger.error(f"Fallback tool retry failed ({mapped_tool}): {retry_exc}")
                        err_text = str(retry_exc)
                        return agent._attach_error_code(
                            agent._normalize_tool_execution_result(
                                used_tool,
                                {"success": False, "status": "failed", "error": str(retry_exc)},
                                source="agent_fallback_callable",
                                error_code="EXECUTION_EXCEPTION",
                            )
                        )
                friendly_error = agent._friendly_missing_argument_error(str(exc), tool_name=used_tool)
                if friendly_error:
                    logger.warning(f"Tool invocation missing param ({used_tool}): {friendly_error}")
                    err_text = friendly_error
                    return agent._attach_error_code(
                        agent._normalize_tool_execution_result(
                            used_tool,
                            {"success": False, "status": "needs_input", "error": friendly_error, "message": friendly_error},
                            source="agent_fallback_callable",
                        )
                    )
                logger.error(f"Fallback tool execution error ({mapped_tool}): {exc}")
                err_text = str(exc)
                return agent._attach_error_code(
                    agent._normalize_tool_execution_result(
                        used_tool,
                        {"success": False, "status": "failed", "error": str(exc)},
                        source="agent_fallback_callable",
                        error_code="EXECUTION_EXCEPTION",
                    )
                )
        except asyncio.TimeoutError:
            err_text = f"Tool '{mapped_tool}' timed out"
            logger.warning(f"[timeout_guard] {err_text}")
            return agent._attach_error_code(
                agent._normalize_tool_execution_result(
                    mapped_tool,
                    {
                        "success": False,
                        "status": "failed",
                        "error": friendly_timeout_message(mapped_tool),
                        "errors": ["TIMEOUT"],
                        "data": {"error_code": "TIMEOUT"},
                    },
                    source="agent_execute_tool",
                    error_code="TIMEOUT",
                )
            )
        except Exception as exc:
            err_text = str(exc)
            logger.error(f"Tool execution error ({mapped_tool}): {exc}")
            return agent._attach_error_code(
                agent._normalize_tool_execution_result(
                    mapped_tool,
                    {
                        "success": False,
                        "status": "failed",
                        "error": str(exc),
                        "errors": ["EXECUTION_EXCEPTION"],
                        "data": {"error_code": "EXECUTION_EXCEPTION", "exception_type": type(exc).__name__},
                    },
                    source="agent_execute_tool",
                    error_code="EXECUTION_EXCEPTION",
                )
            )
        finally:
            latency = int((time.perf_counter() - start) * 1000)
            final_result = locals().get("result", {})
            record_tool_usage(used_tool, success=success, latency_ms=latency, source="agent", error=err_text)
            try:
                if runtime_facade is not None:
                    runtime_facade.record_tool_outcome(task_category, used_tool, success, latency)
                    if success:
                        runtime_facade.uncertainty_engine.update_belief(used_tool, "success", 0.9)
                    else:
                        runtime_facade.uncertainty_engine.update_belief(used_tool, "failure", 0.1)
            except Exception:
                pass
            try:
                request_log.finish_request(
                    request_record,
                    final_result,
                    latency_ms=latency,
                    success=success,
                    error=err_text,
                )
            except Exception:
                pass
            try:
                suppress = agent._suppress_duplicate_confirmation(used_tool, final_result, success)
                if not suppress:
                    _agent_runtime()._push_tool_event(
                        "end",
                        str(used_tool or mapped_tool or tool_name),
                        step=step_name,
                        request_id=str(getattr(request_record, "request_id", "") or ""),
                        success=bool(success),
                        latency_ms=latency,
                        payload=agent._tool_event_preview(final_result),
                    )
                else:
                    _agent_runtime()._push_tool_event(
                        "update",
                        str(used_tool or mapped_tool or tool_name),
                        step=step_name,
                        request_id=str(getattr(request_record, "request_id", "") or ""),
                        payload={"status": "duplicate_confirmation_suppressed"},
                    )
            except Exception:
                pass
            try:
                ledger = _agent_runtime()._active_ledger.get()
                if ledger is not None:
                    ledger.log_step(
                        step=str(step_name or used_tool or tool_name),
                        tool=str(used_tool or mapped_tool or tool_name),
                        status="success" if success else "failed",
                        input_payload={"user_input": user_input, "step_name": step_name},
                        params=clean_params,
                        result=final_result,
                        duration_ms=latency,
                    )
            except Exception:
                pass
            try:
                if agent.learning:
                    hint_error = ""
                    if not success:
                        hint_error = str(err_text or "").strip()
                        if not hint_error and isinstance(final_result, dict) and final_result.get("success") is False:
                            hint_error = str(final_result.get("error", "") or "").strip()
                    if success or hint_error:
                        hint = agent.learning.generate_smart_hint(last_error=hint_error or None)
                        if hint:
                            if hint_error:
                                _agent_runtime()._push_hint(hint, icon="triangle-alert", color="orange")
                            else:
                                _agent_runtime()._push_hint(hint, icon="lightbulb", color="blue")
            except Exception:
                pass


_tool_runtime_executor: ToolRuntimeExecutor | None = None


def get_tool_runtime_executor() -> ToolRuntimeExecutor:
    global _tool_runtime_executor
    if _tool_runtime_executor is None:
        _tool_runtime_executor = ToolRuntimeExecutor()
    return _tool_runtime_executor
