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
        if a in {"write_file", "take_screenshot", "write_word", "write_excel"}:
            gates.extend(["file_exists", "file_not_empty"])

        path = str((params or {}).get("path") or "").lower()
        if path.endswith(".json"):
            gates.append("valid_json")
        elif path.endswith(".html"):
            gates.append("valid_html")
        elif path.endswith(".py"):
            gates.append("valid_python")
        gates.append("tool_success")
        return self._dedupe(gates)

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

    async def _build_team_tasks(self, brief: str) -> Tuple[List[TeamTask], Dict[str, Any]]:
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
                }
            )
        return outputs

    async def execute_project(self, brief: str) -> TeamResult:
        manager = SubAgentManager(
            self.agent,
            parent_session_id="team",
            tool_scopes=DEFAULT_TOOL_SCOPES,
        )

        lead_task = SubAgentTask(
            name="Lead Plan",
            action="chat",
            params={"message": f"Görevi kısa planla, bağımlılıkları ve riskleri belirt: {brief}"},
            description=brief,
            domain="planning",
        )
        lead_result = await manager.spawn_and_wait("lead", lead_task, timeout=min(120, self.config.timeout_s))
        lead_summary = str(lead_result.result or "")

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
        return TeamResult(status=status, summary=summary, outputs=outputs, notes=notes)


__all__ = ["TeamConfig", "TeamResult", "AgentTeam"]
