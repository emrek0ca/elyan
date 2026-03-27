from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional
from urllib.parse import quote_plus

from core.conversation_memory import conversation_memory
from core.capability_router import get_capability_router
from core.cowork_runtime import get_cowork_runtime
from core.device_sync import get_device_sync_store
from core.intent import ConversationContext, route_intent as route_shared_intent
from core.memory_v2 import memory_v2
from core.ml import get_verifier
from core.reliability import get_outcome_store
from core.storage_paths import resolve_elyan_data_dir, resolve_runs_root
from tools import AVAILABLE_TOOLS
from utils.logger import get_logger

logger = get_logger("mission_control")


def _now() -> float:
    return time.time()


def _compact(text: Any) -> str:
    return " ".join(str(text or "").strip().split())


_ERROR_SIGNAL_MARKERS = (
    "hata",
    "error",
    "failed",
    "failure",
    "unsupported",
    "blocked",
    "invalid",
    "missing",
    "unverified",
    "parse error",
    "verify failed",
    "bozuk",
)

_WEB_BUILD_VERBS = (
    "yap",
    "yaz",
    "oluştur",
    "olustur",
    "üret",
    "uret",
    "tasarla",
    "geliştir",
    "gelistir",
    "hazırla",
    "hazirla",
    "kaydet",
    "create",
    "build",
    "make",
)

_WEB_BUILD_MARKERS = (
    "landing page",
    "landing",
    "frontend",
    "web sitesi",
    "web sayfası",
    "web sayfasi",
    "website",
    "html",
    "css",
    "javascript",
    "js",
    "ui",
)

_QUALITY_META_KEYS = (
    "quality_summary",
    "claim_coverage",
    "critical_claim_coverage",
    "uncertainty_count",
    "conflict_count",
    "manual_review_claim_count",
    "quality_status",
    "source_count",
    "avg_reliability",
    "claim_map_path",
    "revision_summary_path",
    "team_quality_avg",
    "team_research_claim_coverage",
    "team_research_critical_claim_coverage",
    "team_research_uncertainty_count",
)

_WORKFLOW_META_KEYS = (
    "workflow_profile",
    "workflow_phase",
    "approval_status",
    "plan_progress",
    "review_status",
    "workspace_mode",
    "execution_route",
    "autonomy_mode",
    "autonomy_policy",
    "design_artifact_path",
    "plan_artifact_path",
    "plan_json_artifact_path",
    "review_artifact_path",
    "workspace_report_path",
    "baseline_check_path",
    "finish_branch_report_path",
)


def _has_error_signal(*values: Any) -> bool:
    combined = " ".join(_compact(value).lower() for value in values if _compact(value))
    if not combined:
        return False
    return any(marker in combined for marker in _ERROR_SIGNAL_MARKERS)


def _extract_path_candidates(*values: Any) -> list[str]:
    found: list[str] = []
    pattern = re.compile(r"(~?/Users/[^\s'\"]+|/Users/[^\s'\"]+|~\/[^\s'\"]+)")
    for value in values:
        text = str(value or "")
        for match in pattern.findall(text):
            candidate = str(match or "").strip()
            if candidate and candidate not in found:
                found.append(candidate)
    return found


def _has_concrete_artifact(node: "TaskNode", attachments: list[dict[str, Any]], text: str) -> bool:
    paths: list[str] = []
    for attachment in attachments:
        path = str((attachment or {}).get("path") or "").strip()
        if path:
            paths.append(path)
    paths.extend(_extract_path_candidates(text, node.output, node.summary))
    normalized = [path.lower() for path in paths if path]
    if node.specialist == "browser":
        return any(path.endswith((".png", ".jpg", ".jpeg", ".webp")) for path in normalized)
    if node.specialist in {"file", "code"}:
        return any(
            not path.endswith(("/manifest.json", "/summary.txt"))
            and not "/.elyan/proofs/" in path
            and not "/.elyan/runs/" in path
            for path in normalized
        )
    return bool(normalized)


def _attachments_from_direct_payload(payload: dict[str, Any], *, text: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def _push(path_value: Any, kind: str = "artifact") -> None:
        path = str(path_value or "").strip()
        if not path:
            return
        rows.append({"path": path, "type": kind, "name": Path(path).name})

    if not isinstance(payload, dict):
        return rows
    _push(payload.get("path"))
    _push(payload.get("file_path"))
    _push(payload.get("output_path"))
    _push(payload.get("local_path"))
    _push(payload.get("project_dir"), "directory")
    _push(payload.get("pack_dir"), "directory")
    for path in list(payload.get("artifact_paths") or []):
        _push(path)
    for path in list(payload.get("files_created") or []):
        _push(path)
    for path in list(payload.get("report_paths") or []):
        _push(path)
    for path in list(payload.get("screenshots") or []):
        _push(path, "image")
    proof = payload.get("_proof")
    if isinstance(proof, dict):
        _push(proof.get("screenshot"), "image")
    for item in list(payload.get("artifacts") or []):
        if isinstance(item, dict):
            _push(item.get("path"), str(item.get("type") or "artifact"))
    raw = payload.get("raw")
    if isinstance(raw, dict):
        _push(raw.get("path"))
        _push(raw.get("file_path"))
        _push(raw.get("output_path"))
        _push(raw.get("local_path"))
        for item in list(raw.get("artifacts") or []):
            if isinstance(item, dict):
                _push(item.get("path"), str(item.get("type") or "artifact"))
        for path in list(raw.get("files_created") or []):
            _push(path)
        for path in list(raw.get("report_paths") or []):
            _push(path)
        for path in list(raw.get("screenshots") or []):
            _push(path, "image")
    for item in list(payload.get("artifact_manifest") or []):
        if isinstance(item, dict):
            _push(item.get("path"), str(item.get("type") or "artifact"))
    if text:
        for path in _extract_path_candidates(text):
            if _path_exists(path):
                _push(path)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("path") or "")
        if key and key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def _infer_file_node_intent(mission: "Mission", node: "TaskNode") -> dict[str, Any]:
    text = str(node.objective or "").strip()
    combined = f"{mission.goal}\n{text}"
    quoted_match = re.search(r"['\"]([^'\"]+)['\"]", text) or re.search(r"['\"]([^'\"]+)['\"]", combined)
    content = str(quoted_match.group(1) or "").strip() if quoted_match else ""
    low = _low(text)
    mission_low = _low(combined)
    path = ""
    file_match = re.search(r"([A-Za-z0-9_\-./]+?\.(?:txt|md|py|json|html|csv|js|ts|docx|xlsx|pdf))", text)
    if not file_match:
        file_match = re.search(r"([A-Za-z0-9_\-./]+?\.(?:txt|md|py|json|html|csv|js|ts|docx|xlsx|pdf))", combined)
    if file_match:
        path = str(file_match.group(1) or "").strip()
    if path and not path.startswith(("~/", "/")):
        if any(token in mission_low for token in ("masaüstü", "masaustu", "desktop")):
            path = f"~/Desktop/{Path(path).name}"
    if not path:
        folder_name = ""
        folder_match = re.search(r"([A-Za-z0-9_\-]+)\s+(?:adında|adinda|named)?\s+klas(?:ör|or)", text, re.IGNORECASE)
        if not folder_match:
            folder_match = re.search(r"klas(?:ör|or)\s+([A-Za-z0-9_\-]+)", text, re.IGNORECASE)
        if folder_match:
            folder_name = str(folder_match.group(1) or "").strip()
        base_dir = "~/Desktop" if any(token in mission_low for token in ("masaüstü", "masaustu", "desktop")) else "~"
        if folder_name and any(token in low for token in ("klasör", "klasor", "folder")) and any(token in low for token in ("oluştur", "olustur", "create", "aç", "ac")):
            return {"action": "create_folder", "params": {"path": f"{base_dir}/{folder_name}".rstrip("/")}}
        if any(token in low for token in ("listele", "göster", "goster", "list")) and any(token in mission_low for token in ("klasör", "klasor", "folder", "masaüstü", "masaustu", "desktop", "dosya", "file")):
            return {"action": "list_files", "params": {"path": base_dir}}
        if any(token in low for token in ("ara", "search", "bul")) and any(token in mission_low for token in ("dosya", "file")):
            pattern_match = re.search(r"['\"]([^'\"]+)['\"]", combined)
            pattern = str(pattern_match.group(1) or "").strip() if pattern_match else ""
            if not pattern:
                ext_match = re.search(r"(\.[A-Za-z0-9]+)\b", combined)
                if ext_match:
                    pattern = f"*{str(ext_match.group(1) or '').strip()}"
            if pattern:
                return {"action": "search_files", "params": {"pattern": pattern, "directory": base_dir}}
        return {}
    if any(token in low for token in ("doğrula", "dogrula", "içeriğini", "icerigini", "içerik", "icerik", "oku", "kontrol et")):
        return {"action": "read_file", "params": {"path": path}}
    if any(token in low for token in ("sil", "delete", "trash")):
        return {"action": "delete_file", "params": {"path": path, "force": False}}
    if any(token in low for token in (" yaz", " oluştur", "olustur", "kaydet", "save")):
        return {"action": "write_file", "params": {"path": path, "content": content}}
    return {}


def _infer_browser_node_intent(node: "TaskNode") -> dict[str, Any]:
    text = str(node.objective or "").strip()
    url_match = re.search(r"(https?://[^\s'\"]+)", text)
    if url_match:
        return {"action": "open_url", "params": {"url": str(url_match.group(1) or "").strip()}}
    low = _low(text)
    if not any(token in low for token in ("ara", "search", "aç", "ac", "haber", "video", "resim", "resmi", "gorsel", "görsel", "docs")):
        return {}
    cleaned = re.sub(r"\b(?:google chrome|chrome|safari|firefox|browser|tarayıcı|tarayici)(?:'de|'da|de|da|den|dan)?\b", " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:ara|arat|search|aç|ac|göster|goster)\b", " ", cleaned, flags=re.IGNORECASE)
    query = " ".join(cleaned.split()).strip(" .")
    if not query:
        return {}
    if any(token in low for token in ("video", "videosu", "videos")):
        return {"action": "open_url", "params": {"url": f"https://www.youtube.com/results?search_query={quote_plus(query)}"}}
    if any(token in low for token in ("resim", "resmi", "görsel", "gorsel", "image")):
        return {"action": "open_url", "params": {"url": f"https://www.google.com/search?tbm=isch&q={quote_plus(query)}"}}
    return {"action": "open_url", "params": {"url": f"https://www.google.com/search?q={quote_plus(query)}"}}


def _serialize_routed_intent(routed: Any) -> dict[str, Any]:
    if not routed:
        return {}
    if isinstance(routed, dict):
        payload = dict(routed)
    elif hasattr(routed, "to_dict") and callable(routed.to_dict):
        try:
            payload = dict(routed.to_dict())
        except Exception:
            payload = {}
    else:
        payload = {}
    if not payload:
        return {}

    tasks: list[dict[str, Any]] = []
    for task in list(getattr(routed, "tasks", []) or []):
        if isinstance(task, dict):
            tasks.append(dict(task))
            continue
        if hasattr(task, "to_dict") and callable(task.to_dict):
            try:
                task_payload = task.to_dict()
                if isinstance(task_payload, dict):
                    tasks.append(dict(task_payload))
                    continue
            except Exception:
                pass
        if hasattr(task, "__dict__"):
            tasks.append({k: v for k, v in vars(task).items() if not str(k).startswith("_")})
        else:
            tasks.append({"value": str(task)})

    payload["tasks"] = tasks
    payload["is_multi_task"] = bool(getattr(routed, "is_multi_task", payload.get("is_multi_task", False)))
    payload["requires_clarification"] = bool(
        getattr(routed, "requires_clarification", payload.get("requires_clarification", False))
    )
    payload["clarification_options"] = list(
        getattr(routed, "clarification_options", payload.get("clarification_options", [])) or []
    )
    return payload


