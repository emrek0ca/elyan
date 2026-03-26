"""
Intelligent Task Planning & Multi-Step Execution
Advanced task decomposition, dependency management, parallel execution
"""

import asyncio
import json
import time
import uuid
from typing import Dict, List, Optional, Any, Set, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque

from utils.logger import get_logger
from core.spec.extractors import get_domain_fewshot

logger = get_logger("intelligent_planner")


KNOWN_TOOL_ACTIONS: Set[str] = {
    "open_url",
    "open_app",
    "close_app",
    "advanced_research",
    "deep_research",
    "web_search",
    "read_file",
    "write_file",
    "list_files",
    "search_files",
    "create_folder",
    "delete_file",
    "move_file",
    "copy_file",
    "rename_file",
    "take_screenshot",
    "type_text",
    "press_key",
    "key_combo",
    "mouse_move",
    "mouse_click",
    "computer_use",
    "run_safe_command",
    "execute_python_code",
    "execute_shell_command",
    "write_word",
    "write_excel",
    "generate_document_pack",
    "research_document_delivery",
    "create_web_project_scaffold",
    "create_software_project_pack",
    "create_coding_delivery_plan",
    "create_coding_verification_report",
    "open_project_in_ide",
    "send_email",
    "analyze_document",
    "generate_report",
    "http_request",
    "graphql_query",
    "api_health_check",
    "browser_open",
    "browser_click",
    "browser_type",
    "browser_screenshot",
    "create_directory",
    "list_directory",
    "create_visual_asset_pack",
    "transcribe_audio_file",
    "speak_text_local",
    "analyze_and_narrate_image",
    "chat",
}

ACTION_ALIASES: Dict[str, str] = {
    "research": "advanced_research",
    "deep_research": "advanced_research",
    "internet_research": "advanced_research",
    "browser_search": "web_search",
    "search_web": "web_search",
    "create_word_document": "write_word",
    "create_excel": "write_excel",
    "create_website": "create_web_project_scaffold",
    "status_snapshot": "take_screenshot",
    "run_command": "run_safe_command",
    "execute_python": "execute_python_code",
    "execute_code": "execute_python_code",
    "terminal_command": "run_safe_command",
    "create_directory": "create_folder",
    "list_directory": "list_files",
    "api_call": "http_request",
    "make_request": "http_request",
    "request_api": "http_request",
    "check_api": "api_health_check",
    "api_check": "api_health_check",
}

# Domain → LLM role mapping for role-aware LLM selection
_DOMAIN_TO_ROLE: Dict[str, str] = {
    "code": "code",
    "research": "research_worker",
    "api": "code_worker",
    "office": "reasoning",
    "automation": "code_worker",
    "filesystem": "reasoning",
}


