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
from typing import List, Dict, Any, Optional
from utils.logger import get_logger

from .specialists import get_specialist_registry
from .contract import DeliverableContract, Artifact
from .qa_pipeline import QAPipeline
from .job_templates import get_template
from core.artifact_quality_engine import quality_engine
from core.memory_v2 import memory_v2
from core.action_lock import action_lock
from core.timeout_guard import with_timeout, STEP_TIMEOUT

logger = get_logger("multi_agent.orchestrator")

class AgentOrchestrator:
    def __init__(self, agent_instance):
        self.main_agent = agent_instance
        self.registry = get_specialist_registry()
        self.qa_pipeline = QAPipeline(agent_instance)

    async def manage_flow(self, plan: Any, original_input: str) -> str:
        """
        Industrial Loop: Reason -> Plan -> Surgical Execute -> Layered Verify
        """
        job_id = f"job_{int(time.time())}"
        workspace_dir = f"/tmp/elyan_{job_id}"
        start_time = time.time()
        
        # 1. Template selection
        job_type = "web_site_job" if "site" in original_input.lower() or "html" in original_input.lower() else "generic"
        template = get_template(job_type)
        
        action_lock.lock(job_id, f"Think-Factory Job: {template.name}")
        context = memory_v2.get_context_for_intent(original_input)
        
        from core.multi_agent.budget import BudgetTracker, BudgetExceededError
        self.budget_tracker = BudgetTracker(max_tokens=template.max_tokens, max_usd=template.max_usd)
        
        try:
            # --- Phase 0: DEEP REASONING (The 'Think' Step) ---
            action_lock.update_status(0.05, "Brainstorming: En iyi çözüm yolu aranıyor...")
            reason_prompt = f"Girdi: {original_input}. Bu iş için en verimli stratejiyi düşün. Riskleri ve asset ihtiyaçlarını belirle."
            # Use pm_agent for initial reasoning
            brainstorm_raw = await self._run_specialist("pm_agent", reason_prompt)
            self._log_thought("Planner", brainstorm_raw)

            # --- Phase 1: PLAN ---
            action_lock.update_status(0.1, "Planner: Teknik Sözleşme Hazırlanıyor...")
            plan_prompt = f"Strateji: {brainstorm_raw}\nGirdi: {original_input}. Sözleşmeyi JSON formatında planla."
            plan_raw = await self._run_specialist("pm_agent", plan_prompt)
            plan_data = self._safe_parse_json(plan_raw)

            contract = DeliverableContract(job_id=job_id, goal=original_input, job_type=job_type)
            await self.main_agent._execute_tool("create_folder", {"path": workspace_dir})

            from core.deterministic_runner import DeterministicToolRunner, ExecutionPlan
            from core.multi_agent.rollback import RollbackManager
        
            rollback_mgr = RollbackManager(workspace_dir)
            await rollback_mgr.ensure_initialized()
            initial_snapshot = await rollback_mgr.create_snapshot()

            # --- Phase 2: EXECUTE (Build & Patch) ---
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
                if contract.artifacts:
                    issues = [f"{a.path}: {a.errors}" for a in contract.artifacts.values() if a.errors]
                    build_prompt += f"\n\nDERİN DÜŞÜN: Önceki hataları analiz et ve repair/patch (cerrahi çözüm) adımları içeren yeni bir execution plan üret: {issues}"

                build_raw = await self._run_specialist("executor", build_prompt)
                self._log_thought("Builder", build_raw)
            
                # Extract JSON and execute
                try:
                    match = re.search(r"\{.*\}", build_raw, re.DOTALL)
                    if match:
                        payload = json.loads(match.group(0))
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
                    # Fallback implementation (old Markdown blocks) removed to force state-machine compliance.
                    pass

                # --- Phase 3: VERIFY (Swarm Consensus) ---
                action_lock.update_status(0.7, "Validator: Swarm Consensus Debate...")
            
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
                    await self.main_agent._execute_tool("run_safe_command", {"command": f"cd {workspace_dir} && zip -r {zip_path} ."})
                
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
                    action_lock.unlock()
                
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
                        plan_data["risks"] = ["Hiçbir dosya bloğu tespit edilemedi. Lütfen [FILE: /yol] formatını kullan."]

            await rollback_mgr.restore_snapshot(initial_snapshot)
            action_lock.unlock()
            return f"❌ GÖREV BAŞARISIZ (QA Onayı Alınamadı: {job_id})\n\nSon Hatalar: {issues}"
        
        except BudgetExceededError as e:
            await getattr(rollback_mgr, 'restore_snapshot')(initial_snapshot) if 'rollback_mgr' in locals() else None
            action_lock.unlock()
            logger.error(f"Budget break: {e}")
            return f"🛑 BÜTÇE/TOKEN LİMİTİ AŞILDI: {e}\n{self.budget_tracker.get_status()}"

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

    def _log_thought(self, agent_name: str, raw_text: str):
        """Extract and log the thought block for transparency."""
        match = re.search(r"<thought>(.*?)</thought>", raw_text, re.DOTALL)
        if match:
            thought = match.group(1).strip()
            logger.info(f"🧠 [{agent_name} Reasoning]: {thought}")
            # Dashboard'a özel bir ipucu olarak da gönderebiliriz
            from core.gateway.server import push_hint
            push_hint(f"{agent_name}: {thought[:120]}...", icon="brain", color="purple")

    async def _run_specialist(self, key: str, prompt: str) -> str:
        specialist = self.registry.get(key)
        final_prompt = f"ROLÜN: {specialist.system_prompt}\n\nİSTEK: {prompt}"
        
        if hasattr(self, "budget_tracker"):
            self.budget_tracker.consume(input_tokens=(len(final_prompt) // 4), output_tokens=0)
            
        result = await with_timeout(
            self.main_agent.llm.generate(final_prompt, role=specialist.role, user_id="system"),
            seconds=STEP_TIMEOUT,
            fallback=f'{{"outputs": ["Hata: {specialist.name} zaman aşımı"], "risks": ["Timeout"]}}',
            context=f"factory:{key}"
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

def get_orchestrator(agent_instance) -> AgentOrchestrator:
    return AgentOrchestrator(agent_instance)
