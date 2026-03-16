from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Tuple

from core.goal_graph import get_goal_graph_planner
from core.intelligent_planner import IntelligentPlanner
from utils.logger import get_logger

from .manager import SubAgentManager
from .session import SubAgentTask
from .shared_state import SharedTaskBoard, TeamMessage, TeamMessageBus, TeamTask
from .validator import SubAgentValidator

logger = get_logger("agent_team")


DEFAULT_TOOL_SCOPES: Dict[str, frozenset[str]] = {
    "lead": frozenset({"chat", "advanced_research", "web_search", "read_file"}),
    "researcher": frozenset({"advanced_research", "deep_research", "web_search", "open_url", "read_file", "analyze_document", "chat"}),
    "builder": frozenset({"write_file", "create_folder", "create_directory", "create_web_project_scaffold", "create_software_project_pack", "run_safe_command", "execute_python_code", "take_screenshot", "chat"}),
    "ops": frozenset({"run_safe_command", "execute_shell_command", "list_files", "read_file", "http_request", "api_health_check", "graphql_query", "chat"}),
    "qa": frozenset({"read_file", "list_files", "take_screenshot", "chat"}),
    "communicator": frozenset({"chat", "write_file"}),
}


@dataclass
class TeamConfig:
    timeout_s: int = 900
    max_parallel: int = 4
    use_llm_planner: bool = False
    max_retries_per_task: int = 1
    max_tasks: int = 12
    specialists: List[str] = field(default_factory=lambda: ["lead", "researcher", "builder", "ops", "qa", "communicator"])


@dataclass
class TeamResult:
    status: str
    summary: str
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    telemetry: Dict[str, Any] = field(default_factory=dict)