class TaskPriority(Enum):
    """Task execution priority"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class TaskState(Enum):
    """Task execution state"""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


@dataclass
class ExecutionContext:
    """Context for task execution"""
    variables: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubTask:
    """Represents a decomposed sub-task"""
    task_id: str
    name: str
    action: str
    params: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    priority: TaskPriority = TaskPriority.NORMAL
    state: TaskState = TaskState.PENDING
    retry_count: int = 0
    max_retries: int = 3
    result: Optional[Any] = None
    error: Optional[str] = None
    rollback_action: Optional[Callable] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    estimated_duration: float = 10.0  # seconds


@dataclass
class ExecutionPlan:
    """Complete execution plan for a complex task"""
    plan_id: str
    description: str
    subtasks: List[SubTask]
    context: ExecutionContext = field(default_factory=ExecutionContext)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    total_duration: float = 0.0
    success: bool = False


class IntelligentPlanner:
    """
    Intelligent Task Planning & Execution System
    - Decomposes complex tasks into subtasks
    - Manages dependencies
    - Executes tasks in parallel where possible
    - Supports rollback on failure
    - Tracks progress and estimates completion
    """

    def __init__(self):
        self.active_plans: Dict[str, ExecutionPlan] = {}
        self.plan_history: deque = deque(maxlen=100)
        self.executor_pool_size = 4
        self.progress_callbacks: List[Callable] = []
        from core.llm_client import LLMClient
        self.llm = LLMClient()
        # Cost-guard defaults (overridable via TaskEngine)
        self.use_llm = True
        self.max_subtasks = 10
        try:
            from config.elyan_config import elyan_config

            self.use_llm = bool(elyan_config.get("agent.planning.use_llm", True))
            self.max_subtasks = int(elyan_config.get("agent.planning.max_subtasks", 10) or 10)
            self.max_subtasks = max(1, min(20, self.max_subtasks))
        except Exception:
            self.use_llm = True
            self.max_subtasks = 10

        logger.info("Intelligent Planner initialized")

    def register_progress_callback(self, callback: Callable):
        """Register callback for progress updates"""
        self.progress_callbacks.append(callback)

    @staticmethod
    def _infer_domain_from_request(
        task_description: str,
        preferred_tools: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        domain = ""
        if isinstance(context, dict):
            goal_graph = context.get("goal_graph", {})
            if isinstance(goal_graph, dict):
                domain = str(goal_graph.get("domain", "") or "").strip().lower()
        if domain:
            return domain

        tools = {str(t or "").strip().lower() for t in (preferred_tools or []) if str(t or "").strip()}
        low_desc = str(task_description or "").lower()

        if tools.intersection({"api_health_check", "http_request", "graphql_query"}) or any(
            k in low_desc for k in ("api", "endpoint", "graphql", "rest", "webhook", "http")
        ):
            return "api"
        if tools.intersection({"advanced_research", "deep_research", "generate_report"}) or any(
            k in low_desc for k in ("araştır", "arastir", "research", "literature", "kaynak", "analiz")
        ):
            return "research"
        if tools.intersection({"create_software_project_pack", "execute_python_code", "run_safe_command"}) or any(
            k in low_desc for k in ("kod", "code", "python", "backend", "frontend", "repo", "test", "build")
        ):
            return "code"
        if tools.intersection({"write_word", "write_excel", "analyze_document"}) or any(
            k in low_desc for k in ("rapor", "belge", "doküman", "dokuman", "excel", "word", "sunum")
        ):
            return "office"
        if any(k in low_desc for k in ("otomasyon", "automation", "cron", "schedule", "zamanla", "her gün", "her gun")):
            return "automation"
        if tools.intersection({"create_folder", "write_file", "read_file", "list_files"}) or any(
            k in low_desc for k in ("dosya", "klasör", "klasor", "folder", "file", "masaüstü", "masaustu")
        ):
            return "filesystem"
        return ""

    async def decompose_task(
        self,
        task_description: str,
        llm_client=None,
        context: Optional[Dict[str, Any]] = None,
        use_llm: bool = True,
        user_id: str = "local",
        preferred_tools: Optional[List[str]] = None,
        llm_role: str = "planning"
    ) -> List[SubTask]:
        """
        Decompose a complex task into executable subtasks
        Uses LLM for intelligent decomposition
        """
        client = llm_client or self.llm
        subtasks: List[SubTask] = []

        # LLM-assisted decomposition first
        if use_llm and client:
            try:
                # Determine effective role based on domain
                domain = self._infer_domain_from_request(
                    task_description,
                    preferred_tools=preferred_tools,
                    context=context,
                )
                effective_role = _DOMAIN_TO_ROLE.get(domain, llm_role)

                context_hint = self._format_context_for_planner(context or {})
                pref_hint = f"\nPreferred tools for this domain: {', '.join(preferred_tools)}" if preferred_tools else ""
                json_contract = (
                    "\nELYAN CORE OBJECTIVE:\n"
                    "- Kullanıcıyı doğru anla, hedefi eksiksiz sıraya koy, hatasız uygulanabilir adımlar üret.\n"
                    "- Sohbet/öneri değil; yalnızca çalıştırılabilir görev adımları üret.\n"
                    "\nCRITICAL OUTPUT CONTRACT:\n"
                    "- SADECE JSON dizi döndür.\n"
                    "- Markdown, açıklama, başlık, code fence kullanma.\n"
                    "- Her adım şu alanları içermeli: id, name, action, params, depends_on.\n"
                    "- action değeri çalıştırılabilir tool adı olmalı.\n"
                    "- Her adım bir önceki adımla mantıksal olarak tutarlı olmalı.\n"
                )
                fewshot_hint = ""
                fewshots = get_domain_fewshot(domain)
                if fewshots:
                    rows = []
                    for item in fewshots[:2]:
                        user = str(item.get("user", "")).strip()
                        intent = str(item.get("intent", "")).strip()
                        step_actions = [
                            str(s.get("action") or "").strip()
                            for s in (item.get("steps", []) or [])
                            if isinstance(s, dict) and str(s.get("action") or "").strip()
                        ]
                        step_chain = " -> ".join(step_actions[:6]) if step_actions else "n/a"
                        if user:
                            rows.append(
                                f"- User: {user} | intent={intent or 'n/a'} | actions={step_chain}"
                            )
                    if rows:
                        fewshot_hint = "\nDomain few-shot:\n" + "\n".join(rows)

                low_desc = str(task_description or "").lower()
                web_mode = "create_web_project_scaffold" in (preferred_tools or []) or any(
                    k in low_desc for k in ("web", "website", "site", "landing", "html", "frontend")
                )
                api_mode = any(
                    k in low_desc for k in ("api", "endpoint", "graphql", "webhook", "rest", "http")
                ) or any(t in (preferred_tools or []) for t in ("http_request", "graphql_query", "api_health_check"))
                code_mode = any(
                    k in low_desc for k in ("code", "kod", "script", "python", "backend", "program")
                ) or any(t in (preferred_tools or []) for t in ("create_software_project_pack", "execute_python_code"))

                if web_mode:
                    prompt = f"""Goal: {task_description}

Plan 6-12 executable steps. Use valid actions:
- create_web_project_scaffold: Web projesi olustur (params: project_name, stack, theme, output_dir, brief)
- write_file: Dosya yaz (params: path, content)
- run_safe_command: smoke/test komutu calistir (params: command)
- read_file: dogrulama ve kalite kontrol dosyalarini oku (params: path)
- take_screenshot: Ekran goruntusu al{pref_hint}

The FIRST step MUST use create_web_project_scaffold.
Mandatory phases:
1) scaffold
2) component/section implementation
3) styling and responsive improvements
4) interaction/animation enhancement
5) verification (run_safe_command/read_file)
6) artifact proof (screenshot/report)
Steps should be execution-ready, dependency-safe and non-trivial.
Return JSON array:
[{{"id":"task_1","name":"...","action":"create_web_project_scaffold","params":{{"project_name":"...","stack":"vanilla","theme":"professional","output_dir":"~/Desktop","brief":"..."}}, "depends_on":[]}}]
"""
                elif api_mode:
                    prompt = f"""Goal: {task_description}

Plan 3-6 executable steps. Use valid actions:
- http_request: API request at (params: method, url, headers, body, timeout)
- graphql_query: GraphQL sorgu (params: url, query, variables, headers)
- api_health_check: Endpoint health (params: url, timeout)
- write_file: Sonuclari dosyaya kaydet (params: path, content){pref_hint}

Rules:
- Start with api_health_check OR a safe GET request.
- Include at least one validation/reporting step.
- Ensure each step has valid params and deterministic execution order.
Return JSON array only.
"""
                elif code_mode:
                    prompt = f"""Goal: {task_description}

