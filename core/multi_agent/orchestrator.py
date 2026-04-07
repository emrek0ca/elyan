"""
core/multi_agent/orchestrator.py
─────────────────────────────────────────────────────────────────────────────
Industrial Grade Orchestrator v3.
Implements: Determinism, Surgical Fixes (Patching), Layered QA.
"""

from __future__ import annotations
import asyncio
import time
import re
import json
import os
import shlex
from pathlib import Path
from typing import List, Dict, Any, Optional
from utils.logger import get_logger

from .specialists import get_specialist_registry
from .contract import DeliverableContract, Artifact
from .qa_pipeline import QAPipeline
from .job_templates import get_template, detect_template_key
from core.artifact_quality_engine import quality_engine
from core.memory_v2 import memory_v2
from core.action_lock import action_lock
from core.timeout_guard import with_timeout, STEP_TIMEOUT
from core.reasoning.trace_logger import trace_logger
from core.capability_router import get_capability_router
from core.event_system import EventPriority, get_event_bus
from config.elyan_config import elyan_config
from core.elyan_runtime import get_elyan_runtime
from core.multi_agent.contract_net import TaskAnnouncement
from core.multi_agent.orchestrator_bridge import get_orchestrator_bridge

logger = get_logger("multi_agent.orchestrator")