def _route_specialist_intent(agent: Any, objective: str, user_id: str, mission_goal: str = "") -> dict[str, Any]:
    user_key = str(user_id or "local")
    text = str(objective or "").strip()
    if not text:
        return {}

    context = ConversationContext(user_id=user_key)
    if mission_goal:
        context.add_message("user", str(mission_goal))
    context.add_message("user", text)

    try:
        router = getattr(agent, "intent_router", None)
        if router is not None:
            routed = router.route(text, user_key, AVAILABLE_TOOLS, context)
        else:
            routed = route_shared_intent(text, user_key, AVAILABLE_TOOLS, context, getattr(agent, "llm", None))
    except Exception as exc:
        logger.debug(f"Shared intent routing skipped: {exc}")
        return {}

    payload = _serialize_routed_intent(routed)
    action = str(payload.get("action") or "").strip().lower()
    if not action or action in {"chat", "unknown"}:
        return {}
    return payload


def _looks_like_web_build_goal(text: str) -> bool:
    low = _compact(text).lower()
    if not low:
        return False
    if not any(marker in low for marker in _WEB_BUILD_MARKERS):
        return False
    if any(verb in low for verb in _WEB_BUILD_VERBS):
        return True
    return any(phrase in low for phrase in ("html css js", "html/css/js", "frontend ui"))


def _slug(text: Any, *, max_len: int = 42) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", _compact(text).lower())
    clean = raw.strip("-") or "mission"
    return clean[:max_len].strip("-") or "mission"


def _low(text: Any) -> str:
    return _compact(text).lower()


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return value
    except Exception:
        return str(value)


def _path_exists(path: str) -> bool:
    try:
        return bool(path) and Path(path).expanduser().exists()
    except Exception:
        return False