Plan 7-14 executable steps. Use valid actions:
- create_software_project_pack (project_name, project_type, stack, complexity, output_dir, brief)
- write_file (path, content)
- execute_python_code or run_safe_command for verification
- read_file for QA/checkpoint{pref_hint}

Mandatory phases:
1) project pack creation
2) domain models + core modules
3) service/controller or CLI layer
4) tests (unit and integration)
5) lint/typecheck/test verification
6) docs/runbook updates
The plan must include at least two verification steps before finalization.
Keep dependencies acyclic and execution-safe.
Return JSON array only.
"""
                else:
                    prompt = f"""Goal: {task_description}

Plan 3-10 executable steps. Use valid actions (open_url, advanced_research, read_file, write_file, take_screenshot, create_folder, list_files, run_safe_command, send_email, analyze_document, web_search, generate_report).{pref_hint}
Rules: avoid chat-like actions, produce deterministic step order, fill critical params.
Return JSON array:
[{{"id":"task_1","name":"...","action":"tool","params":{{"path":"~/Desktop"}},"depends_on":[]}}]
"""
                prompt += json_contract
                if fewshot_hint:
                    prompt += fewshot_hint
                if context_hint:
                    prompt += f"\nContext: {context_hint}"

                resp = await client.generate(prompt, max_tokens=600, user_id=user_id, role=effective_role)
                subtasks = self._parse_subtasks_from_response(resp, task_description, limit=self.max_subtasks)

                # LLM serbest metin döndürürse ikinci pas: metni JSON'a zorla.
                if not subtasks:
                    salvage_prompt = (
                        "Aşağıdaki metni yürütülebilir görev planı JSON dizisine dönüştür.\n"
                        "Sadece JSON döndür. Format: [{id,name,action,params,depends_on}].\n\n"
                        f"Metin:\n{resp}"
                    )
                    salvage_resp = await client.generate(salvage_prompt, max_tokens=500, user_id=user_id, role=effective_role)
                    subtasks = self._parse_subtasks_from_response(salvage_resp, task_description, limit=self.max_subtasks)
            except Exception as e:
                logger.debug(f"LLM decomposition failed, fallback heuristic: {e}")

        # Heuristic fallback
        if not subtasks:
            if "ve" in task_description or "sonra" in task_description:
                parts = task_description.replace(" sonra ", " ve ").split(" ve ")
                for i, part in enumerate(parts):
                    subtasks.append(SubTask(
                        task_id=f"subtask_{i+1}",
                        name=part.strip(),
                        action=self._infer_action(part.strip()),
                        params={},
                        dependencies=[f"subtask_{i}"] if i > 0 else [],
                        priority=TaskPriority.NORMAL
                    ))
            else:
                subtasks.append(SubTask(
                    task_id="subtask_1",
                    name=task_description,
                    action=self._infer_action(task_description),
                    params={},
                    priority=TaskPriority.NORMAL
                ))

        subtasks = self._sanitize_subtasks(subtasks, task_description)
        logger.info(f"Decomposed task into {len(subtasks)} subtasks")
        return subtasks

    def _parse_subtasks_from_response(self, response_text: str, task_description: str, limit: int = 10) -> List[SubTask]:
        subtasks: List[SubTask] = []
        payload = self._extract_first_json_payload(response_text)
        actions: list[Any] = []
        if isinstance(payload, list):
            actions = payload
        elif isinstance(payload, dict):
            for key in ("steps", "tasks", "subtasks", "plan"):
                value = payload.get(key)
                if isinstance(value, list):
                    actions = value
                    break
        if not actions:
            return subtasks

        for i, a in enumerate(actions[:limit]):
            if not isinstance(a, dict):
                continue
            action = str(a.get("action", "")).split("(")[0].strip() or self._infer_action(task_description)
            deps = a.get("depends_on", []) or a.get("dependencies", [])
            if isinstance(deps, str):
                deps = [deps]
            if not isinstance(deps, list):
                deps = []
            subtasks.append(
                SubTask(
                    task_id=str(a.get("id", f"subtask_{i+1}")),
                    name=str(a.get("name", f"Adim {i+1}")),
                    action=action,
                    params=a.get("params", {}) if isinstance(a.get("params", {}), dict) else {},
                    dependencies=[str(d) for d in deps if str(d).strip()],
                    priority=TaskPriority.NORMAL,
                )
            )
        return self._sanitize_subtasks(subtasks, task_description)

    @staticmethod
    def _extract_first_json_payload(response_text: str) -> Any:
        import re

        raw = str(response_text or "").strip()
        if not raw:
            return None

        candidates: list[str] = [raw]
        fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
        for block in fenced:
            s = str(block or "").strip()
            if s:
                candidates.append(s)

        decoder = json.JSONDecoder()
        for chunk in candidates:
            probe = chunk.strip()
            if probe.lower().startswith("json"):
                probe = probe[4:].strip()
            try:
                parsed = json.loads(probe)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except Exception:
                pass
            for idx, ch in enumerate(probe):
                if ch not in "{[":
                    continue
                try:
                    parsed, _end = decoder.raw_decode(probe[idx:])
                    if isinstance(parsed, (dict, list)):
                        return parsed
                except Exception:
                    continue
        return None

    def _normalize_action_name(self, action: str, *, fallback_text: str = "") -> str:
        raw = str(action or "").split("(")[0].strip().lower()
        if not raw:
            return self._infer_action(fallback_text or "")
        mapped = ACTION_ALIASES.get(raw, raw)
        if mapped in KNOWN_TOOL_ACTIONS:
            return mapped
        inferred = self._infer_action(fallback_text or mapped)
        inferred_mapped = ACTION_ALIASES.get(inferred, inferred)
        if inferred_mapped in KNOWN_TOOL_ACTIONS:
            return inferred_mapped
        return mapped

    def _sanitize_subtask_params(self, action: str, params: Dict[str, Any], *, name: str = "", goal: str = "") -> Dict[str, Any]:
        cleaned = dict(params or {})
        hint = str(name or goal or "").strip() or "görev"

        if action == "open_url" and not str(cleaned.get("url", "")).strip():
            query = str(hint).replace("\n", " ").strip()
            cleaned["url"] = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        elif action == "web_search" and not str(cleaned.get("query", "")).strip():
            cleaned["query"] = hint
            cleaned.setdefault("num_results", 5)
        elif action == "advanced_research" and not str(cleaned.get("topic", "")).strip():
            cleaned["topic"] = hint
            cleaned.setdefault("depth", "standard")
        elif action == "deep_research" and not str(cleaned.get("topic", "")).strip():
            cleaned["topic"] = hint
            cleaned.setdefault("depth", "comprehensive")
        elif action == "read_file" and not str(cleaned.get("path", "")).strip():
            cleaned["path"] = "~/Desktop/not.txt"
        elif action == "write_file":
            if not str(cleaned.get("path", "")).strip():
                cleaned["path"] = "~/Desktop/not.txt"
            if not str(cleaned.get("content", "")).strip():
                cleaned["content"] = str(goal or hint).strip()
        elif action == "list_files" and not str(cleaned.get("path", "")).strip():
            cleaned["path"] = "~/Desktop"
        elif action == "list_directory" and not str(cleaned.get("path", "")).strip():
            cleaned["path"] = "~/Desktop"
        elif action == "create_folder" and not str(cleaned.get("path", "")).strip():
            cleaned["path"] = "~/Desktop/yeni_klasor"
        elif action == "create_directory" and not str(cleaned.get("path", "")).strip():
            cleaned["path"] = "~/Desktop/yeni_klasor"
        elif action == "move_file":
            if not str(cleaned.get("source", "")).strip():
                cleaned["source"] = "~/Desktop/not.txt"
            if not str(cleaned.get("destination", "")).strip():
                cleaned["destination"] = "~/Desktop"
        elif action == "copy_file":
            if not str(cleaned.get("source", "")).strip():
                cleaned["source"] = "~/Desktop/not.txt"
            if not str(cleaned.get("destination", "")).strip():
                cleaned["destination"] = "~/Desktop"
        elif action == "delete_file" and not str(cleaned.get("path", "")).strip():
            cleaned["path"] = "~/Desktop/not.txt"
            cleaned.setdefault("force", False)
        elif action == "write_word":
            if not str(cleaned.get("path", "")).strip():
                cleaned["path"] = "~/Desktop/belge.docx"
            if not str(cleaned.get("content", "")).strip():
                cleaned["content"] = str(goal or hint).strip()
        elif action == "write_excel":
            if not str(cleaned.get("path", "")).strip():
                cleaned["path"] = "~/Desktop/tablo.xlsx"
            if not cleaned.get("data"):
                cleaned["data"] = [{"Veri": str(goal or hint).strip()}]
            cleaned.setdefault("headers", ["Veri"])
        elif action == "edit_text_file":
            if not str(cleaned.get("path", "")).strip():
                cleaned["path"] = "~/Desktop/not.md"
            ops = cleaned.get("operations")
            if not isinstance(ops, list) or not ops:
                cleaned["operations"] = [{"type": "append", "text": str(goal or hint).strip() or "guncelleme"}]
            cleaned.setdefault("create_backup", True)
        elif action == "batch_edit_text":
            if not str(cleaned.get("directory", "")).strip():
                cleaned["directory"] = "~/Desktop"
            if not str(cleaned.get("pattern", "")).strip():
                cleaned["pattern"] = "*.md"
            ops = cleaned.get("operations")
            if not isinstance(ops, list) or not ops:
                cleaned["operations"] = [{"type": "append", "text": str(goal or hint).strip() or "guncelleme"}]
            cleaned.setdefault("create_backup", True)
        elif action == "edit_word_document":
            if not str(cleaned.get("path", "")).strip():
                cleaned["path"] = "~/Desktop/belge.docx"
            ops = cleaned.get("operations")
            if not isinstance(ops, list) or not ops:
                cleaned["operations"] = [{"type": "add_paragraph", "text": str(goal or hint).strip() or "guncelleme"}]
            cleaned.setdefault("create_backup", True)
        elif action == "summarize_document":
            if not str(cleaned.get("path", "")).strip() and not str(cleaned.get("content", "")).strip():
                cleaned["path"] = "~/Desktop/not.md"
            style = str(cleaned.get("style", "")).strip().lower()
            if style not in {"brief", "detailed", "bullets"}:
                cleaned["style"] = "brief"
        elif action == "analyze_document":
            if not str(cleaned.get("path", "")).strip():
                cleaned["path"] = "~/Desktop/not.md"
        elif action == "create_web_project_scaffold":
            cleaned.setdefault("project_name", "web-projesi")
            cleaned.setdefault("stack", "vanilla")
            cleaned.setdefault("theme", "professional")
            cleaned.setdefault("output_dir", "~/Desktop")
            cleaned.setdefault("brief", str(goal or hint).strip())
        elif action == "create_software_project_pack":
            cleaned.setdefault("project_name", "uygulama-projesi")
            cleaned.setdefault("project_type", "app")
            cleaned.setdefault("stack", "python")
            cleaned.setdefault("complexity", "advanced")
            cleaned.setdefault("output_dir", "~/Desktop")
            cleaned.setdefault("brief", str(goal or hint).strip())
        elif action == "research_document_delivery":
            cleaned.setdefault("topic", str(goal or hint).strip() or "genel konu")
            cleaned.setdefault("depth", "comprehensive")
            cleaned.setdefault("output_dir", "~/Desktop")
            cleaned.setdefault("include_word", True)
            cleaned.setdefault("include_excel", False)
            cleaned.setdefault("include_report", True)
        elif action == "http_request":
            cleaned.setdefault("method", "GET")
            if not str(cleaned.get("url", "")).strip():
                query = str(hint).replace("\n", " ").strip()
                cleaned["url"] = f"https://api.duckduckgo.com/?q={query.replace(' ', '+')}&format=json"
            if not isinstance(cleaned.get("headers"), dict):
                cleaned["headers"] = {"Accept": "application/json"}
            cleaned.setdefault("timeout", 15)
        elif action == "graphql_query":
            if not str(cleaned.get("url", "")).strip():
                cleaned["url"] = "https://countries.trevorblades.com/"
            if not str(cleaned.get("query", "")).strip():
                cleaned["query"] = "{ __typename }"
            if not isinstance(cleaned.get("variables"), dict):
                cleaned["variables"] = {}
            if not isinstance(cleaned.get("headers"), dict):
                cleaned["headers"] = {}
            cleaned.setdefault("timeout", 15)
        elif action == "api_health_check":
            if not str(cleaned.get("url", "")).strip():
                cleaned["url"] = "https://httpbin.org/get"
            cleaned.setdefault("timeout", 10)
        elif action == "execute_python_code" and not str(cleaned.get("code", "")).strip():
            cleaned["code"] = "print('ok')"
        elif action == "execute_shell_command" and not str(cleaned.get("command", "")).strip():
            cleaned["command"] = "echo ok"
        elif action == "type_text":
            if not str(cleaned.get("text", "")).strip():
                cleaned["text"] = str(goal or hint).strip() or "test"
            cleaned.setdefault("press_enter", False)
        elif action == "press_key":
            if not str(cleaned.get("key", "")).strip():
                cleaned["key"] = "enter"
            if not isinstance(cleaned.get("modifiers"), list):
                cleaned["modifiers"] = []
        elif action == "key_combo":
            if not str(cleaned.get("combo", "")).strip():
                cleaned["combo"] = "cmd+l"
        elif action == "mouse_move":
            cleaned.setdefault("x", 960)
            cleaned.setdefault("y", 540)
        elif action == "mouse_click":
            cleaned.setdefault("x", 960)
            cleaned.setdefault("y", 540)
            cleaned.setdefault("button", "left")
            cleaned.setdefault("double", False)
        elif action == "computer_use":
            steps = cleaned.get("steps")
            if not isinstance(steps, list) or not steps:
                cleaned["steps"] = [
                    {"action": "open_app", "params": {"app_name": "Safari"}},
                    {"action": "open_url", "params": {"url": "https://www.google.com", "browser": "Safari"}},
                ]
            cleaned.setdefault("final_screenshot", True)
            cleaned.setdefault("pause_ms", 200)

        return cleaned

    def _sanitize_subtasks(self, subtasks: List[SubTask], goal: str) -> List[SubTask]:
        if not subtasks:
            return [
                SubTask(
                    task_id="subtask_1",
                    name=str(goal or "görev"),
                    action=self._normalize_action_name("", fallback_text=goal),
                    params=self._sanitize_subtask_params(
                        self._normalize_action_name("", fallback_text=goal),
                        {},
                        name=str(goal or "görev"),
                        goal=goal,
                    ),
                )
            ]

        normalized: List[SubTask] = []
        id_map: Dict[str, str] = {}
        used_ids: Set[str] = set()

        # Pass 1: normalize identity/action/params.
        for idx, task in enumerate(subtasks[: self.max_subtasks], start=1):
            old_id = str(getattr(task, "task_id", "") or f"subtask_{idx}")
            new_id = old_id.strip() or f"subtask_{idx}"
            if new_id in used_ids:
                new_id = f"subtask_{idx}"
                while new_id in used_ids:
                    idx2 = len(used_ids) + 1
                    new_id = f"subtask_{idx2}"
            used_ids.add(new_id)
            id_map[old_id] = new_id

            raw_name = str(getattr(task, "name", "") or f"Adım {idx}")
            norm_action = self._normalize_action_name(
                str(getattr(task, "action", "") or ""),
                fallback_text=f"{raw_name} {goal}",
            )
            norm_params = self._sanitize_subtask_params(
                norm_action,
                getattr(task, "params", {}) if isinstance(getattr(task, "params", {}), dict) else {},
                name=raw_name,
                goal=goal,
            )

            normalized.append(
                SubTask(
                    task_id=new_id,
                    name=raw_name,
                    action=norm_action,
                    params=norm_params,
                    dependencies=list(getattr(task, "dependencies", []) or []),
                    priority=getattr(task, "priority", TaskPriority.NORMAL),
                    max_retries=getattr(task, "max_retries", 3),
                    estimated_duration=float(getattr(task, "estimated_duration", 10.0) or 10.0),
                )
            )

        # Pass 2: sanitize dependencies (only previous known ids, no self-ref).
        known = {t.task_id for t in normalized}
        for idx, task in enumerate(normalized):
            valid_deps: List[str] = []
            for dep in list(task.dependencies or []):
                dep_key = str(dep).strip()
                if not dep_key:
                    continue
                dep_norm = id_map.get(dep_key, dep_key)
                if dep_norm == task.task_id or dep_norm not in known:
                    continue
                # forward-dependency risk: keep only dependencies that appear before this step
                dep_pos = next((i for i, st in enumerate(normalized) if st.task_id == dep_norm), -1)
                if dep_pos >= idx:
                    continue
                if dep_norm not in valid_deps:
                    valid_deps.append(dep_norm)
            task.dependencies = valid_deps

        # If planner returned no dependencies for a multi-step plan, force linear order.
        if len(normalized) > 1 and not any(t.dependencies for t in normalized):
            for idx in range(1, len(normalized)):
                normalized[idx].dependencies = [normalized[idx - 1].task_id]

        if not any(t.action != "chat" for t in normalized):
            normalized[0].action = self._normalize_action_name("", fallback_text=goal)
            normalized[0].params = self._sanitize_subtask_params(
                normalized[0].action,
                normalized[0].params,
                name=normalized[0].name,
                goal=goal,
            )

        return normalized

    def _format_context_for_planner(self, context: Dict[str, Any]) -> str:
        if not context:
            return ""
        segments: list[str] = []
        profile = context.get("user_profile") or {}
        if isinstance(profile, dict) and profile:
            pref_lang = profile.get("preferred_language", "auto")
            top_topics = ", ".join(profile.get("top_topics", [])[:5])
            top_actions = ", ".join(profile.get("top_actions", [])[:5])
            segments.append(f"user_profile.language={pref_lang}")
            if top_topics:
                segments.append(f"user_profile.top_topics={top_topics}")
            if top_actions:
                segments.append(f"user_profile.top_actions={top_actions}")

        prefs = context.get("user_preferences") or {}
        if isinstance(prefs, dict):
            lang = prefs.get("preferred_language")
            if lang:
                segments.append(f"user_preferences.preferred_language={lang}")

        formatted = context.get("formatted_context")
        if formatted:
            segments.append(f"recent_context={str(formatted)[:300]}")
        requirements = context.get("execution_requirements")
        if isinstance(requirements, dict) and requirements:
            req = ",".join(f"{k}={v}" for k, v in requirements.items())
            segments.append(f"execution_requirements={req[:200]}")
        return " | ".join(segments)

    def evaluate_plan_quality(self, subtasks: List[SubTask], goal: str = "") -> Dict[str, Any]:
        """Score plan quality before execution."""
        if not subtasks:
            return {"score": 0.0, "issues": ["no_subtasks"], "safe_to_run": False}

        issues: List[str] = []
        score = 1.0

        # 1) Action validity
        chat_count = sum(1 for t in subtasks if t.action == "chat")
        if chat_count == len(subtasks):
            issues.append("all_chat_actions")
            score -= 0.5
        elif chat_count > 0:
            issues.append("contains_chat_actions")
            score -= 0.15

        unknown_actions = [t.action for t in subtasks if str(t.action or "").strip() not in KNOWN_TOOL_ACTIONS]
        if unknown_actions:
            issues.append(f"unknown_actions:{','.join(sorted(set(unknown_actions))[:5])}")
            score -= min(0.35, 0.08 * len(set(unknown_actions)))

        # 2) Dependency sanity
        known_ids = {t.task_id for t in subtasks}
        for t in subtasks:
            for dep in t.dependencies:
                if dep not in known_ids:
                    issues.append("invalid_dependency")
                    score -= 0.1
                    break

        # 3) Parameter completeness for common risky actions
        required_keys = {
            "open_url": ("url",),
            "write_file": ("path",),
            "read_file": ("path",),
            "delete_file": ("path",),
            "move_file": ("source", "destination"),
            "copy_file": ("source", "destination"),
            "http_request": ("url", "method"),
            "graphql_query": ("url", "query"),
            "api_health_check": ("url",),
        }
        for t in subtasks:
            req = required_keys.get(t.action)
            if not req:
                continue
            missing = [k for k in req if not str(t.params.get(k, "")).strip()]
            if missing:
                issues.append(f"missing_params:{t.task_id}:{','.join(missing)}")
                score -= 0.1

        # 4) Overly long plan heuristic
        if len(subtasks) > self.max_subtasks:
            issues.append("too_many_steps")
            score -= 0.1

        # 5) Repeated redundant actions (likely hallucinated loops)
        repeated_pairs = 0
        for i in range(1, len(subtasks)):
            prev = subtasks[i - 1]
            cur = subtasks[i]
            if prev.action == cur.action and prev.params == cur.params:
                repeated_pairs += 1
        if repeated_pairs > 0:
            issues.append("repeated_redundant_steps")
            score -= min(0.2, repeated_pairs * 0.06)

        score = max(0.0, min(1.0, score))
        safe_to_run = score >= 0.60 and "all_chat_actions" not in issues and not unknown_actions
        return {"score": score, "issues": issues, "safe_to_run": safe_to_run}

    async def revise_plan(
        self,
        goal: str,
        *,
        current_subtasks: List[SubTask],
        context: Optional[Dict[str, Any]] = None,
        failure_feedback: str = "",
        llm_client=None,
        use_llm: bool = True,
        user_id: str = "local"
    ) -> List[SubTask]:
        """Try a second-pass plan synthesis using failure feedback."""
        if not use_llm:
            return current_subtasks
        client = llm_client or self.llm
        if not client:
            return current_subtasks

        try:
            compact_plan = [
                {
                    "id": s.task_id,
                    "action": s.action,
                    "params": s.params,
                    "depends_on": s.dependencies,
                }
                for s in current_subtasks[:10]
            ]
            context_hint = self._format_context_for_planner(context or {})
            prompt = (
                f"Goal: {goal}\n"
                f"Current Plan JSON: {compact_plan}\n"
                f"Failure Feedback: {failure_feedback or 'quality_issues'}\n"
                "Revise this plan for higher success probability.\n"
                "Rules: use only valid tool-like actions, keep dependencies valid, fill required params.\n"
                "Return JSON array only."
            )
            if context_hint:
                prompt += f"\nContext: {context_hint}"

            resp = await client.generate(prompt, max_tokens=650, user_id=user_id, role="planning")
            revised = self._parse_subtasks_from_response(resp, goal, limit=self.max_subtasks)
            if revised:
                return self._sanitize_subtasks(revised, goal)
        except Exception as exc:
            logger.debug(f"Plan revision failed: {exc}")
        return self._sanitize_subtasks(current_subtasks, goal)

    def _infer_action(self, task_text: str) -> str:
        """Infer action from task text"""
        text_lower = task_text.lower()

        # Deterministic keyword mapping for planner fallback.
        action_map = {
            "oku": "read_file",
            "yaz": "write_file",
            "kaydet": "write_file",
            "sil": "delete_file",
            "düzenle": "edit_text_file",
            "duzenle": "edit_text_file",
            "değiştir": "edit_text_file",
            "degistir": "edit_text_file",
            "özet": "summarize_document",
            "ozet": "summarize_document",
            "taşı": "move_file",
            "tasi": "move_file",
            "kopyala": "copy_file",
            "aç": "open_app",
            "ac": "open_app",
            "kapat": "close_app",
            "araştır": "advanced_research",
            "arastir": "advanced_research",
            "ara": "web_search",
            "search": "web_search",
            "api": "http_request",
            "endpoint": "http_request",
            "graphql": "graphql_query",
            "webhook": "http_request",
            "http": "http_request",
            "curl": "http_request",
            "youtube": "open_url",
            "çal": "open_url",
            "cal": "open_url",
            "play": "open_url",
            "google": "open_url",
            "safari": "open_url",
            "site": "write_file",
            "html": "write_file",
            "klasör": "create_folder",
            "klasor": "create_folder",
            "listele": "list_files",
            "göster": "list_files",
            "goster": "list_files",
            "screenshot": "take_screenshot",
            "ekran": "take_screenshot",
            "tıkla": "mouse_click",
            "tikla": "mouse_click",
            "mouse": "mouse_move",
            "klavye": "type_text",
            "tuş": "press_key",
            "tus": "press_key",
            "otomasyon": "computer_use",
            "adım": "computer_use",
            "adim": "computer_use",
            "görsel": "create_visual_asset_pack",
            "gorsel": "create_visual_asset_pack",
            "image": "create_visual_asset_pack",
            "logo": "create_visual_asset_pack",
            "tasarla": "create_visual_asset_pack",
        }

        for keyword, action in action_map.items():
            if keyword in text_lower:
                return action

        if "http" in text_lower or ".com" in text_lower or ".org" in text_lower:
            return "open_url"

        # Last-resort fallback should never become a non-tool hallucination.
        return "chat"

    async def create_plan(
        self,
        description: str,
        subtasks: Optional[List[SubTask]] = None,
        llm_client=None,
        context: Optional[Dict[str, Any]] = None,
        use_llm: bool = True,
        user_id: str = "local",
        preferred_tools: Optional[List[str]] = None
    ) -> ExecutionPlan:
        """Create and return an execution plan (returns the plan object)."""
        plan_id = str(uuid.uuid4())[:8]

        if not subtasks:
            # Decompose automatically
            subtasks = await self.decompose_task(
                description,
                llm_client,
                context=context,
                use_llm=use_llm and self.use_llm,
                user_id=user_id,
                preferred_tools=preferred_tools
            )
        else:
            subtasks = self._sanitize_subtasks(subtasks, description)

        plan = ExecutionPlan(
            plan_id=plan_id,
            description=description,
            subtasks=subtasks
        )

        self.active_plans[plan_id] = plan
        logger.info(f"Created plan {plan_id}: {description}")

        return plan

    def _build_dependency_graph(self, subtasks: List[SubTask]) -> Dict[str, Set[str]]:
        """Build dependency graph for task execution order"""
        graph = defaultdict(set)

        for task in subtasks:
            for dep in task.dependencies:
                graph[task.task_id].add(dep)

        return graph

    def _topological_sort(self, subtasks: List[SubTask]) -> List[List[str]]:
        """
        Topological sort to determine execution levels
        Returns list of levels where each level can be executed in parallel
        """
        graph = self._build_dependency_graph(subtasks)
        in_degree = {task.task_id: len(task.dependencies) for task in subtasks}

        levels = []
        ready = [task.task_id for task in subtasks if in_degree[task.task_id] == 0]

        while ready:
            levels.append(ready[:])
            next_ready = []

            for task_id in ready:
                # Find tasks that depend on this one
                for task in subtasks:
                    if task_id in task.dependencies:
                        in_degree[task.task_id] -= 1
                        if in_degree[task.task_id] == 0:
                            next_ready.append(task.task_id)

            ready = next_ready

        return levels

    async def execute_plan(
        self,
        plan_id: str,
        executor=None
    ) -> Dict[str, Any]:
        """Execute a plan with intelligent scheduling"""
        if plan_id not in self.active_plans:
            return {"success": False, "error": "Plan not found"}

        plan = self.active_plans[plan_id]
        plan.started_at = time.time()

        try:
            # Get execution levels (tasks that can run in parallel)
            levels = self._topological_sort(plan.subtasks)
            task_map = {t.task_id: t for t in plan.subtasks}

            logger.info(f"Executing plan {plan_id} in {len(levels)} levels")

            # Execute level by level
            for level_num, level in enumerate(levels, 1):
                logger.info(f"Level {level_num}: Executing {len(level)} tasks in parallel")

                # Execute all tasks in this level in parallel
                tasks_to_run = [task_map[tid] for tid in level]
                await self._execute_level(tasks_to_run, plan, executor)

                # Notify progress
                await self._notify_progress(plan, level_num, len(levels))

                # Check if any task failed
                failed = [t for t in tasks_to_run if t.state == TaskState.FAILED]
                if failed:
                    logger.error(f"Level {level_num} failed, rolling back")
                    await self._rollback_plan(plan)
                    return {
                        "success": False,
                        "error": f"Tasks failed: {[t.name for t in failed]}",
                        "plan_id": plan_id
                    }

            plan.completed_at = time.time()
            plan.total_duration = plan.completed_at - plan.started_at
            plan.success = True

            # Move to history
            self.plan_history.append(plan)
            del self.active_plans[plan_id]

            logger.info(f"Plan {plan_id} completed successfully in {plan.total_duration:.2f}s")

            return {
                "success": True,
                "plan_id": plan_id,
                "duration": plan.total_duration,
                "completed_tasks": len(plan.subtasks),
                "results": plan.context.results
            }

        except Exception as e:
            logger.error(f"Plan execution error: {e}")
            await self._rollback_plan(plan)
            return {"success": False, "error": str(e)}

    async def _execute_level(
        self,
        tasks: List[SubTask],
        plan: ExecutionPlan,
        executor
    ):
        """Execute all tasks in a level in parallel"""
        async def run_task(task: SubTask):
            task.state = TaskState.RUNNING
            task.started_at = time.time()

            try:
                # Execute the task
                if executor:
                    from tools import AVAILABLE_TOOLS
                    tool = AVAILABLE_TOOLS.get(task.action)

                    if tool:
                        result = await executor.execute(tool, task.params)
                        task.result = result

                        if result.get("success"):
                            task.state = TaskState.COMPLETED
                            plan.context.results[task.task_id] = result
                        else:
                            raise Exception(result.get("error", "Unknown error"))
                    else:
                        raise Exception(f"Tool not found: {task.action}")
                else:
                    # Simulation mode
                    await asyncio.sleep(0.1)
                    task.state = TaskState.COMPLETED
                    task.result = {"success": True, "simulated": True}

                task.completed_at = time.time()
                logger.info(f"Task {task.name} completed")

            except Exception as e:
                task.state = TaskState.FAILED
                task.error = str(e)
                task.completed_at = time.time()
                logger.error(f"Task {task.name} failed: {e}")

                # Retry if possible
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    logger.info(f"Retrying task {task.name} ({task.retry_count}/{task.max_retries})")
                    await asyncio.sleep(1)  # Backoff
                    await run_task(task)

        # Run all tasks in parallel with semaphore to limit concurrency
        semaphore = asyncio.Semaphore(self.executor_pool_size)

        async def limited_run(task):
            async with semaphore:
                await run_task(task)

        await asyncio.gather(*[limited_run(task) for task in tasks])

    async def _rollback_plan(self, plan: ExecutionPlan):
        """Rollback completed tasks in reverse order"""
        logger.warning(f"Rolling back plan {plan.plan_id}")

        # Reverse order rollback
        for task in reversed(plan.subtasks):
            if task.state == TaskState.COMPLETED and task.rollback_action:
                try:
                    await task.rollback_action()
                    task.state = TaskState.ROLLED_BACK
                    logger.info(f"Rolled back task {task.name}")
                except Exception as e:
                    logger.error(f"Rollback failed for {task.name}: {e}")

    async def _notify_progress(self, plan: ExecutionPlan, current_level: int, total_levels: int):
        """Notify progress callbacks"""
        progress = (current_level / total_levels) * 100

        for callback in self.progress_callbacks:
            try:
                await callback({
                    "plan_id": plan.plan_id,
                    "progress": progress,
                    "current_level": current_level,
                    "total_levels": total_levels,
                    "completed_tasks": sum(1 for t in plan.subtasks if t.state == TaskState.COMPLETED),
                    "total_tasks": len(plan.subtasks)
                })
            except Exception as e:
                logger.error(f"Progress callback error: {e}")

    def get_plan_status(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a plan"""
        plan = self.active_plans.get(plan_id)
        if not plan:
            # Check history
            for p in self.plan_history:
                if p.plan_id == plan_id:
                    plan = p
                    break

        if not plan:
            return None

        completed = sum(1 for t in plan.subtasks if t.state == TaskState.COMPLETED)
        failed = sum(1 for t in plan.subtasks if t.state == TaskState.FAILED)
        running = sum(1 for t in plan.subtasks if t.state == TaskState.RUNNING)

        return {
            "plan_id": plan.plan_id,
            "description": plan.description,
            "total_tasks": len(plan.subtasks),
            "completed": completed,
            "failed": failed,
            "running": running,
            "success": plan.success,
            "duration": plan.total_duration if plan.completed_at else time.time() - (plan.started_at or time.time()),
            "tasks": [
                {
                    "id": t.task_id,
                    "name": t.name,
                    "state": t.state.value,
                    "retry_count": t.retry_count
                }
                for t in plan.subtasks
            ]
        }

    def cancel_plan(self, plan_id: str):
        """Cancel an active plan"""
        if plan_id in self.active_plans:
            plan = self.active_plans[plan_id]
            for task in plan.subtasks:
                if task.state in [TaskState.PENDING, TaskState.READY, TaskState.RUNNING]:
                    task.state = TaskState.CANCELLED
            logger.info(f"Plan {plan_id} cancelled")
            return True
        return False

    def get_summary(self) -> Dict[str, Any]:
        """Get planner summary"""
        return {
            "active_plans": len(self.active_plans),
            "completed_plans": len(self.plan_history),
            "total_tasks_executed": sum(len(p.subtasks) for p in self.plan_history),
            "average_plan_duration": sum(p.total_duration for p in self.plan_history) / len(self.plan_history) if self.plan_history else 0
        }


# Global instance
_intelligent_planner: Optional[IntelligentPlanner] = None


def get_intelligent_planner() -> IntelligentPlanner:
    """Get or create global intelligent planner instance"""
    global _intelligent_planner
    if _intelligent_planner is None:
        _intelligent_planner = IntelligentPlanner()
    return _intelligent_planner