class AgentTeam:
    """Coordinated team execution wrapper over sub-agents."""

    def __init__(self, agent: Any, config: TeamConfig | None = None):
        self.agent = agent
        self.config = config or TeamConfig()
        self.board = SharedTaskBoard()
        self.bus = TeamMessageBus()
        self.validator = SubAgentValidator()

    @staticmethod
    def _select_specialist(action: str, task_name: str = "", domain_hint: str = "") -> str:
        t = f"{action} {task_name} {domain_hint}".lower()
        if any(k in t for k in ("automation", "otomasyon", "schedule", "cron", "create_automation")):
            return "ops"
        if any(k in t for k in ("write_file", "read_file", "list_files", "create_folder", "create_directory")):
            return "builder"
        if any(k in t for k in ("code", "kod", "python", "run_safe_command", "execute_python", "execute_shell")):
            return "builder"
        if any(k in t for k in ("research", "araştır", "arastir", "web_search", "open_url", "analyze")):
            return "researcher"
        if any(k in t for k in ("verify", "qa", "test", "kontrol", "doğrula", "dogrula")):
            return "qa"
        if any(k in t for k in ("http_request", "graphql_query", "api_health_check", "run_safe_command", "execute_shell")):
            return "ops"
        if any(k in t for k in ("report", "sunum", "mail", "communicat")):
            return "communicator"
        return "builder"

    @staticmethod
    def _dedupe(items: List[str]) -> List[str]:
        return list(dict.fromkeys([str(x).strip() for x in items if str(x).strip()]))

    @staticmethod
    def _extract_brief_steps(brief: str) -> List[str]:
        text = str(brief or "").strip()
        if not text:
            return []
        numbered = re.split(r"(?:^|\s)(?:\d+[\)\.\-:])\s*", text)
        candidates = [c.strip(" \n\t-•") for c in numbered if str(c).strip(" \n\t-•")]
        if len(candidates) >= 2:
            return candidates
        lines = [ln.strip(" \n\t-•") for ln in text.splitlines() if ln.strip(" \n\t-•")]
        if len(lines) >= 2:
            return lines
        joined = re.split(r"\s+(?:ve|sonra|ardından|ardindan|then|and)\s+", text, flags=re.IGNORECASE)
        joined = [c.strip(" \n\t-•") for c in joined if str(c).strip(" \n\t-•")]
        if len(joined) >= 2:
            return joined
        return [text]

    def _deterministic_tasks_from_brief(self, brief: str, planner: IntelligentPlanner) -> List[TeamTask]:
        steps = self._extract_brief_steps(brief)[: max(1, int(self.config.max_tasks or 12))]
        tasks: List[TeamTask] = []
        for idx, step_text in enumerate(steps, start=1):
            action = planner._normalize_action_name(
                planner._infer_action(step_text),
                fallback_text=f"{step_text} {brief}",
            )
            params = planner._sanitize_subtask_params(action, {}, name=step_text, goal=brief)
            specialist = self._select_specialist(action, step_text)
            gates = self._derive_gates(specialist, action, params)
            objective, success_criteria = self._derive_success_contract(
                brief=brief,
                title=step_text,
                specialist=specialist,
                action=action,
                params=params,
            )
            depends_on = [tasks[-1].task_id] if tasks else []
            tasks.append(
                TeamTask(
                    title=step_text[:120] or f"Adım {idx}",
                    specialist=specialist,
                    action=action,
                    params=params,
                    objective=objective,
                    success_criteria=success_criteria,
                    gates=gates,
                    depends_on=depends_on,
                    max_retries=max(0, int(self.config.max_retries_per_task or 0)),
                )
            )
        return tasks

    def _derive_gates(self, specialist: str, action: str, params: Dict[str, Any]) -> List[str]:
        gates: List[str] = []
        if specialist == "researcher":
            gates.extend(["has_content", "no_placeholder"])
        elif specialist == "qa":
            gates.extend(["has_content"])

        a = str(action or "").strip()
        low_action = a.lower()
        if low_action in {"advanced_research", "deep_research"}:
            gates.extend(
                [
                    "research_contract_complete",
                    "claim_coverage_full",
                    "critical_claim_support",
                ]
            )
        elif low_action == "research_document_delivery":
            gates.extend(
                [
                    "research_contract_complete",
                    "claim_coverage_full",
                    "critical_claim_support",
                    "claim_map_present",
                    "uncertainty_section_present",
                ]
            )
            if str((params or {}).get("previous_claim_map_path") or "").strip() or str((params or {}).get("revision_request") or "").strip():
                gates.append("revision_summary_present")
        if a in {"write_file", "take_screenshot", "write_word", "write_excel"}:
            gates.extend(["file_exists", "file_not_empty"])

        path = str((params or {}).get("path") or "").lower()
        if path.endswith(".json"):
            gates.append("valid_json")
        elif path.endswith(".html"):
            gates.append("valid_html")
        elif path.endswith(".py"):
            gates.append("valid_python")
        task_packet = (params or {}).get("_task_packet") if isinstance((params or {}).get("_task_packet"), dict) else {}
        if task_packet:
            gates.extend(["task_scope_respected", "artifact_bundle_complete"])
            if bool(task_packet.get("review_required", False)):
                gates.append("review_passed")
            if isinstance(task_packet.get("tests_to_write"), list) and task_packet.get("tests_to_write"):
                gates.extend(["tests_written_first", "failing_test_observed", "tests_pass_after_change"])
        gates.append("tool_success")
        return self._dedupe(gates)

    @staticmethod
    def _extract_research_telemetry(result_payload: Any) -> Dict[str, Any]:
        payload = dict(result_payload) if isinstance(result_payload, dict) else {}
        quality = payload.get("quality_summary") if isinstance(payload.get("quality_summary"), dict) else {}
        if not quality and not any(payload.get(k) for k in ("research_contract", "claim_map_path", "revision_summary_path")):
            return {}
        telemetry: Dict[str, Any] = {}
        for key in (
            "claim_coverage",
            "critical_claim_coverage",
            "uncertainty_count",
            "conflict_count",
            "manual_review_claim_count",
            "status",
        ):
            if key in quality:
                telemetry[key] = quality.get(key)
        for key in ("claim_map_path", "revision_summary_path"):
            value = str(payload.get(key) or "").strip()
            if value:
                telemetry[key] = value
        if isinstance(payload.get("research_contract"), dict):
            telemetry["research_contract_present"] = True
        return telemetry

    def _derive_success_contract(
        self,
        *,
        brief: str,
        title: str,
        specialist: str,
        action: str,
        params: Dict[str, Any],
    ) -> Tuple[str, List[str]]:
        objective = str(title or brief or "").strip() or "Somut ve doğrulanabilir çıktı üret"
        criteria: List[str] = []
        if specialist == "researcher":
            criteria.extend([
                "Boş ve placeholder olmayan içerik üret",
                "Kısa kanıt özeti ver",
            ])
        elif specialist == "qa":
            criteria.extend([
                "Doğrulama notu üret",
                "Risk varsa açıkça yaz",
            ])
        elif specialist == "communicator":
            criteria.extend([
                "Sonucu kısa ve net özetle",
                "Gereksiz teknik detay verme",
            ])
        else:
            criteria.append("Somut bir çıktı üret")

        a = str(action or "").strip().lower()
        path = str((params or {}).get("path") or "").strip()
        if a in {"write_file", "take_screenshot", "write_word", "write_excel"} or path:
            criteria.append("Üretilen dosya yolu artifact listesinde olsun")
            criteria.append("Dosya boş olmasın")
        else:
            criteria.append("Sonuç en az bir uygulanabilir çıktı içersin")
        return objective, self._dedupe(criteria)

    @staticmethod
    def _team_specialist_from_hint(hint: str) -> str:
        low = str(hint or "").strip().lower()
        if any(tok in low for tok in ("devops", "ops", "infra")):
            return "ops"
        if any(tok in low for tok in ("qa", "reality", "evidence", "checker")):
            return "qa"
        if any(tok in low for tok in ("research", "trend", "feedback")):
            return "researcher"
        if any(tok in low for tok in ("summary", "communicator", "report")):
            return "communicator"
        return "builder"

    @staticmethod
    def _explicit_packet_dependencies(packet: Dict[str, Any]) -> List[str]:
        deps = packet.get("depends_on_packets")
        if deps is None:
            deps = packet.get("depends_on")
        if deps is None:
            deps = packet.get("packet_dependencies")
        if isinstance(deps, str):
            deps = [deps]
        if not isinstance(deps, list):
            return []
        return [str(item).strip() for item in deps if str(item).strip()]

    @staticmethod
    def _is_read_only_packet(packet: Dict[str, Any]) -> bool:
        action = str(packet.get("action") or "chat").strip().lower()
        return action in {"read_file", "list_files", "search_files", "web_search", "advanced_research", "analyze_document", "chat"}

    @staticmethod
    def _packet_conflicts(current_packet: Dict[str, Any], prior_packet: Dict[str, Any]) -> bool:
        current_targets = {str(item).strip() for item in list(current_packet.get("target_files") or []) if str(item).strip()}
        prior_targets = {str(item).strip() for item in list(prior_packet.get("target_files") or []) if str(item).strip()}
        if current_targets and prior_targets and current_targets.intersection(prior_targets):
            return True
        current_read_only = AgentTeam._is_read_only_packet(current_packet)
        prior_read_only = AgentTeam._is_read_only_packet(prior_packet)
        if current_read_only and prior_read_only:
            return False
        if not current_targets or not prior_targets:
            return not (current_read_only and prior_read_only)
        return False

    @staticmethod
    def _packet_scope(packet: Dict[str, Any]) -> List[str]:
        scope = [
            str(item).strip()
            for item in list(packet.get("target_files") or packet.get("scope_guard") or [])
            if str(item).strip()
        ]
        return list(dict.fromkeys(scope))

    def _summarize_packet_execution_plan(self, task_packets: List[Dict[str, Any]]) -> Dict[str, Any]:
        packets = [dict(packet) for packet in list(task_packets or []) if isinstance(packet, dict)]
        if not packets:
            return {
                "packet_count": 0,
                "parallel_waves": 0,
                "max_wave_size": 0,
                "parallelizable_packets": 0,
                "serial_packets": 0,
                "ownership_conflicts": 0,
                "specialist_assignments": {},
                "wave_map": {},
            }

        wave_by_packet: Dict[str, int] = {}
        packets_by_id: Dict[str, Dict[str, Any]] = {}
        waves: List[List[str]] = []
        conflict_pairs: set[tuple[str, str]] = set()
        specialist_assignments: Dict[str, int] = {}

        for idx, packet in enumerate(packets, start=1):
            packet_id = str(packet.get("packet_id") or f"packet_{idx}").strip() or f"packet_{idx}"
            packets_by_id[packet_id] = packet
            specialist = self._team_specialist_from_hint(packet.get("specialist_hint") or "")
            specialist_assignments[specialist] = int(specialist_assignments.get(specialist, 0) or 0) + 1

            deps = [dep for dep in self._explicit_packet_dependencies(packet) if dep]
            min_wave = 0
            for dep in deps:
                if dep in wave_by_packet:
                    min_wave = max(min_wave, int(wave_by_packet[dep]) + 1)

            assigned_wave = None
            for wave_idx in range(min_wave, len(waves)):
                existing_ids = list(waves[wave_idx])
                if all(not self._packet_conflicts(packet, packets_by_id[existing_id]) for existing_id in existing_ids):
                    assigned_wave = wave_idx
                    break
                for existing_id in existing_ids:
                    if self._packet_conflicts(packet, packets_by_id[existing_id]):
                        conflict_pairs.add(tuple(sorted((packet_id, existing_id))))
            if assigned_wave is None:
                assigned_wave = len(waves)
                waves.append([])
            waves[assigned_wave].append(packet_id)
            wave_by_packet[packet_id] = assigned_wave

        packets_in_parallel_waves = sum(len(wave) for wave in waves if len(wave) > 1)
        return {
            "packet_count": len(packets),
            "parallel_waves": len(waves),
            "max_wave_size": max((len(wave) for wave in waves), default=0),
            "parallelizable_packets": int(packets_in_parallel_waves),
            "serial_packets": max(0, len(packets) - int(packets_in_parallel_waves)),
            "ownership_conflicts": len(conflict_pairs),
            "specialist_assignments": specialist_assignments,
            "wave_map": {packet_id: int(wave_idx + 1) for packet_id, wave_idx in wave_by_packet.items()},
        }

    def _team_tasks_from_packets(
        self,
        brief: str,
        task_packets: List[Dict[str, Any]],
        workflow_context: Dict[str, Any] | None = None,
    ) -> List[TeamTask]:
        workflow = dict(workflow_context or {})
        tasks: List[TeamTask] = []
        packet_completion_barriers: Dict[str, str] = {}
        prior_packets: List[Dict[str, Any]] = []
        for idx, packet in enumerate(list(task_packets or []), start=1):
            if not isinstance(packet, dict):
                continue
            action = str(packet.get("action") or "chat").strip() or "chat"
            title = str(packet.get("title") or packet.get("goal") or f"Task {idx}").strip() or f"Task {idx}"
            specialist = self._team_specialist_from_hint(packet.get("specialist_hint") or "")
            params = dict(packet.get("params") or {}) if isinstance(packet.get("params"), dict) else {}
            params["_task_packet"] = dict(packet)
            if workflow:
                params["_workflow_context"] = dict(workflow)
            params["_coordination_contract"] = {
                "main_agent_role": "contract_owner",
                "sub_agent_role": "scoped_executor",
                "packet_id": str(packet.get("packet_id") or f"packet_{idx}"),
                "specialist": specialist,
                "write_scope": self._packet_scope(packet),
                "review_required": bool(packet.get("review_required", False)),
            }
            gates = self._derive_gates(specialist, action, params)
            objective, success_criteria = self._derive_success_contract(
                brief=brief,
                title=title,
                specialist=specialist,
                action=action,
                params=params,
            )
            worker_dependencies: List[str] = []
            for dep in self._explicit_packet_dependencies(packet):
                barrier = packet_completion_barriers.get(dep)
                if barrier:
                    worker_dependencies.append(barrier)
            if not worker_dependencies:
                for prior_packet in prior_packets:
                    prior_id = str(prior_packet.get("packet_id") or "").strip()
                    if not prior_id:
                        continue
                    if not self._packet_conflicts(packet, prior_packet):
                        continue
                    barrier = packet_completion_barriers.get(prior_id)
                    if barrier:
                        worker_dependencies.append(barrier)
            worker = TeamTask(
                title=title,
                specialist=specialist,
                action=action,
                params=params,
                objective=objective,
                success_criteria=success_criteria,
                gates=gates,
                depends_on=self._dedupe(worker_dependencies),
                max_retries=max(0, int(self.config.max_retries_per_task or 0)),
            )
            tasks.append(worker)

            # NEXUS-style two-stage review loop: spec compliance then code quality.
            review_params = {
                "message": (
                    f"Spec compliance review for {title}. "
                    f"Scope guard: {', '.join(str(x) for x in list(packet.get('scope_guard') or [])[:6])}. "
                    f"Acceptance: {', '.join(str(x) for x in list(packet.get('acceptance_checks') or [])[:6])}."
                ),
                "_task_packet": dict(packet),
            }
            spec_review = TeamTask(
                title=f"{title} / Spec Review",
                specialist="qa",
                action="chat",
                params=review_params,
                objective=f"{title} için plan uyumunu denetle",
                success_criteria=["Spec compliance review yaz", "Açık risk varsa belirt"],
                gates=["has_content", "review_passed", "tool_success"],
                depends_on=[worker.task_id],
                max_retries=0,
            )
            tasks.append(spec_review)

            quality_params = {
                "message": (
                    f"Code quality review for {title}. "
                    f"Tests: {', '.join(str(x) for x in list(packet.get('tests_to_write') or [])[:4]) or 'N/A'}. "
                    f"Verification: {', '.join(str(x) for x in list(packet.get('verification_steps') or [])[:4]) or 'N/A'}."
                ),
                "_task_packet": dict(packet),
            }
            quality_review = TeamTask(
                title=f"{title} / Quality Review",
                specialist="qa",
                action="chat",
                params=quality_params,
                objective=f"{title} için code quality review üret",
                success_criteria=["Code quality review yaz", "Regresyon riski varsa belirt"],
                gates=["has_content", "review_passed", "tool_success"],
                depends_on=[spec_review.task_id],
                max_retries=0,
            )
            tasks.append(quality_review)
            packet_id = str(packet.get("packet_id") or "").strip() or f"packet_{idx}"
            packet_completion_barriers[packet_id] = quality_review.task_id
            prior_packets.append(dict(packet))
        return tasks

    @staticmethod
    def _quality_score(*, status: str, failed_gates: List[str], retry_count: int) -> float:
        score = 1.0
        s = str(status or "").strip().lower()
        if s == "failed":
            return 0.0
        if s in {"partial", "retrying"}:
            score -= 0.35
        score -= min(0.5, 0.12 * len(list(failed_gates or [])))
        score -= min(0.25, 0.08 * int(retry_count or 0))
        return round(max(0.0, min(1.0, score)), 2)

    async def _build_team_tasks(
        self,
        brief: str,
        *,
        task_packets: List[Dict[str, Any]] | None = None,
        workflow_context: Dict[str, Any] | None = None,
    ) -> Tuple[List[TeamTask], Dict[str, Any]]:
        if task_packets:
            graph = {"stage_count": len(task_packets), "workflow": dict(workflow_context or {})}
            return self._team_tasks_from_packets(brief, list(task_packets or []), workflow_context=workflow_context), graph
        graph: Dict[str, Any] = {}
        try:
            graph = get_goal_graph_planner().build(brief)
        except Exception:
            graph = {}

        planner = IntelligentPlanner()
        plan = await planner.create_plan(
            description=brief,
            llm_client=getattr(self.agent, "llm", None),
            use_llm=bool(self.config.use_llm_planner),
            user_id=str(getattr(self.agent, "current_user_id", "local") or "local"),
            context={"goal_graph": graph},
        )
        subtasks = list(getattr(plan, "subtasks", []) or [])[: max(1, int(self.config.max_tasks or 12))]
        quality = planner.evaluate_plan_quality(subtasks, goal=brief) if subtasks else {"safe_to_run": False}

        tasks: List[TeamTask] = []
        if not subtasks or not bool(quality.get("safe_to_run", False)):
            tasks = self._deterministic_tasks_from_brief(brief, planner)
            if tasks:
                return tasks, graph
        if not tasks:
            tasks.append(
                TeamTask(
                    title="Görev Analizi",
                    specialist="researcher",
                    action="advanced_research",
                    params={"topic": brief, "depth": "standard"},
                    objective="Görevi anlamlandır ve uygulanabilir araştırma çıktısı üret",
                    success_criteria=["Boş olmayan araştırma özeti üret", "Placeholder içerik üretme"],
                    gates=["has_content", "no_placeholder"],
                )
            )
            tasks.append(
                TeamTask(
                    title="Çıktı Üretimi",
                    specialist="builder",
                    action="chat",
                    params={"message": f"Uygulanabilir bir çıktı üret: {brief}"},
                    objective="Araştırma çıktısını uygulanabilir sonuca dönüştür",
                    success_criteria=["Somut bir sonuç veya artifact üret", "Boş yanıt verme"],
                    gates=["has_content"],
                    depends_on=[tasks[0].task_id],
                )
            )
            return tasks, graph

        for st in subtasks:
            params = dict(getattr(st, "params", {}) or {})
            action = str(getattr(st, "action", "chat") or "chat")
            name = str(getattr(st, "name", "") or "Adım")
            deps = list(getattr(st, "dependencies", []) or [])
            specialist = self._select_specialist(action, name, getattr(st, "action", ""))
            gates = self._derive_gates(specialist, action, params)
            objective, success_criteria = self._derive_success_contract(
                brief=brief,
                title=name,
                specialist=specialist,
                action=action,
                params=params,
            )
            tasks.append(
                TeamTask(
                    title=name,
                    specialist=specialist,
                    action=action,
                    params=params,
                    objective=objective,
                    success_criteria=success_criteria,
                    depends_on=deps,
                    gates=gates,
                    max_retries=max(0, int(self.config.max_retries_per_task or 0)),
                )
            )
        return tasks, graph

    async def _execute_wave(
        self,
        manager: SubAgentManager,
        brief: str,
        lead_summary: str,
        batch: List[TeamTask],
    ) -> List[Dict[str, Any]]:
        to_run: List[Tuple[str, SubAgentTask]] = []
        picked: List[TeamTask] = []
        for task in list(batch or []):
            claimed = await self.board.claim_task(f"worker:{task.specialist}", task.task_id)
            if not claimed:
                continue
            picked.append(task)
            payload = dict(task.params or {})
            payload.setdefault("_lead_summary", lead_summary)
            task_packet = payload.get("_task_packet") if isinstance(payload.get("_task_packet"), dict) else {}
            to_run.append(
                (
                    task.specialist,
                    SubAgentTask(
                        name=task.title,
                        action=task.action,
                        params=payload,
                        description=brief,
                        objective=str(task.objective or task.title or brief),
                        success_criteria=list(task.success_criteria or []),
                        domain=task.specialist,
                        dependencies=list(task.depends_on or []),
                        gates=list(task.gates or []),
                        target_files=list(task_packet.get("target_files") or []),
                        tests_to_write=list(task_packet.get("tests_to_write") or []),
                        verification_steps=list(task_packet.get("verification_steps") or []),
                        scope_guard=list(task_packet.get("scope_guard") or []),
                        review_required=bool(task_packet.get("review_required", False)),
                        handoff_template=str(task_packet.get("handoff_template") or ""),
                        context={
                            "lead_summary": str(lead_summary or ""),
                            "workflow_context": dict(payload.get("_workflow_context") or {})
                            if isinstance(payload.get("_workflow_context"), dict)
                            else {},
                        },
                    ),
                )
            )

        if not to_run:
            return []

        results = await manager.spawn_parallel(to_run, timeout=min(300, self.config.timeout_s))
        outputs: List[Dict[str, Any]] = []
        for task, result in zip(picked, results):
            validation = await self.validator.validate(result, list(task.gates or []))
            if validation.passed:
                await self.board.complete_task(task.task_id, result.result)
                q_score = self._quality_score(
                    status=result.status,
                    failed_gates=[],
                    retry_count=int(task.retry_count or 0),
                )
                await self.bus.send(
                    from_agent=task.specialist,
                    to_agent="lead",
                    message=TeamMessage(
                        from_agent=task.specialist,
                        to_agent="lead",
                        body=f"{task.title} tamamlandı (q={q_score})",
                        payload={"task_id": task.task_id, "quality_score": q_score, "status": result.status},
                    ),
                )
                outputs.append(
                    {
                        "task_id": task.task_id,
                        "task": task.title,
                        "specialist": task.specialist,
                        "status": result.status,
                        "result": result.result,
                        "quality_score": q_score,
                        "objective": str(task.objective or ""),
                        "success_criteria": list(task.success_criteria or []),
                        "validation": {"passed": True, "failed_gates": []},
                        "research_telemetry": self._extract_research_telemetry(result.result),
                    }
                )
                continue

            if task.retry_count < task.max_retries:
                task.retry_count += 1
                task.params["_validation_feedback"] = ", ".join(validation.failed_gates)
                await self.board.retry_task(task.task_id, note=f"validation_retry:{','.join(validation.failed_gates)}")
                q_score = self._quality_score(
                    status="retrying",
                    failed_gates=list(validation.failed_gates or []),
                    retry_count=int(task.retry_count or 0),
                )
                await self.bus.send(
                    from_agent=task.specialist,
                    to_agent="lead",
                    message=TeamMessage(
                        from_agent=task.specialist,
                        to_agent="lead",
                        body=f"{task.title} retry (gates={','.join(validation.failed_gates)})",
                        payload={"task_id": task.task_id, "quality_score": q_score, "status": "retrying"},
                    ),
                )
                outputs.append(
                    {
                        "task_id": task.task_id,
                        "task": task.title,
                        "specialist": task.specialist,
                        "status": "retrying",
                        "result": result.result,
                        "quality_score": q_score,
                        "objective": str(task.objective or ""),
                        "success_criteria": list(task.success_criteria or []),
                        "validation": {"passed": False, "failed_gates": list(validation.failed_gates)},
                        "research_telemetry": self._extract_research_telemetry(result.result),
                    }
                )
                continue

            fail_result = {
                "success": False,
                "error": "validation_failed",
                "failed_gates": list(validation.failed_gates),
                "raw_result": result.result,
            }
            await self.board.fail_task(task.task_id, result=fail_result, note="validation_failed")
            q_score = self._quality_score(
                status="failed",
                failed_gates=list(validation.failed_gates or []),
                retry_count=int(task.retry_count or 0),
            )
            await self.bus.send(
                from_agent=task.specialist,
                to_agent="lead",
                message=TeamMessage(
                    from_agent=task.specialist,
                    to_agent="lead",
                    body=f"{task.title} başarısız (gates={','.join(validation.failed_gates)})",
                    payload={"task_id": task.task_id, "quality_score": q_score, "status": "failed"},
                ),
            )
            outputs.append(
                {
                    "task_id": task.task_id,
                    "task": task.title,
                    "specialist": task.specialist,
                    "status": "failed",
                    "result": fail_result,
                    "quality_score": q_score,
                    "objective": str(task.objective or ""),
                    "success_criteria": list(task.success_criteria or []),
                    "validation": {"passed": False, "failed_gates": list(validation.failed_gates)},
                    "research_telemetry": self._extract_research_telemetry(result.result),
                }
            )
        return outputs

    async def execute_project(
        self,
        brief: str,
        task_packets: List[Dict[str, Any]] | None = None,
        workflow_context: Dict[str, Any] | None = None,
    ) -> TeamResult:
        manager = SubAgentManager(
            self.agent,
            parent_session_id="team",
            tool_scopes=DEFAULT_TOOL_SCOPES,
        )
        workflow = dict(workflow_context or {})

        lead_task = SubAgentTask(
            name="Lead Plan",
            action="chat",
            params={
                "message": (
                    f"Görevi kısa planla, bağımlılıkları ve riskleri belirt: {brief}. "
                    f"Workflow={workflow.get('workflow_profile') or 'default'} "
                    f"Workspace={workflow.get('workspace_mode') or '-'}"
                )
            },
            description=brief,
            domain="planning",
        )
        lead_result = await manager.spawn_and_wait("lead", lead_task, timeout=min(120, self.config.timeout_s))
        lead_summary = str(lead_result.result or "")
        packet_plan_summary = self._summarize_packet_execution_plan(list(task_packets or []))

        try:
            tasks, graph = await self._build_team_tasks(
                brief,
                task_packets=list(task_packets or []),
                workflow_context=workflow,
            )
        except TypeError:
            tasks, graph = await self._build_team_tasks(brief)
        for t in tasks:
            await self.board.post_task(t)

        outputs: List[Dict[str, Any]] = []
        safety_counter = 0
        while safety_counter < 100:
            safety_counter += 1
            snapshot = await self.board.snapshot()
            unfinished = [t for t in snapshot if t.status in {"pending", "running"}]
            if not unfinished:
                break

            available = await self.board.get_available("coordinator")
            if not available:
                for pending in [t for t in unfinished if t.status == "pending"]:
                    await self.board.fail_task(pending.task_id, result={"success": False, "error": "dependency_deadlock"}, note="dependency_deadlock")
                break

            batch = available[: max(1, int(self.config.max_parallel or 1))]
            wave_outputs = await self._execute_wave(manager, brief, lead_summary, batch)
            outputs.extend(wave_outputs)

        final_tasks = await self.board.snapshot()
        completed = [t for t in final_tasks if t.status == "completed"]
        failed = [t for t in final_tasks if t.status == "failed"]

        total = max(1, len(final_tasks))
        completion_ratio = len(completed) / float(total)
        if completion_ratio < 0.6:
            status = "failed"
        elif failed:
            status = "partial"
        else:
            status = "success"

        summary = (
            f"Team mode tamamlandı: completed={len(completed)} failed={len(failed)} "
            f"stages={int((graph or {}).get('stage_count', len(final_tasks) or 1))}"
        )
        notes = []
        if lead_summary:
            notes.append(f"lead: {lead_summary[:300]}")
        if failed:
            notes.append("failed_tasks: " + ", ".join(t.title for t in failed[:10]))
        quality_values = [float(o.get("quality_score", 0.0) or 0.0) for o in outputs if "quality_score" in o]
        if quality_values:
            quality_avg = round(sum(quality_values) / max(1, len(quality_values)), 2)
            notes.append(f"quality_avg: {quality_avg}")
            if status == "success" and quality_avg < 0.7:
                status = "partial"
                notes.append("completion_gate: quality_avg_below_threshold")
        task_packet_count = len(list(task_packets or []))
        packet_progress_total = task_packet_count or len(final_tasks)
        packet_progress_completed = min(len(completed), packet_progress_total)
        review_status = "passed" if status == "success" else "blocked" if failed else "pending"
        research_rows = [o.get("research_telemetry", {}) for o in outputs if isinstance(o.get("research_telemetry"), dict) and o.get("research_telemetry")]
        telemetry: Dict[str, Any] = {
            "completed": len(completed),
            "failed": len(failed),
            "quality_avg": quality_avg if quality_values else 0.0,
            "workflow_profile": str(workflow.get("workflow_profile") or ""),
            "workflow_id": str(workflow.get("workflow_id") or ""),
            "workspace_mode": str(workflow.get("workspace_mode") or ""),
            "approval_status": str(workflow.get("approval_status") or ""),
            "plan_progress_completed": int(packet_progress_completed),
            "plan_progress_total": int(packet_progress_total),
            "plan_progress": f"{int(packet_progress_completed)}/{int(packet_progress_total)}",
            "review_status": review_status,
            "main_agent_role": "contract_owner",
            "sub_agent_role": "scoped_executor",
            "packet_count": int(packet_plan_summary.get("packet_count", 0) or 0),
            "parallel_waves": int(packet_plan_summary.get("parallel_waves", 0) or 0),
            "max_wave_size": int(packet_plan_summary.get("max_wave_size", 0) or 0),
            "parallelizable_packets": int(packet_plan_summary.get("parallelizable_packets", 0) or 0),
            "serial_packets": int(packet_plan_summary.get("serial_packets", 0) or 0),
            "ownership_conflicts": int(packet_plan_summary.get("ownership_conflicts", 0) or 0),
            "specialist_assignments": dict(packet_plan_summary.get("specialist_assignments") or {}),
            "packet_wave_map": dict(packet_plan_summary.get("wave_map") or {}),
        }
        if research_rows:
            claim_coverages = [float(row.get("claim_coverage", 0.0) or 0.0) for row in research_rows if row.get("claim_coverage") is not None]
            critical_coverages = [float(row.get("critical_claim_coverage", 0.0) or 0.0) for row in research_rows if row.get("critical_claim_coverage") is not None]
            uncertainty_counts = [int(row.get("uncertainty_count", 0) or 0) for row in research_rows]
            failed_research_gates = sorted(
                {
                    gate
                    for output in outputs
                    if isinstance(output, dict)
                    for gate in list(((output.get("validation") or {}).get("failed_gates") or []))
                    if gate in {
                        "research_contract_complete",
                        "claim_coverage_full",
                        "critical_claim_support",
                        "uncertainty_section_present",
                        "claim_map_present",
                        "revision_summary_present",
                    }
                }
            )
            telemetry.update(
                {
                    "research_tasks": len(research_rows),
                    "avg_claim_coverage": round(sum(claim_coverages) / max(1, len(claim_coverages)), 2) if claim_coverages else 0.0,
                    "avg_critical_claim_coverage": round(sum(critical_coverages) / max(1, len(critical_coverages)), 2) if critical_coverages else 0.0,
                    "max_uncertainty_count": max(uncertainty_counts) if uncertainty_counts else 0,
                    "failed_research_gates": failed_research_gates,
                    "claim_map_outputs": sum(1 for row in research_rows if str(row.get("claim_map_path") or "").strip()),
                    "revision_artifacts": sum(1 for row in research_rows if str(row.get("revision_summary_path") or "").strip()),
                }
            )
            notes.append(
                "research_quality: "
                f"claim={telemetry['avg_claim_coverage']:.2f} "
                f"critical={telemetry['avg_critical_claim_coverage']:.2f} "
                f"uncertainty_max={telemetry['max_uncertainty_count']}"
            )
            if status == "success" and failed_research_gates:
                status = "partial"
                notes.append("completion_gate: research_gates_failed")
        # Pull a compact message digest for final lead summary.
        digest = []
        for _ in range(20):
            msg = await self.bus.receive("lead", timeout=1)
            if msg is None:
                break
            digest.append(str(msg.body))
        if digest:
            notes.append("messages: " + " | ".join(digest[:8]))
        logger.info(summary)
        if research_rows:
            summary += (
                f" | research_claim={telemetry.get('avg_claim_coverage', 0.0):.2f}"
                f" critical={telemetry.get('avg_critical_claim_coverage', 0.0):.2f}"
                f" uncertainty_max={int(telemetry.get('max_uncertainty_count', 0) or 0)}"
            )
        if telemetry.get("plan_progress"):
            summary += (
                f" | workflow={telemetry.get('workflow_profile') or '-'}"
                f" plan={telemetry.get('plan_progress')}"
                f" review={telemetry.get('review_status') or '-'}"
            )
        if telemetry.get("packet_count"):
            summary += (
                f" | packets={int(telemetry.get('packet_count') or 0)}"
                f" waves={int(telemetry.get('parallel_waves') or 0)}"
                f" conflicts={int(telemetry.get('ownership_conflicts') or 0)}"
            )
        return TeamResult(status=status, summary=summary, outputs=outputs, notes=notes, telemetry=telemetry)


__all__ = ["TeamConfig", "TeamResult", "AgentTeam"]