class AgentOrchestrator:
    def __init__(self, agent_instance):
        self.main_agent = agent_instance
        self.registry = get_specialist_registry()
        self.qa_pipeline = QAPipeline(agent_instance)
        self.team_roster: list[dict[str, str]] = []

    async def _emit_event(self, event_type: str, payload: dict[str, Any], *, priority: EventPriority = EventPriority.NORMAL) -> None:
        payload = dict(payload or {})
        correlation_id = str(
            payload.get("job_id")
            or payload.get("run_id")
            or payload.get("session_id")
            or payload.get("template_id")
            or event_type
        )
        causation_id = str(
            payload.get("parent_job_id")
            or payload.get("parent_run_id")
            or payload.get("causation_id")
            or correlation_id
        )
        idempotency_key = str(payload.get("idempotency_key") or f"{event_type}:{correlation_id}")
        try:
            await get_event_bus().publish(
                event_type=event_type,
                data=payload,
                priority=priority,
                source="multi_agent.orchestrator",
                tags={"multi_agent", "orchestrator"},
                metadata={"orchestrator": True},
                schema_version=1,
                correlation_id=correlation_id,
                causation_id=causation_id,
                idempotency_key=idempotency_key,
            )
        except Exception:
            logger.debug("Orchestrator event publish skipped", exc_info=True)

    @staticmethod
    def _specialist_role_key(key: str) -> str:
        token = str(key or "").strip().lower()
        mapping = {
            "lead": "planning",
            "pm_agent": "planning",
            "researcher": "research_worker",
            "research_agent": "research_worker",
            "builder": "code",
            "code_agent": "code_worker",
            "executor": "code_worker",
            "coder": "code_worker",
            "document_agent": "creative",
            "thinking_agent": "reasoning",
            "ops": "worker",
            "tool_runner": "worker",
            "qa": "qa",
            "qa_expert": "qa",
            "communicator": "creative",
        }
        return mapping.get(token, "reasoning")

    async def manage_flow(self, plan: Any, original_input: str) -> str:
        """
        Industrial Loop: Reason -> Plan -> Surgical Execute -> Layered Verify
        """
        job_id = f"job_{int(time.time())}"
        start_time = time.time()
        self._bridge = get_orchestrator_bridge()
        await self._emit_event(
            "orchestrator.flow_started",
            {"job_id": job_id, "input": str(original_input or "")[:300]},
            priority=EventPriority.HIGH,
        )

        # 1. Template selection + capability-aware routing
        cap_plan = None
        try:
            cap_plan = get_capability_router().route(original_input)
        except Exception:
            cap_plan = None

        template_key = detect_template_key(original_input)
        if cap_plan:
            if cap_plan.domain == "website":
                template_key = "web_site_job"
            elif cap_plan.domain in {"code", "full_stack_delivery"}:
                template_key = "code_delivery_job"
            elif cap_plan.domain == "api_integration":
                template_key = "api_integration_job"
            elif cap_plan.domain == "automation":
                template_key = "automation_job"
            elif cap_plan.domain in {"research", "document", "summarization"}:
                template_key = "research_report_job"

        template = get_template(template_key)
        await self._emit_event(
            "orchestrator.template_selected",
            {"job_id": job_id, "template_id": template.id, "template_name": template.name},
        )
        self.team_roster = self._build_team_roster(template.id, cap_plan)
        try:
            if self.team_roster:
                trace_logger.push_trace("Team", json.dumps(self.team_roster, ensure_ascii=False))
        except Exception:
            pass

        await self._bridge.on_job_started(job_id, template.id, original_input)

        workspace_dir = self._derive_workspace_dir(job_id, template.id, original_input)
        plan_hint = self._compact_plan_hint(plan)
        
        lock_result = action_lock.request_lock(
            job_id,
            f"Think-Factory Job: {template.name}",
            policy_scope=f"deliverable:{template.id}",
            conflict_key=template.id,
            owner="multi_agent.orchestrator",
            metadata={"template_id": template.id, "input": str(original_input or "")[:200]},
        )
        if not lock_result.get("acquired", False):
            await self._emit_event(
                "orchestrator.flow_blocked",
                {"job_id": job_id, "template_id": template.id, "reason": lock_result.get("reason", "action_locked")},
                priority=EventPriority.HIGH,
            )
            return f"⏳ Başka bir üretim akışı çalışıyor. {template.name} için çalışma kuyruğa alındı."
        context = memory_v2.get_context_for_intent(original_input)
        
        from core.multi_agent.budget import BudgetTracker, BudgetExceededError
        self.budget_tracker = BudgetTracker(max_tokens=template.max_tokens, max_usd=template.max_usd)
        
        try:
            # --- Phase 0: DEEP REASONING (The 'Think' Step) ---
            action_lock.update_status(0.05, "Brainstorming: En iyi çözüm yolu aranıyor...")
            await self._emit_event("orchestrator.phase_started", {"job_id": job_id, "phase": "reason", "template_id": template.id})
            
            # Select Workflow Chain
            chain_key = self._workflow_for_template(template.id)
            workflow = self.registry.get_chain(chain_key)
            if workflow:
                logger.info(f"Orchestrator: Using workflow chain '{workflow.name}'")

            reason_prompt = (
                f"Girdi: {original_input}. Bu iş için en verimli stratejiyi düşün. "
                f"Riskleri ve asset ihtiyaçlarını belirle. Template: {template.id}."
            )
            if plan_hint:
                reason_prompt += f"\nPipeline Plan Hint: {plan_hint}"
            # Use lead agent for initial reasoning
            brainstorm_raw = await self._run_specialist("lead", reason_prompt)
            self._log_thought("Planner", brainstorm_raw)

            # --- Phase 1: PLAN ---
            action_lock.update_status(0.1, "Planner: Teknik Sözleşme Hazırlanıyor...")
            plan_prompt = (
                f"Strateji: {brainstorm_raw}\n"
                f"Girdi: {original_input}. Template: {template.id}. "
                "Sözleşmeyi JSON formatında planla."
            )
            if plan_hint:
                plan_prompt += f"\nPipeline Plan Hint: {plan_hint}"
            plan_raw = await self._run_specialist("lead", plan_prompt)
            plan_data = self._safe_parse_json(plan_raw)
            await self._emit_event(
                "orchestrator.plan_parsed",
                {"job_id": job_id, "template_id": template.id, "step_count": len(plan_data) if isinstance(plan_data, list) else 0},
            )

            contract = DeliverableContract(job_id=job_id, goal=original_input, job_type=template.id)
            await self.main_agent._execute_tool("create_folder", {"path": workspace_dir})

            from core.deterministic_runner import DeterministicToolRunner, ExecutionPlan
            from core.multi_agent.rollback import RollbackManager
        
            rollback_mgr = RollbackManager(workspace_dir)
            await rollback_mgr.ensure_initialized()
            initial_snapshot = await rollback_mgr.create_snapshot()

            # --- Phase 2: EXECUTE (Build & Patch) ---
            await self._emit_event("orchestrator.phase_started", {"job_id": job_id, "phase": "execute", "template_id": template.id})
            for i in range(3): # Max 3 Revision loops
                iter_label = f"(Rev {i+1})"
                action_lock.update_status(0.2 + (i * 0.2), f"Builder: Üretim {iter_label}...")
            
                schema = DeliverableContract.get_contract_schema()
                execution_schema = {
                    "type": "object",
                    "properties": {
                        "artifact_map": schema,
                        "execution_plan": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "action": {"type": "string"},
                                    "params": {"type": "object"},
                                    "preconditions": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {"type": {"type": "string"}, "path": {"type": "string"}, "value": {"type": "string"}}
                                        }
                                    },
                                    "postconditions": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {"type": {"type": "string"}, "path": {"type": "string"}, "value": {"type": "string"}}
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "required": ["artifact_map", "execution_plan"]
                }

                build_prompt = (
                    f"Hedef: {original_input}. Plan: {plan_data}.\n"
                    f"LÜTFEN ÇIKTIYI AŞAĞIDAKİ JSON ŞEMASINA (%100 UYUMLU) GÖRE DÖNDÜR:\n"
                    f"{json.dumps(execution_schema, indent=2)}\n"
                    f"Bu bir State Machine Execution Plan'dir. 'execution_plan' arrayi içindeki her adım idempotent olmalıdır."
                )
                build_prompt += (
                    f"\nTemplate ID: {template.id}\n"
                    f"Workspace: {workspace_dir}\n"
                    f"Zorunlu artifacts: {template.mandatory_artifacts}\n"
                )
                if plan_hint:
                    build_prompt += f"Pipeline Plan Hint: {plan_hint}\n"
                if contract.artifacts:
                    issues = [f"{a.path}: {a.errors}" for a in contract.artifacts.values() if a.errors]
                    build_prompt += f"\n\nDERİN DÜŞÜN: Önceki hataları analiz et ve repair/patch (cerrahi çözüm) adımları içeren yeni bir execution plan üret: {issues}"

                build_raw = await self._run_specialist("executor", build_prompt)
                self._log_thought("Builder", build_raw)
            
                # Extract JSON and execute
                try:
                    payload = None
                    match = re.search(r"\{.*\}", build_raw, re.DOTALL)
                    if match:
                        payload = json.loads(match.group(0))

                    if not isinstance(payload, dict):
                        payload = self._build_fallback_execution_payload(
                            template_id=template.id,
                            original_input=original_input,
                            workspace_dir=workspace_dir,
                            plan_hint=plan_hint,
                        )
                        logger.warning("Builder JSON parse failed. Using deterministic fallback payload.")

                    # 1. Register Artifacts from Map
                    art_map = payload.get("artifact_map", {})
                    if "artifacts" in art_map:
                        for art in art_map["artifacts"]:
                            path = art.get("path", "")
                            content = art.get("content", "")
                            mime = art.get("mime", "text/plain")
                            if path and content:
                                contract.add_artifact(
                                    path=path, type=art.get("type", "code"), content=content, mime=mime,
                                    required_sections=art.get("required_sections", []),
                                    min_size_bytes=art.get("min_size_bytes", 0),
                                    asset_source=art.get("asset_source", "local"),
                                    encoding=art.get("encoding", "utf-8"), line_endings=art.get("line_endings", "LF")
                                )

                    # 2. Run Deterministic Execution Plan
                    plan_data = payload.get("execution_plan", [])
                    if not isinstance(plan_data, list) or not plan_data:
                        payload = self._build_fallback_execution_payload(
                            template_id=template.id,
                            original_input=original_input,
                            workspace_dir=workspace_dir,
                            plan_hint=plan_hint,
                        )
                        plan_data = payload.get("execution_plan", [])
                        logger.warning("Execution plan missing/empty. Applied deterministic fallback steps.")

                    plan_data = self._attach_owners(plan_data)
                    try:
                        await self._emit_event(
                            "orchestrator.parallel_warmup_started",
                            {"job_id": job_id, "template_id": template.id, "step_count": len(plan_data)},
                        )
                        await self._warm_up_parallel_sub_agents(job_id, plan_data, original_input)
                    except Exception as warm_exc:
                        logger.debug(f"Sub-agent warmup skipped: {warm_exc}")
                    exec_plan = ExecutionPlan.from_dict({"job_id": job_id, "steps": plan_data})
                    runner = DeterministicToolRunner(self.main_agent)
                
                    action_lock.update_status(0.4 + (i * 0.2), f"Runner: Adımlar İşleniyor {iter_label}")
                
                    step_snapshot = await rollback_mgr.create_snapshot()
                    run_result = await runner.execute_plan(exec_plan)
                    if not run_result["success"]:
                        logger.error(f"Deterministic logic failed: {run_result}. Self-healing via Rollback...")
                        await rollback_mgr.restore_snapshot(step_snapshot)
                    else:
                        await rollback_mgr.clear_snapshot(step_snapshot)
                except Exception as e:
                    logger.warning(f"Failed to parse and execute Deterministic Plan JSON: {e}")
                    payload = self._build_fallback_execution_payload(
                        template_id=template.id,
                        original_input=original_input,
                        workspace_dir=workspace_dir,
                        plan_hint=plan_hint,
                    )
                    try:
                        exec_plan = ExecutionPlan.from_dict({"job_id": job_id, "steps": payload.get("execution_plan", [])})
                        runner = DeterministicToolRunner(self.main_agent)
                        step_snapshot = await rollback_mgr.create_snapshot()
                        run_result = await runner.execute_plan(exec_plan)
                        if not run_result.get("success"):
                            await rollback_mgr.restore_snapshot(step_snapshot)
                        else:
                            await rollback_mgr.clear_snapshot(step_snapshot)
                    except Exception as fallback_exc:
                        logger.error(f"Fallback deterministic execution failed: {fallback_exc}")

                # --- Phase 3: VERIFY (Swarm Consensus) ---
                action_lock.update_status(0.7, "Validator: Swarm Consensus Debate...")
                await self._emit_event("orchestrator.phase_started", {"job_id": job_id, "phase": "verify", "template_id": template.id})
            
                # Layered Swarm QA (Security, Performance, UX)
                from core.multi_agent.swarm_consensus import SwarmConsensus
                tribunal = SwarmConsensus(self.main_agent)
                passed, issues = await tribunal.run_tribunal_debate(original_input, contract.artifacts)
                
                # Update integrity (Static/Syntax) for metrics
                passed_static, static_issues = await self.qa_pipeline.run_full_audit(workspace_dir, contract.artifacts)
                issues.extend(static_issues)
                if not passed_static: passed = False
            
                for artifact in contract.artifacts.values():
                    quality_engine.verify_integrity(artifact, workspace_dir)
            
                quality_engine.calculate_metrics(contract)
            
                if passed:
                    # Success!
                    quality_engine.create_audit_bundle(contract, workspace_dir)
                
                    # Packaging
                    zip_path = f"{workspace_dir}.zip"
                    await self.main_agent._execute_tool(
                        "run_safe_command",
                        {"command": f"cd {shlex.quote(workspace_dir)} && zip -r {shlex.quote(zip_path)} ."},
                    )
                
                    await rollback_mgr.clear_snapshot(initial_snapshot)
                    
                    # Semantic Golden Recipe Learning
                    if contract.metrics and contract.metrics.task_success_rate >= 1.0:
                        from core.multi_agent.golden_memory import golden_memory
                        await golden_memory.save_recipe(
                            intent=original_input, 
                            template_id=template.id, 
                            audit_zip=zip_path, 
                            duration_s=contract.metrics.duration_s,
                            agent=self.main_agent
                        )
                        
                    action_lock.update_status(1.0, "Görev Onaylandı ve Paketlendi!")
                    await self._bridge.on_job_completed(job_id, {"zip": zip_path})
                    action_lock.unlock(reason="completed")
                    await self._emit_event(
                        "orchestrator.flow_completed",
                        {"job_id": job_id, "template_id": template.id, "success": True, "duration_s": round(time.time() - start_time, 2)},
                        priority=EventPriority.HIGH,
                    )
                
                    return (f"✅ İŞ BAŞARIYLA TESLİM EDİLDİ\n\n"
                            f"Job ID: {job_id}\n"
                            f"Tamamlanma: %{contract.metrics.output_completeness}\n"
                            f"Audit Bundle: {contract.audit_bundle_path}\n"
                            f"Paket (ZIP): {zip_path}")
                else:
                    # Reset errors for artifacts and record new ones
                    for a in contract.artifacts.values(): a.errors = []
                    for issue in issues:
                        logger.warning(f"QA Fail: {issue}")
                        for path in contract.artifacts:
                            if path in issue: contract.artifacts[path].errors.append(issue)

                        # Self-Coding Meta-Loop
                        if "ToolNotFound" in issue or "Eksik Yetenek" in issue:
                            from core.multi_agent.tool_governance import ToolGovernance
                            governance = ToolGovernance(self.main_agent)
                            missing_tool = await self._run_specialist("pm_agent", f"Şu hataya göre eksik aracın adını ve amacını tek cümle yaz: {issue}")
                            logger.info(f"Yetenek eksikliği tespit edildi: {missing_tool}. Kendi kendine yazma denenecek...")
                            
                            success = await governance.author_and_inject_tool(missing_tool, f"dynamic_tool_{job_id[:4]}")
                            if success:
                                action_lock.update_status(0.8, "Eksik yetenek kodlandı ve sisteme entegre edildi!")
                                issues.append("Yeni araç yazıldı. Bir sonraki revizyonda planı tekrar dene.")
                
                    # If no artifacts at all, specifically tell the builder
                    if not contract.artifacts:
                        logger.warning("No artifacts detected after QA fail; forcing deterministic fallback on next revision.")

            await rollback_mgr.restore_snapshot(initial_snapshot)
            await self._bridge.on_job_failed(job_id, f"qa_failed: {len(issues)} issues")
            action_lock.unlock(reason="qa_failed")
            await self._emit_event(
                "orchestrator.flow_failed",
                {"job_id": job_id, "template_id": template.id, "reason": "qa_failed", "issues": issues[:12]},
                priority=EventPriority.HIGH,
            )
            return f"❌ GÖREV BAŞARISIZ (QA Onayı Alınamadı: {job_id})\n\nSon Hatalar: {issues}"
        
        except BudgetExceededError as e:
            await getattr(rollback_mgr, 'restore_snapshot')(initial_snapshot) if 'rollback_mgr' in locals() else None
            await self._bridge.on_job_failed(job_id, f"budget_exceeded: {e}")
            action_lock.unlock(reason="budget_exceeded")
            await self._emit_event(
                "orchestrator.flow_failed",
                {"job_id": job_id, "template_id": template.id, "reason": "budget_exceeded", "error": str(e)},
                priority=EventPriority.HIGH,
            )
            logger.error(f"Budget break: {e}")
            return f"🛑 BÜTÇE/TOKEN LİMİTİ AŞILDI: {e}\n{self.budget_tracker.get_status()}"
        except Exception as e:
            try:
                if 'rollback_mgr' in locals():
                    await rollback_mgr.restore_snapshot(initial_snapshot)
            except Exception:
                logger.debug("Unexpected orchestrator failure rollback skipped", exc_info=True)
            await self._bridge.on_job_failed(job_id, f"unexpected_error: {e}")
            action_lock.unlock(reason="unexpected_error")
            await self._emit_event(
                "orchestrator.flow_failed",
                {"job_id": job_id, "template_id": template.id, "reason": "unexpected_error", "error": str(e)},
                priority=EventPriority.HIGH,
            )
            logger.exception(f"Unexpected orchestrator failure: {e}")
            return f"❌ GÖREV BEKLENMEYEN HATA İLE DURDU: {e}"

    async def _apply_production_logic(self, raw_text: str, workspace: str, contract: DeliverableContract):
        """Builder çıktısını analiz eder: Yama mı yoksa Full Dosya mı?"""
        # 1. Patch tespiti (Fallback or intentional injection)
        patches = re.findall(r"PATCH:\s*`?([^\n`]+)`?\nSEARCH:\n```\n(.*?)\n```\nREPLACE:\n```\n(.*?)\n```", raw_text, re.DOTALL)
        if patches:
            for path, search, replace in patches:
                full_path = f"{workspace}{path.strip()}"
                await self.main_agent._execute_tool("apply_patch", {"path": full_path, "search_text": search, "replacement_text": replace})
            return

        # 2. Try parsing Artifact Map JSON
        parsed_json = False
        try:
            match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if match:
                artifact_map = json.loads(match.group(0))
                if "artifacts" in artifact_map:
                    for art in artifact_map["artifacts"]:
                        path = art.get("path", "")
                        content = art.get("content", "")
                        mime = art.get("mime", "text/plain")
                        if path and content:
                            contract.add_artifact(
                                path=path, 
                                type=art.get("type", "code"), 
                                content=content, 
                                mime=mime,
                                required_sections=art.get("required_sections", []),
                                min_size_bytes=art.get("min_size_bytes", 0),
                                asset_source=art.get("asset_source", "local"),
                                encoding=art.get("encoding", "utf-8"),
                                line_endings=art.get("line_endings", "LF")
                            )
                            full_path = f"{workspace}{path}"
                            folder = os.path.dirname(full_path)
                            if folder:
                                await self.main_agent._execute_tool("create_folder", {"path": folder})
                            await self.main_agent._execute_tool("write_file", {"path": full_path, "content": content})
                    parsed_json = True
        except Exception as e:
            logger.warning(f"Failed to parse Artifact Map JSON: {e}")

        # 3. File Block tespiti (Fallback if JSON parsing failed)
        if not parsed_json:
            file_blocks = re.findall(r"(?:\[FILE:\s*|### File:\s*|-\s+|FILE:\s*)`?(/[a-zA-Z0-9_\-\./]+)`?\]?\n\s*```[a-z]*\n(.*?)\n\s*```", raw_text, re.DOTALL)
            
            if not file_blocks:
                single_block = re.search(r"```[a-z]*\n(.*?)\n\s*```", raw_text, re.DOTALL)
                if single_block:
                    file_blocks = [("/index.html", single_block.group(1))]

            for path, content in file_blocks:
                clean_path = path.strip()
                mime = "text/html" if clean_path.endswith(".html") else "text/plain"
                contract.add_artifact(clean_path, type="code", content=content, mime=mime)
                
                full_path = f"{workspace}{clean_path}"
                folder = os.path.dirname(full_path)
                if folder:
                    await self.main_agent._execute_tool("create_folder", {"path": folder})
                
                await self.main_agent._execute_tool("write_file", {"path": full_path, "content": content})

    def _log_thought(self, agent_name: str, raw_text: str, model: Optional[str] = None):
        """Extract and log the thought block for transparency."""
        thought = trace_logger.extract_thought(raw_text)
        if thought:
            trace_logger.push_trace(agent_name, thought, model)

    async def _run_specialist(self, key: str, prompt: str) -> str:
        specialist = self.registry.get(key)
        final_prompt = f"ROLÜN: {specialist.system_prompt}\n\nİSTEK: {prompt}"
        role_key = self._specialist_role_key(key)
        if hasattr(self, "budget_tracker"):
            self.budget_tracker.consume(input_tokens=(len(final_prompt) // 4), output_tokens=0)

        # Bridge: track specialist invocation
        bridge = getattr(self, "_bridge", None)
        job_id = getattr(self, "_current_job_id", "")
        child_task_id = None
        if bridge:
            child_task_id = await bridge.on_specialist_called(job_id, key, prompt[:200])

        t0 = time.time()

        async def _invoke_llm():
            runtime = get_elyan_runtime()
            gateway = getattr(runtime, "model_gateway", None)
            try:
                if gateway is not None:
                    return await gateway.generate_text(
                        self.main_agent.llm,
                        final_prompt,
                        specialist_key=key,
                        role=role_key,
                        user_id="system",
                        explicit_model=str(getattr(specialist, "preferred_model", "") or ""),
                    )
                return await self.main_agent.llm.generate(final_prompt, role=role_key, user_id="system")
            except TypeError:
                return await self.main_agent.llm.generate(final_prompt, role=role_key, user_id="system")

        result = await with_timeout(
            _invoke_llm(),
            seconds=STEP_TIMEOUT,
            fallback=f'{{"outputs": ["Hata: {specialist.name} zaman aşımı"], "risks": ["Timeout"]}}',
            context=f"factory:{key}"
        )

        latency_ms = (time.time() - t0) * 1000
        if bridge and child_task_id:
            await bridge.on_specialist_completed(
                child_task_id, key, success=True, latency_ms=latency_ms,
                model_used=str(getattr(specialist, "preferred_model", "") or ""),
            )

        if hasattr(self, "budget_tracker"):
            self.budget_tracker.consume(input_tokens=0, output_tokens=(len(result) // 4))

        return result

    def _safe_parse_json(self, text: str) -> Dict[str, Any]:
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            return json.loads(match.group(0)) if match else {"outputs": [text]}
        except:
            return {"outputs": [text], "risks": ["Parse Error"]}

    def _derive_workspace_dir(self, job_id: str, template_id: str, original_input: str) -> str:
        """Build a deterministic, user-visible workspace path."""
        base_root = str(elyan_config.get("agent.multi_agent.output_root", "~/Desktop") or "~/Desktop")
        base = Path(base_root).expanduser()

        raw = str(original_input or "").lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
        if not slug:
            slug = str(template_id or "job").lower().replace("_", "-")
        slug = slug[:42].strip("-") or "job"

        workspace = base / f"{slug}-{job_id[-6:]}"
        return str(workspace)

    def _compact_plan_hint(self, plan: Any) -> str:
        """Compact pipeline plan into a short textual hint for specialists."""
        if not plan:
            return ""
        if isinstance(plan, dict):
            plan = [plan]
        if not isinstance(plan, list):
            text = str(plan).strip()
            return text[:500]

        parts: List[str] = []
        for idx, step in enumerate(plan[:8], start=1):
            if isinstance(step, dict):
                title = str(
                    step.get("title")
                    or step.get("name")
                    or step.get("description")
                    or f"step_{idx}"
                ).strip()
                action = str(step.get("action") or "task").strip()
                deps = step.get("depends_on") or step.get("dependencies") or []
                if isinstance(deps, str):
                    deps = [deps]
                dep_txt = ", ".join(str(d).strip() for d in deps[:3] if str(d).strip())
                row = f"{idx}. {title} [{action}]"
                if dep_txt:
                    row += f" <- {dep_txt}"
            else:
                row = f"{idx}. {str(step).strip()}"
            parts.append(row[:140])
        return "\n".join(parts)[:900]

    def _workflow_for_template(self, template_id: str) -> str:
        key = str(template_id or "").strip().lower()
        if key in {"research_report_job"}:
            return "RESEARCH_WORKFLOW"
        if key in {"web_site_job", "code_delivery_job", "api_integration_job", "automation_job"}:
            return "CODING_WORKFLOW"
        return "FIX_WORKFLOW"

    def _build_team_roster(self, template_id: str, cap_plan: Any) -> list[dict[str, str]]:
        roster: list[dict[str, str]] = []
        chain_key = self._workflow_for_template(template_id)
        chain = self.registry.get_chain(chain_key)
        domain = getattr(cap_plan, "domain", "") if cap_plan else ""
        if chain:
            for key in chain.steps:
                spec = self.registry.get(key)
                if not spec:
                    continue
                roster.append(
                    {
                        "id": key,
                        "role": spec.role,
                        "domain": spec.domain,
                        "model": spec.preferred_model,
                        "emoji": spec.emoji,
                        "cap_domain": domain,
                    }
                )
        return roster

    def _assign_owner(self, action: str) -> str:
        low = str(action or "").lower()
        if any(k in low for k in ("research", "search", "analyze", "report")):
            return "researcher"
        if any(k in low for k in ("write", "create", "build", "generate", "code", "scaffold")):
            return "builder"
        if any(k in low for k in ("list", "read", "delete", "move", "copy", "rename", "run_safe_command", "open_app", "set_wallpaper")):
            return "ops"
        if any(k in low for k in ("verify", "qa", "test", "lint")):
            return "qa"
        return "lead"

    def _attach_owners(self, plan_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        patched = []
        for step in plan_data or []:
            s = dict(step or {})
            if not s.get("owner"):
                s["owner"] = self._assign_owner(s.get("action", ""))
            patched.append(s)
        return patched

    @staticmethod
    def _contract_agent_to_specialist(agent_id: str) -> str:
        token = str(agent_id or "").strip().lower()
        mapping = {
            "research_agent": "research_agent",
            "vision_agent": "ops",
            "planning_agent": "thinking_agent",
            "code_agent": "code_agent",
            "document_agent": "document_agent",
            "thinking_agent": "thinking_agent",
            "approval_agent": "qa",
        }
        return mapping.get(token, "worker")

    async def _warm_up_parallel_sub_agents(self, job_id: str, plan_data: list[dict[str, Any]], original_input: str) -> None:
        """
        Lightweight DAG warmup: run independent specialist reasoning in parallel.
        This does not mutate deterministic execution plan output; it enriches context.
        """
        runtime = get_elyan_runtime()
        contract_net = runtime.contract_net
        world_model = runtime.world_model
        candidates: list[tuple[str, Any, str]] = []
        for step in list(plan_data or []):
            owner = str(step.get("owner") or "").strip().lower()
            action = str(step.get("action") or "").strip()
            pre = step.get("preconditions")
            if not owner or owner in {"lead", "communicator"}:
                continue
            if isinstance(pre, list) and pre:
                continue
            if not action:
                continue
            task_id = f"{job_id}:{str(step.get('id') or action or 'step')}"
            required = contract_net.infer_required_capabilities(action, owner=owner, params=step.get("params") if isinstance(step.get("params"), dict) else {})
            announcement = TaskAnnouncement(
                task_id=task_id,
                description=str(step.get("description") or action or step.get("id") or "step"),
                required_capabilities=required,
                deadline_ms=120000,
                priority=3 if owner == "researcher" else 2,
            )
            agent_id = None
            try:
                agent_id = await contract_net.allocate_task(announcement)
            except Exception as alloc_exc:
                logger.debug(f"Contract net allocation skipped: {alloc_exc}")
            selected_owner = self._contract_agent_to_specialist(agent_id) if agent_id else owner
            candidates.append((selected_owner, step, agent_id or ""))
            if len(candidates) >= 3:
                break

        if not candidates:
            return

        from core.sub_agent import SubAgentManager, SubAgentTask

        manager = SubAgentManager(self.main_agent, parent_session_id="orchestrator")
        jobs = []
        for owner, step, _agent_id in candidates:
            action = str(step.get("action") or "").strip()
            params = step.get("params") if isinstance(step.get("params"), dict) else {}
            jobs.append(
                (
                    owner,
                    SubAgentTask(
                        name=str(step.get("id") or action or "step"),
                        action="chat",
                        params={
                            "message": (
                                f"Görev adımı hazırlığı yap. Action={action}, Params={params}, "
                                f"UserGoal={original_input}"
                            )
                        },
                        description=str(step.get("id") or action or "step"),
                        domain=owner,
                    ),
                )
            )

        results = await manager.spawn_parallel(jobs, timeout=90)

        # Broadcast successful results to the agent bus for inter-agent communication
        try:
            from core.sub_agent import get_agent_bus
            bus = get_agent_bus()
            for (owner, step, _agent_id), result in zip(candidates, results):
                if result.status == "completed":
                    from core.sub_agent.shared_state import TeamMessage
                    msg = TeamMessage(
                        from_agent=f"orchestrator:{owner}",
                        to_agent="*",  # Broadcast to all agents
                        body=f"Step {step.get('id')} completed successfully",
                        payload={
                            "step_id": step.get("id"),
                            "owner": owner,
                            "result": result.result if isinstance(result.result, dict) else {},
                        }
                    )
                    await bus.broadcast(f"orchestrator:{owner}", msg)
        except Exception as e:
            logger.debug(f"Failed to broadcast results to agent bus: {e}")

        for (owner, step, agent_id), result in zip(candidates, results):
            step.setdefault("_sub_agent", {})
            step_id = str(step.get("id") or step.get("action") or "step")
            payload = result.result if isinstance(result.result, dict) else {}
            quality_summary = payload.get("quality_summary") if isinstance(payload, dict) and isinstance(payload.get("quality_summary"), dict) else {}
            step["_sub_agent"].update(
                {
                    "owner": owner,
                    "agent_id": agent_id,
                    "status": result.status,
                    "notes": list(result.notes or []),
                    "failed_gates": list(payload.get("failed_gates") or []) if isinstance(payload, dict) else [],
                    "quality_summary": dict(quality_summary or {}),
                    "claim_map_path": str(payload.get("claim_map_path") or "") if isinstance(payload, dict) else "",
                    "revision_summary_path": str(payload.get("revision_summary_path") or "") if isinstance(payload, dict) else "",
                }
            )
            try:
                fact_id = f"job.{job_id}.{step_id}"
                await world_model.assert_fact(
                    fact_id,
                    {
                        "step_id": step_id,
                        "owner": owner,
                        "agent_id": agent_id,
                        "status": result.status,
                        "result": payload,
                    },
                    confidence=0.88 if result.status == "completed" else 0.5,
                    source="orchestrator",
                )
            except Exception as fact_exc:
                logger.debug(f"World model update skipped: {fact_exc}")
            if agent_id:
                try:
                    contract_net.report_completion(step_id, agent_id, result.status == "completed")
                except Exception as completion_exc:
                    logger.debug(f"Contract completion update skipped: {completion_exc}")

    @staticmethod
    def _artifact_type_and_mime(path: str) -> tuple[str, str]:
        p = str(path or "").lower()
        if p.endswith(".html"):
            return "html", "text/html"
        if p.endswith(".css"):
            return "css", "text/css"
        if p.endswith(".js"):
            return "js", "application/javascript"
        if p.endswith(".json"):
            return "document", "application/json"
        if p.endswith(".md"):
            return "document", "text/markdown"
        if p.endswith(".txt"):
            return "document", "text/plain"
        return "code", "text/plain"

    def _default_artifact_content(self, template_id: str, artifact_name: str, original_input: str, plan_hint: str) -> str:
        artifact = str(artifact_name or "").strip().lower()
        if artifact.endswith(".html"):
            title = "Elyan Generated Project"
            return (
                "<!doctype html>\n"
                "<html lang=\"tr\">\n"
                "<head>\n"
                "  <meta charset=\"utf-8\" />\n"
                "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
                f"  <title>{title}</title>\n"
                "  <link rel=\"stylesheet\" href=\"./styles/main.css\" />\n"
                "</head>\n"
                "<body>\n"
                f"  <h1>{title}</h1>\n"
                f"  <p>{str(original_input or '').strip()}</p>\n"
                "  <script src=\"./scripts/main.js\"></script>\n"
                "</body>\n"
                "</html>\n"
            )
        if artifact.endswith(".css"):
            return (
                ":root { --bg:#f8fafc; --text:#0f172a; --accent:#2563eb; }\n"
                "body { margin:0; padding:40px; font-family: 'Segoe UI', sans-serif; background:var(--bg); color:var(--text); }\n"
                "h1 { color: var(--accent); }\n"
            )
        if artifact.endswith(".js"):
            return "document.addEventListener('DOMContentLoaded', () => console.log('ready'));\n"
        if artifact.endswith(".json"):
            return json.dumps(
                {
                    "generated_by": "elyan",
                    "template": template_id,
                    "goal": str(original_input or "").strip(),
                    "plan_hint": str(plan_hint or "").strip(),
                    "status": "draft",
                },
                indent=2,
                ensure_ascii=False,
            )
        if artifact.endswith(".md"):
            return (
                "# Teslim Özeti\n\n"
                f"- Template: `{template_id}`\n"
                f"- İstek: {str(original_input or '').strip()}\n\n"
                "## Plan\n"
                f"{str(plan_hint or '(yok)').strip()}\n"
            )
        return (
            f"Template: {template_id}\n"
            f"Goal: {str(original_input or '').strip()}\n"
            f"Plan Hint:\n{str(plan_hint or '(yok)').strip()}\n"
        )

    def _build_fallback_execution_payload(
        self,
        *,
        template_id: str,
        original_input: str,
        workspace_dir: str,
        plan_hint: str = "",
    ) -> Dict[str, Any]:
        """Deterministic payload when builder output is invalid."""
        template = get_template(template_id)
        mandatory = list(getattr(template, "mandatory_artifacts", []) or [])
        if not mandatory:
            mandatory = ["summary.txt"]

        workspace = Path(str(workspace_dir or "~/Desktop/elyan-fallback")).expanduser()
        steps: List[Dict[str, Any]] = [
            {
                "id": "ensure_workspace",
                "action": "create_folder",
                "params": {"path": str(workspace)},
                "owner": self._assign_owner("create_folder"),
                "preconditions": [],
                "postconditions": [{"type": "dir_exists", "path": str(workspace)}],
            }
        ]
        artifacts: List[Dict[str, Any]] = []

        for idx, rel_path in enumerate(mandatory, start=1):
            rel = str(rel_path or "").strip().lstrip("/")
            if not rel:
                rel = f"artifact_{idx}.txt"
            abs_path = (workspace / rel).resolve()
            parent = abs_path.parent

            a_type, mime = self._artifact_type_and_mime(rel)
            content = self._default_artifact_content(template_id, rel, original_input, plan_hint)
            artifacts.append(
                {
                    "path": str(abs_path),
                    "type": a_type,
                    "mime": mime,
                    "content": content,
                    "required_sections": [],
                    "min_size_bytes": max(16, min(256, len(content))),
                    "asset_source": "local",
                    "encoding": "utf-8",
                    "line_endings": "LF",
                }
            )

            if str(parent) != str(workspace):
                steps.append(
                    {
                        "id": f"ensure_parent_{idx}",
                        "action": "create_folder",
                        "params": {"path": str(parent)},
                        "owner": self._assign_owner("create_folder"),
                        "preconditions": [{"type": "dir_exists", "path": str(workspace)}],
                        "postconditions": [{"type": "dir_exists", "path": str(parent)}],
                    }
                )

            steps.append(
                {
                    "id": f"write_{idx}",
                    "action": "write_file",
                    "params": {"path": str(abs_path), "content": content},
                    "owner": self._assign_owner("write_file"),
                    "preconditions": [{"type": "dir_exists", "path": str(parent)}],
                    "postconditions": [
                        {"type": "file_exists", "path": str(abs_path)},
                        {"type": "min_size", "path": str(abs_path), "value": 8},
                    ],
                }
            )

        return {"artifact_map": {"artifacts": artifacts}, "execution_plan": steps}

def get_orchestrator(agent_instance) -> AgentOrchestrator:
    return AgentOrchestrator(agent_instance)