@dataclass
class EvidenceRecord:
    evidence_id: str
    mission_id: str
    node_id: str
    kind: str
    label: str
    path: str = ""
    source: str = "mission"
    summary: str = ""
    created_at: float = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvidenceRecord":
        return cls(
            evidence_id=str(payload.get("evidence_id") or f"ev_{uuid.uuid4().hex[:10]}"),
            mission_id=str(payload.get("mission_id") or ""),
            node_id=str(payload.get("node_id") or ""),
            kind=str(payload.get("kind") or "note"),
            label=str(payload.get("label") or ""),
            path=str(payload.get("path") or ""),
            source=str(payload.get("source") or "mission"),
            summary=str(payload.get("summary") or ""),
            created_at=float(payload.get("created_at") or _now()),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class MissionEvent:
    event_id: str
    mission_id: str
    event_type: str
    label: str
    status: str = ""
    node_id: str = ""
    created_at: float = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MissionEvent":
        return cls(
            event_id=str(payload.get("event_id") or f"evt_{uuid.uuid4().hex[:10]}"),
            mission_id=str(payload.get("mission_id") or ""),
            event_type=str(payload.get("event_type") or ""),
            label=str(payload.get("label") or ""),
            status=str(payload.get("status") or ""),
            node_id=str(payload.get("node_id") or ""),
            created_at=float(payload.get("created_at") or _now()),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class ApprovalRequest:
    approval_id: str
    mission_id: str
    node_id: str
    title: str
    summary: str
    risk_level: str
    expected_effect: str = ""
    rollback_hint: str = ""
    status: str = "pending"
    created_at: float = field(default_factory=_now)
    resolved_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovalRequest":
        return cls(
            approval_id=str(payload.get("approval_id") or f"apr_{uuid.uuid4().hex[:10]}"),
            mission_id=str(payload.get("mission_id") or ""),
            node_id=str(payload.get("node_id") or ""),
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            risk_level=str(payload.get("risk_level") or "medium"),
            expected_effect=str(payload.get("expected_effect") or ""),
            rollback_hint=str(payload.get("rollback_hint") or ""),
            status=str(payload.get("status") or "pending"),
            created_at=float(payload.get("created_at") or _now()),
            resolved_at=float(payload.get("resolved_at") or 0.0),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class TaskNode:
    node_id: str
    title: str
    specialist: str
    objective: str
    kind: str
    status: str = "queued"
    risk_level: str = "low"
    depends_on: list[str] = field(default_factory=list)
    parallel_group: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    retry_budget: int = 1
    summary: str = ""
    output: str = ""
    run_id: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskNode":
        return cls(
            node_id=str(payload.get("node_id") or f"node_{uuid.uuid4().hex[:10]}"),
            title=str(payload.get("title") or ""),
            specialist=str(payload.get("specialist") or "planner"),
            objective=str(payload.get("objective") or ""),
            kind=str(payload.get("kind") or ""),
            status=str(payload.get("status") or "queued"),
            risk_level=str(payload.get("risk_level") or "low"),
            depends_on=[str(item) for item in list(payload.get("depends_on") or []) if str(item).strip()],
            parallel_group=str(payload.get("parallel_group") or ""),
            input_schema=dict(payload.get("input_schema") or {}),
            output_schema=dict(payload.get("output_schema") or {}),
            retry_budget=int(payload.get("retry_budget") or 1),
            summary=str(payload.get("summary") or ""),
            output=str(payload.get("output") or ""),
            run_id=str(payload.get("run_id") or ""),
            started_at=float(payload.get("started_at") or 0.0),
            completed_at=float(payload.get("completed_at") or 0.0),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class MissionGraph:
    nodes: list[TaskNode] = field(default_factory=list)
    parallel_waves: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "parallel_waves": [list(wave) for wave in self.parallel_waves],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MissionGraph":
        return cls(
            nodes=[TaskNode.from_dict(item) for item in list(payload.get("nodes") or []) if isinstance(item, dict)],
            parallel_waves=[list(wave) for wave in list(payload.get("parallel_waves") or []) if isinstance(wave, list)],
        )


@dataclass
class SkillRecipe:
    recipe_id: str
    name: str
    source_mission_id: str
    input_schema: dict[str, Any]
    task_graph_template: dict[str, Any]
    tool_policy: dict[str, Any]
    verification_rules: list[str]
    output_contract: dict[str, Any]
    risk_profile: str
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SkillRecipe":
        return cls(
            recipe_id=str(payload.get("recipe_id") or f"skill_{uuid.uuid4().hex[:10]}"),
            name=str(payload.get("name") or "Skill"),
            source_mission_id=str(payload.get("source_mission_id") or ""),
            input_schema=dict(payload.get("input_schema") or {}),
            task_graph_template=dict(payload.get("task_graph_template") or {}),
            tool_policy=dict(payload.get("tool_policy") or {}),
            verification_rules=[str(item) for item in list(payload.get("verification_rules") or []) if str(item).strip()],
            output_contract=dict(payload.get("output_contract") or {}),
            risk_profile=str(payload.get("risk_profile") or "low"),
            created_at=float(payload.get("created_at") or _now()),
        )


@dataclass
class MemoryRecord:
    memory_type: str
    scope: str
    title: str
    content: str
    confidence: float = 0.0
    last_used_at: float = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Mission:
    mission_id: str
    goal: str
    owner: str
    channel: str
    mode: str
    route_mode: str
    risk_profile: str
    success_contract: dict[str, Any]
    graph: MissionGraph
    status: str = "queued"
    deliverable: str = ""
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    events: list[MissionEvent] = field(default_factory=list)
    evidence: list[EvidenceRecord] = field(default_factory=list)
    approvals: list[ApprovalRequest] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def request_contract(self) -> dict[str, Any]:
        metadata = self.metadata if isinstance(self.metadata, dict) else {}
        contract = metadata.get("request_contract")
        return dict(contract) if isinstance(contract, dict) else {}

    def preview_summary(self) -> dict[str, Any]:
        contract = self.request_contract()
        success = dict(self.success_contract or {})
        nodes = self.graph.nodes[:4]
        return {
            "goal": self.goal,
            "mode": self.mode,
            "route_mode": self.route_mode,
            "risk_profile": self.risk_profile,
            "content_kind": str(contract.get("content_kind") or success.get("content_kind") or "").strip(),
            "output_formats": list(contract.get("output_formats") or success.get("expected_outputs") or []),
            "style_profile": str(contract.get("style_profile") or success.get("style_profile") or "").strip(),
            "source_policy": str(contract.get("source_policy") or success.get("source_policy") or "").strip(),
            "quality_contract": list(contract.get("quality_contract") or success.get("quality_contract") or []),
            "preview": str(contract.get("preview") or success.get("preview") or self.goal[:220]).strip(),
            "expected_artifacts": list(contract.get("output_artifacts") or success.get("expected_outputs") or []),
            "evidence_required": bool(success.get("evidence_required", True)),
            "needs_clarification": bool(contract.get("needs_clarification", False)),
            "clarifying_question": str(contract.get("clarifying_question") or "").strip(),
            "confidence": float(contract.get("confidence") or 0.0),
            "autonomy_mode": str(success.get("autonomy_mode") or "assisted"),
            "approval_mode": str(success.get("approval_mode") or "risk_based"),
            "verification_mode": str(success.get("verification_mode") or "light"),
            "requires_plan": bool(success.get("requires_plan", False)),
            "draft_first": bool(success.get("draft_first", False)),
            "observe_only": bool(success.get("observe_only", False)),
            "parallel_waves": len(self.graph.parallel_waves),
            "node_preview": [
                {
                    "node_id": node.node_id,
                    "title": node.title,
                    "specialist": node.specialist,
                    "risk_level": node.risk_level,
                }
                for node in nodes
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "goal": self.goal,
            "owner": self.owner,
            "channel": self.channel,
            "mode": self.mode,
            "route_mode": self.route_mode,
            "risk_profile": self.risk_profile,
            "success_contract": dict(self.success_contract),
            "graph": self.graph.to_dict(),
            "status": self.status,
            "deliverable": self.deliverable,
            "final_deliverable": self.deliverable,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "events": [event.to_dict() for event in self.events],
            "timeline": [event.to_dict() for event in self.events],
            "evidence": [record.to_dict() for record in self.evidence],
            "approvals": [item.to_dict() for item in self.approvals],
            "attachments": list(self.attachments),
            "metadata": dict(self.metadata),
            "preview_summary": self.preview_summary(),
            "quality_summary": self.quality_summary(),
            "control_summary": self.control_summary(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Mission":
        metadata = dict(payload.get("metadata") or {})
        quality_meta = metadata.get("quality_summary") if isinstance(metadata.get("quality_summary"), dict) else {}
        quality_meta = dict(quality_meta or {})
        for source in (
            payload.get("quality_summary"),
            payload.get("control_summary"),
        ):
            if not isinstance(source, dict) or not source:
                continue
            for key in _QUALITY_META_KEYS:
                if key == "quality_summary":
                    continue
                value = source.get(key)
                if value in ("", None, [], {}):
                    continue
                if key in {
                    "claim_coverage",
                    "critical_claim_coverage",
                    "uncertainty_count",
                    "conflict_count",
                    "manual_review_claim_count",
                    "source_count",
                    "avg_reliability",
                    "team_quality_avg",
                    "team_research_claim_coverage",
                    "team_research_critical_claim_coverage",
                    "team_research_uncertainty_count",
                }:
                    quality_meta[key] = value
                else:
                    metadata[key] = value
            for key in _WORKFLOW_META_KEYS:
                value = source.get(key)
                if value in ("", None, [], {}):
                    continue
                metadata[key] = value
        if quality_meta:
            metadata["quality_summary"] = quality_meta
        return cls(
            mission_id=str(payload.get("mission_id") or f"mission_{uuid.uuid4().hex[:10]}"),
            goal=str(payload.get("goal") or ""),
            owner=str(payload.get("owner") or "local"),
            channel=str(payload.get("channel") or "dashboard"),
            mode=str(payload.get("mode") or "Balanced"),
            route_mode=str(payload.get("route_mode") or "task"),
            risk_profile=str(payload.get("risk_profile") or "low"),
            success_contract=dict(payload.get("success_contract") or {}),
            graph=MissionGraph.from_dict(dict(payload.get("graph") or {})),
            status=str(payload.get("status") or "queued"),
            deliverable=str(payload.get("deliverable") or ""),
            created_at=float(payload.get("created_at") or _now()),
            updated_at=float(payload.get("updated_at") or _now()),
            events=[MissionEvent.from_dict(item) for item in list(payload.get("events") or []) if isinstance(item, dict)],
            evidence=[EvidenceRecord.from_dict(item) for item in list(payload.get("evidence") or []) if isinstance(item, dict)],
            approvals=[ApprovalRequest.from_dict(item) for item in list(payload.get("approvals") or []) if isinstance(item, dict)],
            attachments=[str(item) for item in list(payload.get("attachments") or []) if str(item).strip()],
            metadata=metadata,
        )

    def _node_counts(self) -> dict[str, int]:
        counts = {
            "completed": 0,
            "running": 0,
            "queued": 0,
            "failed": 0,
            "waiting_approval": 0,
            "blocked": 0,
        }
        for node in self.graph.nodes:
            key = str(node.status or "queued").strip().lower() or "queued"
            if key not in counts:
                key = "queued"
            counts[key] += 1
        return counts

    def quality_summary(self) -> dict[str, Any]:
        metadata = self.metadata if isinstance(self.metadata, dict) else {}
        summary: dict[str, Any] = {}
        raw_summary = metadata.get("quality_summary")
        if isinstance(raw_summary, dict):
            summary.update(raw_summary)
        for key in _QUALITY_META_KEYS:
            if key == "quality_summary":
                continue
            value = metadata.get(key)
            if value in ("", None, [], {}):
                continue
            if key not in summary:
                summary[key] = value
        if "status" not in summary:
            raw_status = str(summary.get("quality_status") or "").strip().lower()
            if raw_status:
                summary["status"] = raw_status
            else:
                claim = float(summary.get("claim_coverage", 0.0) or 0.0)
                critical = float(summary.get("critical_claim_coverage", 0.0) or 0.0)
                uncertainty = int(summary.get("uncertainty_count", 0) or 0)
                if claim > 0 or critical > 0:
                    summary["status"] = "pass" if critical >= 1.0 and uncertainty == 0 else "partial"
                elif self.route_mode == "research":
                    summary["status"] = "pending"
        return summary

    def control_summary(self) -> dict[str, Any]:
        counts = self._node_counts()
        metadata = self.metadata if isinstance(self.metadata, dict) else {}
        quality = self.quality_summary()
        total_nodes = max(1, len(self.graph.nodes))
        summary: dict[str, Any] = {
            "status": self.status,
            "mode": self.mode,
            "route_mode": self.route_mode,
            "risk_profile": self.risk_profile,
            "completed_nodes": counts["completed"],
            "running_nodes": counts["running"],
            "queued_nodes": counts["queued"],
            "failed_nodes": counts["failed"],
            "waiting_approval_nodes": counts["waiting_approval"],
            "blocked_nodes": counts["blocked"],
            "progress": round(counts["completed"] / total_nodes, 2),
            "evidence_count": len(self.evidence),
            "artifact_count": len([record for record in self.evidence if str(record.path or "").strip()]),
            "pending_approvals": len([item for item in self.approvals if item.status == "pending"]),
            "node_count": len(self.graph.nodes),
            "parallel_waves": len(self.graph.parallel_waves),
        }
        if quality:
            summary["quality_status"] = str(quality.get("status") or quality.get("quality_status") or "").strip()
            for key in (
                "claim_coverage",
                "critical_claim_coverage",
                "uncertainty_count",
                "conflict_count",
                "manual_review_claim_count",
                "source_count",
                "avg_reliability",
                "claim_map_path",
                "revision_summary_path",
                "team_quality_avg",
                "team_research_claim_coverage",
                "team_research_critical_claim_coverage",
                "team_research_uncertainty_count",
            ):
                if key in quality:
                    summary[key] = quality.get(key)
        for key in _WORKFLOW_META_KEYS:
            value = metadata.get(key)
            if value in ("", None, [], {}):
                continue
            summary[key] = value
        summary["preview_summary"] = self.preview_summary()
        return summary

    def snapshot(self) -> dict[str, Any]:
        counts = self._node_counts()
        quality = self.quality_summary()
        control = self.control_summary()
        return {
            "mission_id": self.mission_id,
            "goal": self.goal,
            "owner": self.owner,
            "channel": self.channel,
            "mode": self.mode,
            "route_mode": self.route_mode,
            "status": self.status,
            "risk_profile": self.risk_profile,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "progress": control.get("progress", round(counts["completed"] / max(1, len(self.graph.nodes)), 2)),
            "pending_approvals": control.get("pending_approvals", len([item for item in self.approvals if item.status == "pending"])),
            "deliverable_preview": self.deliverable[:240],
            "evidence_count": control.get("evidence_count", len(self.evidence)),
            "artifact_count": control.get("artifact_count", len([record for record in self.evidence if str(record.path or "").strip()])),
            "parallel_waves": control.get("parallel_waves", len(self.graph.parallel_waves)),
            "completed_nodes": counts["completed"],
            "running_nodes": counts["running"],
            "queued_nodes": counts["queued"],
            "failed_nodes": counts["failed"],
            "waiting_approval_nodes": counts["waiting_approval"],
            "blocked_nodes": counts["blocked"],
            "quality_status": control.get("quality_status", ""),
            "claim_coverage": control.get("claim_coverage", 0.0),
            "critical_claim_coverage": control.get("critical_claim_coverage", 0.0),
            "uncertainty_count": control.get("uncertainty_count", 0),
            "conflict_count": control.get("conflict_count", 0),
            "manual_review_claim_count": control.get("manual_review_claim_count", 0),
            "source_count": control.get("source_count", 0),
            "avg_reliability": control.get("avg_reliability", 0.0),
            "claim_map_path": control.get("claim_map_path", ""),
            "revision_summary_path": control.get("revision_summary_path", ""),
            "workflow_profile": control.get("workflow_profile", ""),
            "workflow_phase": control.get("workflow_phase", ""),
            "approval_status": control.get("approval_status", ""),
            "plan_progress": control.get("plan_progress", ""),
            "review_status": control.get("review_status", ""),
            "workspace_mode": control.get("workspace_mode", ""),
            "execution_route": control.get("execution_route", ""),
            "preview_summary": control.get("preview_summary", self.preview_summary()),
            "quality_summary": quality,
            "control_summary": control,
        }


class MissionRuntime:
    def __init__(self, storage_dir: Path | None = None):
        self.storage_dir = Path(storage_dir or (resolve_elyan_data_dir() / "mission_control")).expanduser()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.missions_path = self.storage_dir / "missions.json"
        self.skills_path = self.storage_dir / "skills.json"
        self._missions: dict[str, Mission] = {}
        self._skills: dict[str, SkillRecipe] = {}
        self._listeners: list[Callable[[dict[str, Any]], Any]] = []
        self._lock = asyncio.Lock()
        self._running: dict[str, asyncio.Task] = {}
        self.outcome_store = get_outcome_store()
        self.sync_store = get_device_sync_store()
        self.verifier_service = get_verifier()
        self._load()

    @staticmethod
    def _sync_identifiers(mission: "Mission") -> tuple[str, str]:
        metadata = dict(mission.metadata or {})
        return (
            str(metadata.get("device_id") or metadata.get("client_id") or "primary"),
            str(metadata.get("session_id") or metadata.get("channel_session_id") or "default"),
        )

    @staticmethod
    def _sync_request_class(route_mode: str) -> str:
        mode = str(route_mode or "").strip().lower()
        if mode in {"file", "browser", "task"}:
            return "direct_action"
        if mode in {"research", "document"}:
            return "research"
        if mode in {"code", "coding"}:
            return "coding"
        return "workflow"

    def _load(self) -> None:
        try:
            if self.missions_path.exists():
                payload = json.loads(self.missions_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    self._missions = {
                        str(key): Mission.from_dict(row)
                        for key, row in payload.items()
                        if isinstance(row, dict)
                    }
        except Exception as exc:
            logger.warning(f"Mission store load failed: {exc}")
            self._missions = {}
        try:
            if self.skills_path.exists():
                payload = json.loads(self.skills_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    self._skills = {
                        str(key): SkillRecipe.from_dict(row)
                        for key, row in payload.items()
                        if isinstance(row, dict)
                    }
        except Exception as exc:
            logger.warning(f"Skill store load failed: {exc}")
            self._skills = {}

    def _save(self) -> None:
        self.missions_path.write_text(
            json.dumps({mid: mission.to_dict() for mid, mission in self._missions.items()}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        self.skills_path.write_text(
            json.dumps({sid: skill.to_dict() for sid, skill in self._skills.items()}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def subscribe(self, callback: Callable[[dict[str, Any]], Any]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        message = {"event_type": event_type, **payload}
        for callback in list(self._listeners):
            try:
                result = callback(message)
                if inspect.isawaitable(result):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(result)
                    except RuntimeError:
                        pass
            except Exception as exc:
                logger.debug(f"Mission listener failed: {exc}")

    @staticmethod
    def _extract_steps(goal: str) -> list[str]:
        text = str(goal or "").strip()
        if not text:
            return []
        lines = [item.strip(" -•\t") for item in text.splitlines() if item.strip(" -•\t")]
        if len(lines) >= 2:
            return lines[:6]
        numbered = [item.strip(" -•\t") for item in re.split(r"(?:^|\s)\d+[\)\.\-:]\s*", text) if item.strip(" -•\t")]
        if len(numbered) >= 2:
            return numbered[:6]
        chunks = [item.strip(" -•\t") for item in re.split(r"\s+(?:ve|veya|ardından|ardindan|sonra|then|and)\s+", text, flags=re.IGNORECASE) if item.strip(" -•\t")]
        if len(chunks) >= 2:
            return chunks[:6]
        return []

    @staticmethod
    def _steps_are_sequential(goal: str) -> bool:
        text = _low(goal)
        if not text:
            return False
        markers = (
            " sonra ",
            " ve sonra ",
            " ardından ",
            " ardindan ",
            " then ",
            " after ",
            " önce ",
            " once ",
            " kaydet",
            " doğrula",
            " dogrula",
        )
        return any(marker in f" {text} " for marker in markers)

    @staticmethod
    def _select_specialist(text: str, *, route_mode: str = "") -> str:
        low = _low(text)
        mode = str(route_mode or "").strip().lower()
        if mode == "research" or any(token in low for token in ("araştır", "arastir", "research", "kaynak", "rapor", "analiz")):
            return "research"
        if mode in {"browser", "screen"} or any(token in low for token in ("browser", "tarayıcı", "tarayici", "chrome", "safari", "click", "tıkla", "tikla", "form")):
            return "browser"
        if mode == "code" or _looks_like_web_build_goal(low) or any(token in low for token in ("kod", "code", "python", "react", "javascript", "typescript", "website", "web sitesi", "uygulama", "app", "repo", "feature", "geliştir", "gelistir", "implement", "debug", "fix")):
            return "code"
        if mode in {"file", "file_operations"} or any(
            token in low
            for token in (
                "dosya",
                "klasör",
                "folder",
                "file",
                "kaydet",
                "save",
                "masaüstü",
                "masaustu",
                "desktop",
                ".txt",
                ".md",
                ".json",
                ".html",
                ".csv",
            )
        ):
            return "file"
        if any(token in low for token in ("veri", "csv", "dataset", "analitik", "grafik", "tablo", "excel", "xlsx", "sheet", "spreadsheet", "table")):
            return "data"
        if any(token in low for token in ("doküman", "dokuman", "sunum", "rapor", "teklif", "brief")):
            return "document"
        return "document"

    @staticmethod
    def _risk_from_text(text: str, *, route_mode: str = "") -> str:
        low = _low(text)
        if any(token in low for token in ("deploy", "production", "prod", "yayınla", "yayinla", "gönder", "gonder", "sil", "delete", "ödeme", "odeme", "hesap", "payment")):
            return "high"
        if route_mode in {"browser", "screen", "code", "file"}:
            return "medium"
        if any(token in low for token in ("write", "oluştur", "olustur", "repo", "dosya", "browser", "tarayıcı", "tarayici", "kod")):
            return "medium"
        return "low"

    @staticmethod
    def _execution_preferences(text: str, mode: str = "") -> dict[str, Any]:
        low = _low(text)
        prefs: dict[str, Any] = {}
        if any(
            phrase in low
            for phrase in (
                "önce planla",
                "once planla",
                "planını çıkar",
                "planini cikar",
                "plan çıkar",
                "plan cikar",
                "plan first",
            )
        ):
            prefs["requires_plan"] = True
        if any(
            phrase in low
            for phrase in (
                "önce taslak",
                "once taslak",
                "taslak hazırla",
                "taslak hazirla",
                "taslak çıkar",
                "taslak cikar",
                "draft first",
            )
        ):
            prefs["draft_first"] = True
            prefs["requires_plan"] = True
        if any(
            phrase in low
            for phrase in (
                "sorarak ilerle",
                "bana sor",
                "tek tek onay",
                "onay almadan yapma",
                "ask before acting",
                "confirm each step",
            )
        ):
            prefs["approval_mode"] = "per_step"
            prefs["autonomy_mode"] = "confirmed"
        if any(
            phrase in low
            for phrase in (
                "sadece incele",
                "sadece analiz et",
                "sadece gözlemle",
                "sadece gozlemle",
                "observe only",
                "read only",
                "salt okunur",
                "değişiklik yapma",
                "degisiklik yapma",
                "dokunma",
            )
        ):
            prefs["observe_only"] = True
            prefs["dry_run"] = True
            prefs["autonomy_mode"] = "observe_only"
        if any(phrase in low for phrase in ("dry run", "simüle et", "simule et", "simulate", "taslak olarak göster", "taslak olarak goster")):
            prefs["dry_run"] = True
        if any(phrase in low for phrase in ("doğrula", "dogrula", "teyit et", "verify")):
            prefs["verification_mode"] = "strict"
        if prefs.get("draft_first") and "autonomy_mode" not in prefs and not prefs.get("observe_only"):
            prefs["autonomy_mode"] = "draft_first"
        mode_low = str(mode or "").strip().lower()
        if mode_low == "audit":
            prefs.setdefault("verification_mode", "strict")
        elif mode_low == "sprint":
            prefs.setdefault("verification_mode", "minimal")
        return prefs

    @staticmethod
    def _success_contract(goal: str, route_mode: str, mode: str, preferences: dict[str, Any] | None = None) -> dict[str, Any]:
        criteria = ["Somut ve denetlenebilir bir çıktı üret"]
        content_kind = "task"
        expected_outputs = ["deliverable"]
        quality_contract = ["artifact_traceability"]
        style_profile = "executive"
        source_policy = "trusted"
        prefs = dict(preferences or {})
        if route_mode == "research":
            criteria.append("Önemli iddiaları kaynaklarla bağla")
            content_kind = "research_delivery"
            expected_outputs = ["docx", "pdf", "xlsx", "pptx"]
            quality_contract = ["source_traceability", "claim_coverage", "critical_claim_coverage", "uncertainty_log"]
            style_profile = "analytical"
        elif route_mode == "code":
            criteria.append("Kod veya artifact üret ve doğrulama özetini ekle")
            content_kind = "code_project"
            expected_outputs = ["source_code", "tests", "verification_summary"]
            quality_contract = ["repo_truth", "gates", "artifact_evidence"]
            style_profile = "implementation"
        elif route_mode in {"browser", "screen"}:
            criteria.append("DOM veya ekran kanıtı bırak")
            content_kind = "browser_task"
            expected_outputs = ["screenshot", "dom_snapshot", "action_log"]
            quality_contract = ["screen_traceability", "artifact_evidence"]
            style_profile = "operational"
        elif route_mode == "data":
            criteria.append("Schema ve kalite özeti ver")
            content_kind = "spreadsheet"
            expected_outputs = ["xlsx", "csv", "md"]
            quality_contract = ["sheet_integrity", "table_structure", "source_traceability"]
            style_profile = "structured"
        elif route_mode == "document":
            content_kind = "document_pack"
            expected_outputs = ["docx", "pdf", "html", "md"]
            quality_contract = ["section_structure", "language_quality", "traceability"]
            style_profile = "executive"
        else:
            criteria.append("Teslim özeti ve sonraki adımı net yaz")
            expected_outputs = ["summary"]
            quality_contract = ["traceability"]

        verification = "light"
        if str(mode or "").strip().lower() == "audit":
            verification = "strict"
        elif str(mode or "").strip().lower() == "sprint":
            verification = "minimal"
        if prefs.get("verification_mode") in {"strict", "minimal", "light"}:
            verification = str(prefs.get("verification_mode") or verification)

        if prefs.get("requires_plan"):
            criteria.append("Yürütme öncesi görünür plan çıkar")
        if prefs.get("draft_first"):
            criteria.append("Önce taslak veya preview üret, sonra uygulamaya geç")
        if prefs.get("approval_mode") == "per_step":
            criteria.append("Etkili adımlardan önce kullanıcı onayı bekle")
        if prefs.get("observe_only") or prefs.get("dry_run"):
            criteria.append("Kalıcı değişiklik uygulama; yalnızca analiz, preview veya dry-run çıktısı üret")
            expected_outputs = ["plan_summary", "impact_preview", "verification_summary"]
            quality_contract = [item for item in quality_contract if item != "artifact_evidence"] + ["preview_only"]

        preview = f"{content_kind.replace('_', ' ')} | çıktı: {', '.join(expected_outputs[:4])} | stil: {style_profile}"

        return {
            "goal": str(goal or "").strip(),
            "route_mode": route_mode or "task",
            "verification_mode": verification,
            "criteria": criteria,
            "local_only": True,
            "evidence_required": True,
            "content_kind": content_kind,
            "expected_outputs": expected_outputs,
            "quality_contract": quality_contract,
            "style_profile": style_profile,
            "source_policy": source_policy,
            "preview": preview,
            "memory_scope": "task_routed" if route_mode != "communication" else "communication_minimal",
            "autonomy_mode": str(prefs.get("autonomy_mode") or "assisted"),
            "approval_mode": str(prefs.get("approval_mode") or "risk_based"),
            "requires_plan": bool(prefs.get("requires_plan", False)),
            "draft_first": bool(prefs.get("draft_first", False)),
            "observe_only": bool(prefs.get("observe_only", False)),
            "dry_run": bool(prefs.get("dry_run", False)),
        }

    def _build_graph(self, goal: str, route_mode: str, mode: str, preferences: dict[str, Any] | None = None) -> MissionGraph:
        steps = self._extract_steps(goal)
        sequential_steps = self._steps_are_sequential(goal)
        prefs = dict(preferences or {})
        nodes: list[TaskNode] = [
            TaskNode(
                node_id="planner",
                title="Goal Intake",
                specialist="planner",
                objective="Kullanıcı hedefini başarı sözleşmesine ve görev grafiğine çevir.",
                kind="planner",
                risk_level="low",
                output_schema={"type": "mission_contract"},
            )
        ]
        parallel_waves: list[list[str]] = []
        execution_anchor = "planner"
        work_metadata = {
            "approval_required": bool(prefs.get("approval_mode") == "per_step"),
            "read_only": bool(prefs.get("observe_only", False)),
            "dry_run": bool(prefs.get("dry_run", False)),
            "requires_plan": bool(prefs.get("requires_plan", False)),
            "draft_first": bool(prefs.get("draft_first", False)),
        }

        def add_node(node: TaskNode) -> None:
            nodes.append(node)

        if prefs.get("requires_plan") or prefs.get("draft_first"):
            execution_anchor = "plan_preview"
            add_node(
                TaskNode(
                    node_id=execution_anchor,
                    title="Plan Preview",
                    specialist="planner",
                    objective="Yürütme öncesi plan, yaklaşım ve beklenen etkileri görünür özetle.",
                    kind="probe",
                    risk_level="low",
                    depends_on=["planner"],
                    metadata={"probe_type": "plan", "execution_preferences": dict(prefs)},
                )
            )

        if steps:
            wave = []
            for idx, step in enumerate(steps, start=1):
                specialist = self._select_specialist(step, route_mode=route_mode)
                node_id = f"step_{idx}"
                depends_on = [execution_anchor]
                if sequential_steps and idx > 1:
                    depends_on = [f"step_{idx - 1}"]
                add_node(
                    TaskNode(
                        node_id=node_id,
                        title=f"Step {idx}",
                        specialist=specialist,
                        objective=step,
                        kind=specialist,
                        risk_level=self._risk_from_text(step, route_mode=route_mode),
                        depends_on=depends_on,
                        parallel_group="" if sequential_steps else "wave_1",
                        output_schema={"type": "step_result"},
                        metadata=dict(work_metadata),
                    )
                )
                wave.append(node_id)
            parallel_waves.append(wave)
            verify_deps = list(wave)
        else:
            if route_mode == "code":
                wave = ["repo_truth", "implementation"]
                add_node(
                    TaskNode(
                        node_id="repo_truth",
                        title="Repo Truth",
                        specialist="document",
                        objective="Mevcut çalışma alanını ve giriş noktalarını tara.",
                        kind="probe",
                        risk_level="low",
                        depends_on=[execution_anchor],
                        parallel_group="wave_1",
                        metadata={"speculative": True, "probe_type": "repo"},
                    )
                )
                add_node(
                    TaskNode(
                        node_id="implementation",
                        title="Implementation",
                        specialist="code",
                        objective=goal,
                        kind="code",
                        risk_level=self._risk_from_text(goal, route_mode=route_mode),
                        depends_on=[execution_anchor],
                        parallel_group="wave_1",
                        output_schema={"type": "code_deliverable"},
                        metadata=dict(work_metadata),
                    )
                )
                parallel_waves.append(wave)
                verify_deps = list(wave)
            elif route_mode == "research":
                wave = ["source_scan", "synthesis_draft"]
                add_node(
                    TaskNode(
                        node_id="source_scan",
                        title="Source Scan",
                        specialist="research",
                        objective=goal,
                        kind="research",
                        risk_level="low",
                        depends_on=[execution_anchor],
                        parallel_group="wave_1",
                        metadata={"probe_type": "sources"},
                    )
                )
                add_node(
                    TaskNode(
                        node_id="synthesis_draft",
                        title="Draft",
                        specialist="document",
                        objective="Ara bulgular için taslak iskelet hazırla.",
                        kind="probe",
                        risk_level="low",
                        depends_on=[execution_anchor],
                        parallel_group="wave_1",
                        metadata={"speculative": True, "probe_type": "outline"},
                    )
                )
                parallel_waves.append(wave)
                verify_deps = list(wave)
            elif route_mode in {"browser", "screen"}:
                wave = ["screen_probe", "browser_action"]
                add_node(
                    TaskNode(
                        node_id="screen_probe",
                        title="Screen Probe",
                        specialist="browser",
                        objective="Ekran veya browser bağlamını özetle.",
                        kind="probe",
                        risk_level="low",
                        depends_on=[execution_anchor],
                        parallel_group="wave_1",
                        metadata={"probe_type": "screen"},
                    )
                )
                add_node(
                    TaskNode(
                        node_id="browser_action",
                        title="Browser Action",
                        specialist="browser",
                        objective=goal,
                        kind="browser",
                        risk_level=self._risk_from_text(goal, route_mode=route_mode),
                        depends_on=[execution_anchor],
                        parallel_group="wave_1",
                        output_schema={"type": "browser_result"},
                        metadata=dict(work_metadata),
                    )
                )
                parallel_waves.append(wave)
                verify_deps = list(wave)
            else:
                wave = ["context_scan", "delivery_task"]
                add_node(
                    TaskNode(
                        node_id="context_scan",
                        title="Context Scan",
                        specialist="document",
                        objective="Görev bağlamını ve beklenen teslimi özetle.",
                        kind="probe",
                        risk_level="low",
                        depends_on=[execution_anchor],
                        parallel_group="wave_1",
                        metadata={"speculative": True, "probe_type": "context"},
                    )
                )
                add_node(
                    TaskNode(
                        node_id="delivery_task",
                        title="Execution",
                        specialist=self._select_specialist(goal, route_mode=route_mode),
                        objective=goal,
                        kind=route_mode or "task",
                        risk_level=self._risk_from_text(goal, route_mode=route_mode),
                        depends_on=[execution_anchor],
                        parallel_group="wave_1",
                        metadata=dict(work_metadata),
                    )
                )
                parallel_waves.append(wave)
                verify_deps = list(wave)

        add_node(
            TaskNode(
                node_id="verifier",
                title="Verification",
                specialist="verifier",
                objective="Görevin kanıt, doğruluk ve teslim sözleşmesini kontrol et.",
                kind="verifier",
                risk_level="low",
                depends_on=verify_deps,
                output_schema={"type": "verification_summary"},
            )
        )
        add_node(
            TaskNode(
                node_id="delivery",
                title="Delivery",
                specialist="comms",
                objective="Son teslimi kısa, net ve kanıt bağlantılarıyla hazırla.",
                kind="delivery",
                risk_level="low",
                depends_on=["verifier"],
                output_schema={"type": "final_deliverable"},
            )
        )
        return MissionGraph(nodes=nodes, parallel_waves=parallel_waves)

    def _node_index(self, mission: Mission) -> dict[str, TaskNode]:
        return {node.node_id: node for node in mission.graph.nodes}

    def _node(self, mission: Mission, node_id: str) -> Optional[TaskNode]:
        for node in mission.graph.nodes:
            if node.node_id == node_id:
                return node
        return None

    def _record_event(self, mission: Mission, event_type: str, label: str, *, status: str = "", node_id: str = "", metadata: dict[str, Any] | None = None) -> None:
        event = MissionEvent(
            event_id=f"evt_{uuid.uuid4().hex[:10]}",
            mission_id=mission.mission_id,
            event_type=event_type,
            label=label,
            status=status,
            node_id=node_id,
            metadata=dict(metadata or {}),
        )
        mission.events.append(event)
        mission.updated_at = _now()
        self._emit("mission_event", {"mission_id": mission.mission_id, "event": event.to_dict(), "status": mission.status})

    def _record_mission_outcome(self, mission: Mission, final_status: str, *, reason: str = "") -> None:
        try:
            control = mission.control_summary()
            quality = mission.quality_summary()
            self.outcome_store.record_outcome(
                request_id=mission.mission_id,
                user_id=str(mission.owner or "local"),
                action=str(mission.route_mode or "mission"),
                channel=str(mission.channel or "dashboard"),
                final_outcome=str(final_status or mission.status or ""),
                success=str(final_status or "").strip().lower() == "completed",
                verification_result={
                    "ok": str(final_status or "").strip().lower() == "completed",
                    "quality_status": str(quality.get("status") or control.get("quality_status") or "").strip(),
                    "reason": str(reason or ""),
                },
                decision_trace={
                    "route_mode": str(mission.route_mode or ""),
                    "timeline": [event.to_dict() for event in mission.events[-10:]],
                },
                metadata={
                    "goal": str(mission.goal or ""),
                    "reason": str(reason or ""),
                    "final_deliverable": str(mission.deliverable or ""),
                    "route_mode": str(mission.route_mode or ""),
                    "evidence_count": int(control.get("evidence_count", 0) or 0),
                    "artifact_count": int(control.get("artifact_count", 0) or 0),
                    "quality_status": str(control.get("quality_status") or quality.get("status") or "").strip(),
                    "node_count": int(control.get("node_count", 0) or 0),
                    "completed_nodes": int(control.get("completed_nodes", 0) or 0),
                    "failed_nodes": int(control.get("failed_nodes", 0) or 0),
                },
            )
            device_id, session_id = self._sync_identifiers(mission)
            self.sync_store.record_outcome(
                request_id=mission.mission_id,
                user_id=str(mission.owner or "local"),
                channel=str(mission.channel or "dashboard"),
                final_outcome=str(final_status or mission.status or ""),
                success=str(final_status or "").strip().lower() == "completed",
                device_id=device_id,
                session_id=session_id,
                metadata={
                    "mission_id": mission.mission_id,
                    "route_mode": str(mission.route_mode or ""),
                    "quality_status": str(control.get("quality_status") or quality.get("status") or "").strip(),
                },
            )
        except Exception as exc:
            logger.debug(f"mission reliability outcome skipped: {exc}")

    def _add_evidence(self, mission: Mission, node: TaskNode, *, kind: str, label: str, path: str = "", summary: str = "", metadata: dict[str, Any] | None = None) -> None:
        record = EvidenceRecord(
            evidence_id=f"ev_{uuid.uuid4().hex[:10]}",
            mission_id=mission.mission_id,
            node_id=node.node_id,
            kind=kind,
            label=label,
            path=str(path or ""),
            summary=str(summary or ""),
            metadata=dict(metadata or {}),
        )
        mission.evidence.append(record)

    def _merge_runtime_metadata(self, mission: Mission, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict) or not payload:
            return
        metadata = dict(mission.metadata or {})
        quality = metadata.get("quality_summary") if isinstance(metadata.get("quality_summary"), dict) else {}
        quality = dict(quality or {})
        for key in _QUALITY_META_KEYS:
            if key == "quality_summary":
                continue
            value = payload.get(key)
            if value in ("", None, [], {}):
                continue
            if key in {"claim_coverage", "critical_claim_coverage", "uncertainty_count", "conflict_count", "manual_review_claim_count", "source_count", "avg_reliability", "team_quality_avg", "team_research_claim_coverage", "team_research_critical_claim_coverage", "team_research_uncertainty_count"}:
                quality[key] = value
            else:
                metadata[key] = value
        nested_quality = payload.get("quality_summary")
        if isinstance(nested_quality, dict) and nested_quality:
            quality.update(nested_quality)
        if quality:
            if "status" not in quality and str(payload.get("quality_status") or "").strip():
                quality["status"] = str(payload.get("quality_status") or "").strip()
            metadata["quality_summary"] = quality
        for key in _WORKFLOW_META_KEYS:
            value = payload.get(key)
            if value in ("", None, [], {}):
                continue
            metadata[key] = value
        claim_map_path = str(payload.get("claim_map_path") or "").strip()
        revision_summary_path = str(payload.get("revision_summary_path") or "").strip()
        if claim_map_path:
            metadata["claim_map_path"] = claim_map_path
        if revision_summary_path:
            metadata["revision_summary_path"] = revision_summary_path
        mission.metadata = metadata

    def _ensure_approval(self, mission: Mission, node: TaskNode) -> ApprovalRequest:
        pending = next((item for item in mission.approvals if item.node_id == node.node_id and item.status == "pending"), None)
        if pending is not None:
            return pending
        approval = ApprovalRequest(
            approval_id=f"apr_{uuid.uuid4().hex[:10]}",
            mission_id=mission.mission_id,
            node_id=node.node_id,
            title=node.title,
            summary=node.objective,
            risk_level=node.risk_level,
            expected_effect=f"{node.specialist} node çalışacak ve çıktı üretecek.",
            rollback_hint="Gerekirse node iptal edilir ve mission durdurulur.",
            metadata={"specialist": node.specialist, "kind": node.kind},
        )
        mission.approvals.append(approval)
        node.status = "waiting_approval"
        mission.status = "waiting_approval"
        self._record_event(
            mission,
            "approval.requested",
            f"{node.title} onay bekliyor",
            status="waiting_approval",
            node_id=node.node_id,
            metadata=approval.to_dict(),
        )
        return approval

    @staticmethod
    def _is_node_approved(mission: Mission, node_id: str) -> bool:
        return any(item.node_id == node_id and item.status == "approved" for item in mission.approvals)

    def _compose_node_prompt(self, mission: Mission, node: TaskNode) -> str:
        contract = mission.success_contract
        criteria = contract.get("criteria") if isinstance(contract.get("criteria"), list) else []
        expected_outputs = contract.get("expected_outputs") if isinstance(contract.get("expected_outputs"), list) else []
        execution_rules: list[str] = []
        if bool(node.metadata.get("read_only")) or bool(contract.get("observe_only")):
            execution_rules.append("- Salt okunur ilerle; kalıcı değişiklik yapma.")
        elif bool(node.metadata.get("dry_run")) or bool(contract.get("dry_run")):
            execution_rules.append("- Dry-run/preview modunda ilerle; kalıcı değişiklik uygulama.")
        if bool(contract.get("requires_plan")) or bool(contract.get("draft_first")):
            execution_rules.append("- Önce planı veya taslağı görünür hale getir, sonra sadece bu node işini yap.")
        if bool(node.metadata.get("approval_required")) or str(contract.get("approval_mode") or "") == "per_step":
            execution_rules.append("- Etkili adımlardan önce kullanıcı onayı bekle.")
        if str(contract.get("verification_mode") or "").strip().lower() == "strict":
            execution_rules.append("- Sonucu sıkı doğrulama ve kanıtla kapat.")
        lines = [
            f"Bu node için gerçek işi yap: {node.objective}",
            "",
            f"Ana görev: {mission.goal}",
            f"Uzmanlık: {node.specialist}",
            f"Node: {node.title}",
        ]
        if criteria:
            lines.extend(["", "Başarı ölçütleri:"] + [f"- {item}" for item in criteria[:5]])
        if expected_outputs:
            lines.extend(["", "Beklenen çıktılar:"] + [f"- {item}" for item in expected_outputs[:5]])
        lines.extend(
            [
                "",
                "Kurallar:",
                "- Local mission runtime içinde çalışıyorsun.",
                "- Yardım teklif etme; işi gerçekten uygula veya doğrulanabilir hata ver.",
                "- Sadece bu node amacına odaklan.",
                "- Mümkünse artifact üret ve kanıt bırak.",
                "- Başarısız olduysa nedeni açıkça yaz.",
            ]
        )
        if execution_rules:
            lines.extend(["", "Yürütme kontrolü:"] + execution_rules)
        return "\n".join(lines).strip()

    def _probe_workspace(self) -> dict[str, Any]:
        root = Path.cwd()
        manifests = []
        try:
            for name in ("package.json", "pyproject.toml", "Cargo.toml", "go.mod", "pom.xml", "build.gradle"):
                candidate = root / name
                if candidate.exists():
                    manifests.append(str(candidate))
        except Exception:
            pass
        file_count = 0
        try:
            for _ in root.iterdir():
                file_count += 1
        except Exception:
            file_count = 0
        return {
            "root": str(root),
            "manifests": manifests,
            "entries": file_count,
        }

    async def _execute_probe_node(self, mission: Mission, node: TaskNode) -> None:
        probe_type = str(node.metadata.get("probe_type") or "").strip().lower()
        if probe_type == "repo":
            payload = self._probe_workspace()
            summary = f"Workspace: {payload.get('root')} | manifests: {len(payload.get('manifests') or [])} | entries: {payload.get('entries')}"
            node.summary = summary
            node.output = json.dumps(payload, ensure_ascii=False)
            self._add_evidence(mission, node, kind="local_probe", label="Repo truth", summary=summary, metadata=payload)
        elif probe_type == "sources":
            queries = [mission.goal, f"{mission.goal} kaynak", f"{mission.goal} rapor"]
            summary = "Kaynak taraması için sorgular hazırlandı."
            node.summary = summary
            node.output = json.dumps({"queries": queries[:3]}, ensure_ascii=False)
            self._add_evidence(mission, node, kind="query_plan", label="Research queries", summary=summary, metadata={"queries": queries[:3]})
        elif probe_type == "screen":
            summary = "Browser/screen görevi için bağlam probe aşaması hazır."
            node.summary = summary
            node.output = summary
            self._add_evidence(mission, node, kind="screen_probe", label="Screen probe", summary=summary)
        elif probe_type == "plan":
            payload = {
                "goal": mission.goal,
                "route_mode": mission.route_mode,
                "autonomy_mode": mission.success_contract.get("autonomy_mode"),
                "approval_mode": mission.success_contract.get("approval_mode"),
                "observe_only": mission.success_contract.get("observe_only"),
                "dry_run": mission.success_contract.get("dry_run"),
            }
            summary = "Yürütme öncesi plan ve çalışma modu görünür hale getirildi."
            node.summary = summary
            node.output = json.dumps(payload, ensure_ascii=False)
            self._add_evidence(mission, node, kind="plan_preview", label="Plan preview", summary=summary, metadata=payload)
        else:
            summary = "Mission bağlamı ve teslim çerçevesi çıkarıldı."
            node.summary = summary
            node.output = summary
            self._add_evidence(mission, node, kind="context_probe", label="Context scan", summary=summary)
        node.status = "completed"
        node.completed_at = _now()
        self._record_event(mission, "node.completed", node.summary or node.title, status="completed", node_id=node.node_id)

    @staticmethod
    def _response_attachments(response: Any) -> list[dict[str, Any]]:
        if hasattr(response, "to_unified_attachments"):
            try:
                payload = response.to_unified_attachments()
                if isinstance(payload, list):
                    return [dict(item) for item in payload if isinstance(item, dict)]
            except Exception:
                return []
        raw = getattr(response, "attachments", [])
        if isinstance(raw, list):
            out = []
            for item in raw:
                if hasattr(item, "to_dict"):
                    out.append(dict(item.to_dict()))
                elif isinstance(item, dict):
                    out.append(dict(item))
            return out
        return []

    async def _execute_specialist_node(self, mission: Mission, node: TaskNode, agent: Any) -> None:
        if (
            bool(node.metadata.get("approval_required"))
            or node.risk_level == "high"
            or (node.risk_level == "medium" and str(mission.mode).lower() == "audit")
        ) and not self._is_node_approved(mission, node.node_id):
            self._ensure_approval(mission, node)
            return
        if agent is None or not hasattr(agent, "process_envelope"):
            node.status = "failed"
            node.completed_at = _now()
            node.summary = "Agent unavailable"
            self._record_event(mission, "node.failed", node.summary, status="failed", node_id=node.node_id)
            return

        direct_response = None
        read_only = bool(node.metadata.get("read_only") or node.metadata.get("dry_run"))
        if (
            node.specialist in {"file", "browser"}
            and hasattr(agent, "_run_direct_intent")
            and hasattr(agent, "_should_run_direct_intent")
            and not read_only
        ):
            direct_intent = _infer_file_node_intent(mission, node) if node.specialist == "file" else _infer_browser_node_intent(node)
            if not isinstance(direct_intent, dict) or not direct_intent:
                direct_intent = _route_specialist_intent(agent, node.objective, str(mission.owner or "local"), mission.goal)
            if not isinstance(direct_intent, dict) or not direct_intent:
                if hasattr(agent, "intent_parser"):
                    try:
                        direct_intent = agent.intent_parser.parse(node.objective)
                    except Exception:
                        direct_intent = {}
            if isinstance(direct_intent, dict) and agent._should_run_direct_intent(direct_intent, node.objective):
                timeout_s = 45.0 if node.specialist in {"browser", "file"} else 90.0
                try:
                    direct_text = await asyncio.wait_for(
                        agent._run_direct_intent(direct_intent, node.objective, "operator", [], user_id=mission.owner),
                        timeout=timeout_s,
                    )
                except asyncio.TimeoutError:
                    node.status = "failed"
                    node.completed_at = _now()
                    node.summary = f"Node zaman aşımına uğradı ({int(timeout_s)}s)."
                    self._record_event(
                        mission,
                        "node.failed",
                        node.summary,
                        status="failed",
                        node_id=node.node_id,
                        metadata={"specialist": node.specialist, "timeout_s": timeout_s},
                    )
                    return
                direct_payload = getattr(agent, "_last_direct_intent_payload", None)
                if (
                    node.specialist == "browser"
                    and isinstance(direct_payload, dict)
                    and not _attachments_from_direct_payload(direct_payload)
                    and hasattr(agent, "_execute_tool")
                ):
                    try:
                        proof = await agent._execute_tool(
                            "take_screenshot",
                            {"filename": f"mission_browser_proof_{int(time.time() * 1000)}.png"},
                            user_input=node.objective,
                            step_name=f"{node.title} proof",
                        )
                        if isinstance(proof, dict):
                            proof_path = str(proof.get("path") or proof.get("output_path") or "").strip()
                            if proof_path:
                                direct_payload = dict(direct_payload)
                                screenshots = list(direct_payload.get("screenshots") or [])
                                if proof_path not in screenshots:
                                    screenshots.append(proof_path)
                                direct_payload["screenshots"] = screenshots
                    except Exception:
                        pass
                direct_error = str((direct_payload or {}).get("error") or "").strip() if isinstance(direct_payload, dict) else ""
                direct_success = bool((direct_payload or {}).get("success", True)) if isinstance(direct_payload, dict) else not _has_error_signal(direct_text)
                direct_response = SimpleNamespace(
                    run_id="",
                    text=str(direct_text or ""),
                    attachments=_attachments_from_direct_payload(
                        direct_payload if isinstance(direct_payload, dict) else {},
                        text=str(direct_text or ""),
                    ),
                    evidence_manifest_path="",
                    status="success" if direct_success else "failed",
                    error=direct_error,
                    metadata={},
                )

        raw_prompt_ok = (
            node.specialist in {"file", "browser", "code"}
            and not read_only
            and not bool(node.metadata.get("approval_required"))
            and not bool(mission.success_contract.get("requires_plan"))
            and not bool(mission.success_contract.get("draft_first"))
        )
        prompt = node.objective if raw_prompt_ok else self._compose_node_prompt(mission, node)
        if direct_response is not None:
            response = direct_response
        else:
            timeout_s = 45.0 if node.specialist in {"browser", "file"} else 90.0
            try:
                response = await asyncio.wait_for(
                    agent.process_envelope(
                        prompt,
                        channel=mission.channel,
                        metadata={
                            "skip_mission_control": True,
                            "mission_id": mission.mission_id,
                            "mission_node_id": node.node_id,
                            "adaptive_mode": mission.mode.lower(),
                            "local_only": True,
                        },
                    ),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                node.status = "failed"
                node.completed_at = _now()
                node.summary = f"Node zaman aşımına uğradı ({int(timeout_s)}s)."
                self._record_event(
                    mission,
                    "node.failed",
                    node.summary,
                    status="failed",
                    node_id=node.node_id,
                    metadata={"specialist": node.specialist, "timeout_s": timeout_s},
                )
                return
        response_metadata = getattr(response, "metadata", {})
        if isinstance(response_metadata, dict) and response_metadata:
            self._merge_runtime_metadata(mission, response_metadata)
        text = _compact(getattr(response, "text", "") or "")
        status = str(getattr(response, "status", "") or "success").strip().lower()
        error_text = str(getattr(response, "error", "") or "").strip()
        node.run_id = str(getattr(response, "run_id", "") or "")
        node.output = text
        node.summary = text[:260]
        node.completed_at = _now()
        manifest_path = str(getattr(response, "evidence_manifest_path", "") or "")
        attachments = self._response_attachments(response)
        run_summary = (resolve_runs_root() / node.run_id / "summary.txt").expanduser() if node.run_id else None
        has_run_summary = bool(run_summary and run_summary.exists())
        has_artifact_evidence = bool(manifest_path or attachments or has_run_summary)
        has_concrete_artifact = _has_concrete_artifact(node, attachments, text)
        error_signal = _has_error_signal(status, error_text, text, node.summary)
        requires_artifact = node.specialist in {"code", "browser", "file", "research", "data"} and not read_only
        if (
            error_signal
            or status not in {"success", "ok"}
            or (requires_artifact and not has_artifact_evidence)
            or (node.specialist in {"code", "browser", "file"} and not read_only and not has_concrete_artifact)
        ):
            node.status = "failed"
            failure_reason = (
                error_text
                or getattr(response, "reason", "")
                or getattr(response, "summary", "")
                or ("Somut artifact üretilmedi." if node.specialist in {"code", "browser", "file"} and not read_only and not has_concrete_artifact else "")
                or text
                or "Node failed"
            )
            self._record_event(
                mission,
                "node.failed",
                str(failure_reason),
                status="failed",
                node_id=node.node_id,
                metadata={"run_id": node.run_id, "status": status},
            )
            if manifest_path:
                self._add_evidence(
                    mission,
                    node,
                    kind="manifest",
                    label=f"{node.title} evidence manifest",
                    path=manifest_path,
                    summary="Run evidence manifest",
                    metadata={"run_id": node.run_id},
                )
            return

        node.status = "completed"
        if manifest_path:
            self._add_evidence(
                mission,
                node,
                kind="manifest",
                label=f"{node.title} evidence manifest",
                path=manifest_path,
                summary="Run evidence manifest",
                metadata={"run_id": node.run_id},
            )
        for attachment in self._response_attachments(response):
            path = str(attachment.get("path") or "").strip()
            label = str(attachment.get("name") or Path(path).name or node.title).strip()
            self._add_evidence(
                mission,
                node,
                kind=str(attachment.get("type") or "artifact"),
                label=label,
                path=path,
                summary=str(attachment.get("source") or "attachment"),
                metadata=attachment,
            )
        if node.run_id:
            run_summary = (resolve_runs_root() / node.run_id / "summary.txt").expanduser()
            if run_summary.exists():
                self._add_evidence(
                    mission,
                    node,
                    kind="summary",
                    label=f"{node.title} summary",
                    path=str(run_summary),
                    summary="Run summary artifact",
                    metadata={"run_id": node.run_id},
                )
        if text:
            self._add_evidence(
                mission,
                node,
                kind="response_excerpt",
                label=f"{node.title} excerpt",
                summary=text[:220],
                metadata={"run_id": node.run_id, "status": status},
            )
        self._record_event(
            mission,
            "node.completed",
            node.summary or node.title,
            status="completed",
            node_id=node.node_id,
            metadata={"run_id": node.run_id, "specialist": node.specialist},
        )

    async def _execute_verifier_node(self, mission: Mission, node: TaskNode) -> None:
        strictness = str(mission.success_contract.get("verification_mode") or "light").strip().lower()
        work_nodes = [item for item in mission.graph.nodes if item.node_id not in {"planner", "verifier", "delivery"}]
        failed = [item.node_id for item in work_nodes if item.status == "failed"]
        error_nodes: list[str] = []
        artifact_nodes: set[str] = set()
        evidence_map = {item.node_id: 0 for item in work_nodes}
        for record in mission.evidence:
            if record.node_id in evidence_map:
                evidence_map[record.node_id] += 1
                if str(record.path or "").strip():
                    artifact_nodes.add(record.node_id)
        for item in work_nodes:
            if _has_error_signal(item.output, item.summary):
                error_nodes.append(item.node_id)
        missing_evidence = [node_id for node_id, count in evidence_map.items() if count == 0]
        artifact_missing = [
            item.node_id
            for item in work_nodes
            if (
                item.kind != "probe"
                and item.specialist in {"code", "browser", "file"}
                and not bool(item.metadata.get("read_only") or item.metadata.get("dry_run"))
                and item.node_id not in artifact_nodes
            )
        ]
        passes = not failed and not error_nodes
        if strictness != "minimal":
            passes = passes and not missing_evidence and not artifact_missing
        summary_parts = [f"completed_nodes={len([item for item in work_nodes if item.status == 'completed'])}/{len(work_nodes)}"]
        if failed:
            summary_parts.append("failed=" + ", ".join(failed))
        if error_nodes:
            summary_parts.append("error_nodes=" + ", ".join(error_nodes))
        if missing_evidence:
            summary_parts.append("missing_evidence=" + ", ".join(missing_evidence))
        if artifact_missing:
            summary_parts.append("artifact_missing=" + ", ".join(artifact_missing))
        if passes:
            summary_parts.append("verification=passed")
        ml_verify = {}
        try:
            ml_verify = self.verifier_service.score(
                {"kind": "mission_verifier", "specialist": "verifier"},
                {
                    "status": "success" if passes else "failed",
                    "summary": "; ".join(summary_parts),
                    "errors": failed + error_nodes + missing_evidence + artifact_missing,
                    "artifact_count": len(artifact_nodes),
                },
                [record.to_dict() for record in mission.evidence if record.node_id in evidence_map],
            )
        except Exception as exc:
            logger.debug(f"mission ml verifier skipped: {exc}")
        node.summary = "; ".join(summary_parts)
        node.output = node.summary
        node.completed_at = _now()
        node.status = "completed" if passes else "failed"
        node.metadata["ml_verifier"] = dict(ml_verify or {})
        self._add_evidence(
            mission,
            node,
            kind="verification",
            label="Verification summary",
            summary=node.summary,
            metadata={
                "strictness": strictness,
                "failed_nodes": failed,
                "missing_evidence": missing_evidence,
                "ml_verifier": dict(ml_verify or {}),
            },
        )
        self._record_event(
            mission,
            "node.completed" if passes else "node.failed",
            node.summary,
            status=node.status,
            node_id=node.node_id,
        )

    async def _execute_delivery_node(self, mission: Mission, node: TaskNode) -> None:
        completed = [
            item for item in mission.graph.nodes
            if item.node_id not in {"planner", "verifier", "delivery"} and item.status == "completed"
        ]
        lines = [
            f"Misyon: {mission.goal}",
            f"Mod: {mission.mode}",
            "",
            "Çıktı Özeti:",
        ]
        for item in completed[:6]:
            lines.append(f"- [{item.specialist}] {item.summary or item.title}")
        if mission.evidence:
            lines.extend(["", "Kanıtlar:"])
            for record in mission.evidence[:6]:
                target = record.path or record.summary
                if target:
                    lines.append(f"- {record.label}: {target}")
        mission.deliverable = "\n".join(lines).strip()
        node.summary = "Final deliverable hazırlandı."
        node.output = mission.deliverable
        node.status = "completed"
        node.completed_at = _now()
        self._record_event(mission, "mission.deliverable", node.summary, status="completed", node_id=node.node_id)

    async def _execute_node(self, mission: Mission, node: TaskNode, agent: Any) -> None:
        node.status = "running"
        node.started_at = _now()
        self._record_event(mission, "node.started", node.title, status="running", node_id=node.node_id, metadata={"specialist": node.specialist})
        if node.kind == "planner":
            node.summary = "Başarı sözleşmesi ve görev grafiği hazır."
            node.output = json.dumps(_json_safe(mission.success_contract), ensure_ascii=False)
            node.status = "completed"
            node.completed_at = _now()
            self._add_evidence(mission, node, kind="contract", label="Mission contract", summary=node.summary, metadata=mission.success_contract)
            self._record_event(mission, "node.completed", node.summary, status="completed", node_id=node.node_id)
            return
        if node.kind == "probe":
            await self._execute_probe_node(mission, node)
            return
        if node.specialist == "verifier":
            await self._execute_verifier_node(mission, node)
            return
        if node.specialist == "comms":
            await self._execute_delivery_node(mission, node)
            return
        await self._execute_specialist_node(mission, node, agent)

    async def create_mission(
        self,
        goal: str,
        *,
        user_id: str = "local",
        channel: str = "dashboard",
        mode: str = "Balanced",
        attachments: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        agent: Any = None,
        auto_start: bool = True,
    ) -> Mission:
        goal_text = _compact(goal)
        route = get_cowork_runtime().route_command(goal_text, metadata={"channel": channel, "user_id": user_id})
        request_contract: dict[str, Any] = {}
        try:
            cap_router = get_capability_router()
            cap_plan = cap_router.route(goal_text)
            request_contract = cap_router.build_request_contract(
                goal_text,
                domain=str(getattr(cap_plan, "domain", "") or ""),
                confidence=float(getattr(cap_plan, "confidence", 0.0) or 0.0),
                route_mode=str(getattr(cap_plan, "suggested_job_type", "") or ""),
                output_artifacts=list(getattr(cap_plan, "output_artifacts", []) or []),
                quality_checklist=list(getattr(cap_plan, "quality_checklist", []) or []),
                metadata={"channel": channel, "user_id": user_id},
            ).to_dict()
        except Exception as exc:
            logger.debug(f"request contract build skipped: {exc}")
        route_mode = str(getattr(route, "mode", "") or "").strip().lower() or "task"
        request_content_kind = str(request_contract.get("content_kind") or "").strip().lower()
        if request_content_kind in {"web_project", "code_project"} and route_mode in {"communication", "task", "document"}:
            route_mode = "code"
        elif request_content_kind == "research_delivery" and route_mode in {"communication", "task", "document"}:
            route_mode = "research"
        elif request_content_kind == "presentation" and route_mode in {"communication", "task"}:
            route_mode = "document"
        elif request_content_kind == "spreadsheet" and route_mode in {"communication", "task", "document"}:
            route_mode = "data"
        elif str(request_contract.get("route_mode") or "").strip().lower() == "file_operations":
            specialist_hint = self._select_specialist(goal_text, route_mode="file_operations")
            if specialist_hint == "code":
                route_mode = "code"
            elif route_mode in {"communication", "task", "document", "file"}:
                route_mode = "file"
        if route_mode in {"communication", "task"}:
            specialist_hint = self._select_specialist(goal_text, route_mode=route_mode)
            if specialist_hint == "code":
                route_mode = "code"
            elif specialist_hint == "research":
                route_mode = "research"
            elif specialist_hint == "browser":
                route_mode = "browser"
            elif specialist_hint == "data":
                route_mode = "data"
            elif specialist_hint == "file":
                route_mode = "file"
            elif specialist_hint == "document":
                route_mode = "document"
        preferences = self._execution_preferences(goal_text, str(mode or "Balanced"))
        success_contract = self._success_contract(goal_text, route_mode, str(mode or "Balanced"), preferences)
        graph = self._build_graph(goal_text, route_mode, str(mode or "Balanced"), preferences)
        mission = Mission(
            mission_id=f"mission_{uuid.uuid4().hex[:10]}",
            goal=goal_text,
            owner=str(user_id or "local"),
            channel=str(channel or "dashboard"),
            mode=str(mode or "Balanced"),
            route_mode=route_mode,
            risk_profile=self._risk_from_text(goal_text, route_mode=route_mode),
            success_contract=success_contract,
            graph=graph,
            status="queued",
            attachments=[str(item) for item in list(attachments or []) if str(item).strip()],
            metadata={
                "local_only": True,
                "request_contract": request_contract,
                "request_preview": str(request_contract.get("preview") or ""),
                "execution_preferences": dict(preferences),
                "autonomy_mode": str(success_contract.get("autonomy_mode") or "assisted"),
                **dict(metadata or {}),
            },
        )
        async with self._lock:
            self._missions[mission.mission_id] = mission
            self._record_event(mission, "mission.created", "Mission oluşturuldu", status="queued", metadata={"route_mode": route_mode})
            try:
                self.outcome_store.record_decision(
                    request_id=mission.mission_id,
                    user_id=str(user_id or "local"),
                    kind="mission_route",
                    selected=str(route_mode or "task"),
                    confidence=float(request_contract.get("confidence", 0.0) or 0.0),
                    raw_confidence=float(request_contract.get("confidence", 0.0) or 0.0),
                    channel=str(channel or "dashboard"),
                    source="mission_control",
                    metadata={
                        "content_kind": str(request_contract.get("content_kind") or ""),
                        "preview": str(request_contract.get("preview") or ""),
                    },
                )
            except Exception as exc:
                logger.debug(f"mission route decision telemetry skipped: {exc}")
            try:
                device_id, session_id = self._sync_identifiers(mission)
                self.sync_store.record_request(
                    request_id=mission.mission_id,
                    user_id=str(user_id or "local"),
                    channel=str(channel or "dashboard"),
                    request_text=goal_text,
                    request_class=self._sync_request_class(route_mode),
                    execution_path="fast" if route_mode in {"file", "browser", "task"} else "deep",
                    device_id=device_id,
                    session_id=session_id,
                    state="queued",
                    metadata={
                        "mission_id": mission.mission_id,
                        "route_mode": route_mode,
                        "mode": str(mode or "Balanced"),
                    },
                )
            except Exception as exc:
                logger.debug(f"mission sync request skipped: {exc}")
            self._save()
        if auto_start:
            await self.start_mission(mission.mission_id, agent=agent)
        return mission

    async def start_mission(self, mission_id: str, *, agent: Any = None) -> None:
        existing = self._running.get(mission_id)
        if existing and not existing.done():
            return
        async def _runner():
            try:
                await self.run_mission(mission_id, agent=agent)
            finally:
                self._running.pop(mission_id, None)
        self._running[mission_id] = asyncio.create_task(_runner())

    async def run_mission(self, mission_id: str, *, agent: Any = None) -> Optional[Mission]:
        async with self._lock:
            mission = self._missions.get(mission_id)
            if mission is None:
                return None
            if mission.status not in {"queued", "running", "waiting_approval"}:
                return mission
            mission.status = "running"
            self._record_event(mission, "mission.running", "Mission çalışıyor", status="running")
            try:
                device_id, session_id = self._sync_identifiers(mission)
                self.sync_store.record_stage(
                    request_id=mission.mission_id,
                    user_id=str(mission.owner or "local"),
                    channel=str(mission.channel or "dashboard"),
                    state="running",
                    device_id=device_id,
                    session_id=session_id,
                    metadata={"mission_id": mission.mission_id, "route_mode": str(mission.route_mode or "")},
                )
            except Exception as exc:
                logger.debug(f"mission sync running skipped: {exc}")
            self._save()

        while True:
            async with self._lock:
                mission = self._missions.get(mission_id)
                if mission is None:
                    return None
                index = self._node_index(mission)
                if all(node.status == "completed" for node in mission.graph.nodes):
                    mission.status = "completed"
                    self._record_event(mission, "mission.completed", "Mission tamamlandı", status="completed")
                    self._record_mission_outcome(mission, "completed")
                    self._save()
                    return mission
                if any(node.status == "failed" for node in mission.graph.nodes if node.node_id == "verifier"):
                    mission.status = "failed"
                    self._record_event(mission, "mission.failed", "Verifier başarısız", status="failed")
                    self._record_mission_outcome(mission, "failed", reason="verifier_failed")
                    self._save()
                    return mission
                pending_approval = any(item.status == "pending" for item in mission.approvals)
                ready = [
                    node for node in mission.graph.nodes
                    if node.status == "queued" and all(index[dep].status == "completed" for dep in node.depends_on if dep in index)
                ]
                if not ready:
                    if pending_approval or any(node.status == "waiting_approval" for node in mission.graph.nodes):
                        mission.status = "waiting_approval"
                        try:
                            device_id, session_id = self._sync_identifiers(mission)
                            self.sync_store.record_stage(
                                request_id=mission.mission_id,
                                user_id=str(mission.owner or "local"),
                                channel=str(mission.channel or "dashboard"),
                                state="waiting_approval",
                                device_id=device_id,
                                session_id=session_id,
                                metadata={"mission_id": mission.mission_id},
                            )
                        except Exception as exc:
                            logger.debug(f"mission sync waiting approval skipped: {exc}")
                        self._save()
                        return mission
                    failed_nodes = [node for node in mission.graph.nodes if node.status == "failed"]
                    if failed_nodes:
                        mission.status = "failed"
                        self._record_event(
                            mission,
                            "mission.failed",
                            f"Başarısız düğümler: {', '.join(node.node_id for node in failed_nodes[:4])}",
                            status="failed",
                        )
                        self._record_mission_outcome(
                            mission,
                            "failed",
                            reason=f"failed_nodes:{','.join(node.node_id for node in failed_nodes[:4])}",
                        )
                        self._save()
                        return mission
                    self._save()
                    return mission
                self._save()

            await asyncio.gather(*(self._execute_node(mission, node, agent) for node in ready))
            async with self._lock:
                mission = self._missions.get(mission_id)
                if mission is not None:
                    mission.updated_at = _now()
                    self._save()

    def list_missions(self, *, owner: str = "", limit: int = 30) -> list[dict[str, Any]]:
        rows = []
        for mission in self._missions.values():
            if owner and str(mission.owner) != str(owner):
                continue
            rows.append(mission.snapshot())
        rows.sort(key=lambda item: float(item.get("updated_at") or 0.0), reverse=True)
        return rows[: max(1, int(limit or 30))]

    def get_mission(self, mission_id: str) -> Optional[Mission]:
        return self._missions.get(str(mission_id or "").strip())

    def overview(self, *, owner: str = "") -> dict[str, Any]:
        missions = [mission for mission in self._missions.values() if not owner or str(mission.owner) == str(owner)]
        by_status: dict[str, int] = {}
        for mission in missions:
            by_status[mission.status] = int(by_status.get(mission.status, 0)) + 1
        active = len([mission for mission in missions if mission.status in {"queued", "running", "waiting_approval"}])
        return {
            "ok": True,
            "generated_at": _now(),
            "total": len(missions),
            "active": active,
            "waiting_approval": len([mission for mission in missions if mission.status == "waiting_approval"]),
            "completed": len([mission for mission in missions if mission.status == "completed"]),
            "failed": len([mission for mission in missions if mission.status == "failed"]),
            "skills": len(self._skills),
            "local_only": True,
            "by_status": by_status,
        }

    def pending_approvals(self, *, owner: str = "") -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for mission in self._missions.values():
            if owner and str(mission.owner) != str(owner):
                continue
            for approval in mission.approvals:
                if approval.status != "pending":
                    continue
                payload = approval.to_dict()
                payload["goal"] = mission.goal
                items.append(payload)
        items.sort(key=lambda item: float(item.get("created_at") or 0.0), reverse=True)
        return items

    async def resolve_approval(self, approval_id: str, approved: bool, *, note: str = "", agent: Any = None) -> Optional[Mission]:
        async with self._lock:
            for mission in self._missions.values():
                for approval in mission.approvals:
                    if approval.approval_id != approval_id:
                        continue
                    approval.status = "approved" if approved else "denied"
                    approval.resolved_at = _now()
                    approval.metadata["note"] = str(note or "")
                    node = self._node(mission, approval.node_id)
                    if node is not None:
                        node.status = "queued" if approved else "failed"
                        if not approved:
                            node.summary = "Approval denied"
                    mission.status = "queued" if approved else "failed"
                    self._record_event(
                        mission,
                        "approval.resolved",
                        f"{approval.title} {'onaylandı' if approved else 'reddedildi'}",
                        status=approval.status,
                        node_id=approval.node_id,
                    )
                    self._save()
                    if approved:
                        await self.start_mission(mission.mission_id, agent=agent)
                    return mission
        return None

    def list_skills(self) -> list[dict[str, Any]]:
        items = [skill.to_dict() for skill in self._skills.values()]
        items.sort(key=lambda item: float(item.get("created_at") or 0.0), reverse=True)
        return items

    def save_skill(self, mission_id: str, *, name: str = "") -> Optional[SkillRecipe]:
        mission = self.get_mission(mission_id)
        if mission is None:
            return None
        preview = mission.preview_summary()
        success_contract = dict(mission.success_contract or {})
        recipe = SkillRecipe(
            recipe_id=f"skill_{uuid.uuid4().hex[:10]}",
            name=str(name or _slug(mission.goal).replace("-", " ").title()),
            source_mission_id=mission_id,
            input_schema={"goal": "string", "mode": "Balanced|Sprint|Audit"},
            task_graph_template=mission.graph.to_dict(),
            tool_policy={"local_only": True, "risk_profile": mission.risk_profile},
            verification_rules=[str(item) for item in list(mission.success_contract.get("criteria") or []) if str(item).strip()],
            output_contract={
                "route_mode": mission.route_mode,
                "evidence_required": True,
                "content_kind": success_contract.get("content_kind") or preview.get("content_kind") or "",
                "expected_outputs": list(success_contract.get("expected_outputs") or preview.get("output_formats") or []),
                "quality_contract": list(success_contract.get("quality_contract") or preview.get("quality_contract") or []),
                "style_profile": success_contract.get("style_profile") or preview.get("style_profile") or "",
                "preview": preview.get("preview") or "",
            },
            risk_profile=mission.risk_profile,
        )
        self._skills[recipe.recipe_id] = recipe
        self._save()
        self._emit("skill_saved", {"mission_id": mission_id, "skill": recipe.to_dict()})
        return recipe

    def memory_snapshot(self, *, user_id: str = "local") -> dict[str, Any]:
        profile = memory_v2.profile
        profile_records = [
            MemoryRecord(
                memory_type="profile",
                scope="profile",
                title="Kalıcı Tercihler",
                content=json.dumps(_json_safe(asdict(profile)), ensure_ascii=False),
                confidence=1.0,
            ).to_dict()
        ]

        workflow_records = [
            MemoryRecord(
                memory_type="workflow",
                scope="workflow",
                title=str(skill.get("name") or "Skill"),
                content=str(skill.get("output_contract") or ""),
                confidence=0.9,
                last_used_at=float(skill.get("created_at") or _now()),
            ).to_dict()
            for skill in self.list_skills()[:6]
        ]

        task_records = [
            MemoryRecord(
                memory_type="task",
                scope="task",
                title=str(row.get("goal") or "Mission"),
                content=str(row.get("deliverable_preview") or ""),
                confidence=0.8,
                last_used_at=float(row.get("updated_at") or _now()),
            ).to_dict()
            for row in self.list_missions(owner=user_id, limit=6)
        ]

        recent_conv = []
        try:
            recent_conv = conversation_memory.get_history(int(user_id), limit=4) if str(user_id).isdigit() else []
        except Exception:
            recent_conv = []
        if recent_conv:
            task_records.append(
                MemoryRecord(
                    memory_type="task",
                    scope="conversation",
                    title="Son Konuşmalar",
                    content="\n".join(f"{row.get('role')}: {row.get('content')}" for row in recent_conv[-4:]),
                    confidence=0.7,
                ).to_dict()
            )

        evidence_records: list[dict[str, Any]] = []
        for mission in self._missions.values():
            if str(mission.owner) != str(user_id):
                continue
            for record in mission.evidence[-4:]:
                evidence_records.append(
                    MemoryRecord(
                        memory_type="evidence",
                        scope="evidence",
                        title=record.label,
                        content=record.path or record.summary,
                        confidence=0.95 if record.path else 0.7,
                        last_used_at=float(record.created_at or _now()),
                        metadata={"mission_id": mission.mission_id, "node_id": record.node_id},
                ).to_dict()
            )
        evidence_records.sort(key=lambda item: float(item.get("last_used_at") or 0.0), reverse=True)
        memory_summary = {
            "profile_count": len(profile_records),
            "workflow_count": len(workflow_records),
            "task_count": len(task_records),
            "evidence_count": len(evidence_records),
            "profile_preview": str(profile_records[0].get("content") or "")[:200] if profile_records else "",
            "workflow_preview": str(workflow_records[0].get("content") or "")[:200] if workflow_records else "",
            "task_preview": str(task_records[0].get("content") or "")[:200] if task_records else "",
            "evidence_preview": str(evidence_records[0].get("content") or "")[:200] if evidence_records else "",
        }
        return {
            "ok": True,
            "profile": profile_records,
            "workflow": workflow_records,
            "task": task_records[:8],
            "evidence": evidence_records[:8],
            "summary": memory_summary,
            "scopes": {
                "profile": {"editable": True, "count": len(profile_records)},
                "workflow": {"editable": True, "count": len(workflow_records)},
                "task": {"editable": True, "count": len(task_records)},
                "evidence": {"editable": False, "count": len(evidence_records)},
            },
        }


_mission_runtime: MissionRuntime | None = None


def get_mission_runtime(*, storage_dir: Path | None = None) -> MissionRuntime:
    global _mission_runtime
    if storage_dir is not None:
        return MissionRuntime(storage_dir=storage_dir)
    if _mission_runtime is None:
        _mission_runtime = MissionRuntime()
    return _mission_runtime


__all__ = [
    "ApprovalRequest",
    "EvidenceRecord",
    "MemoryRecord",
    "Mission",
    "MissionEvent",
    "MissionGraph",
    "MissionRuntime",
    "SkillRecipe",
    "TaskNode",
    "get_mission_runtime",
]
