from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.elyan_config import elyan_config
from core.skills.catalog import get_builtin_skill_catalog, get_builtin_workflow_catalog
from core.task_executor import TaskExecutor
from core.text_artifacts import DEFAULT_SAVE_MARKERS, default_summary_path
from tools import AVAILABLE_TOOLS
from utils.logger import get_logger

logger = get_logger("skill_manager")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class SkillInfo:
    name: str
    version: str
    description: str
    category: str
    source: str
    required_tools: List[str]
    dependencies: List[str]
    commands: List[str]
    installed: bool = False
    enabled: bool = False
    path: str = ""
    installed_at: str = ""
    updated_at: str = ""
    health_ok: bool = True
    missing_tools: List[str] = None
    missing_dependencies: List[str] = None
    blocked_tools: List[str] = None
    approval_tools: List[str] = None
    runtime_ready: bool = False
    coverage_score: float = 0.0
    tool_access: Dict[str, Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["missing_tools"] = data.get("missing_tools") or []
        data["missing_dependencies"] = data.get("missing_dependencies") or []
        data["blocked_tools"] = data.get("blocked_tools") or []
        data["approval_tools"] = data.get("approval_tools") or []
        data["tool_access"] = data.get("tool_access") or {}
        return data


class SkillManager:
    """
    Skill lifecycle manager:
    - catalog discovery
    - install/remove
    - enable/disable
    - requirement checks
    """

    def __init__(self):
        self.skills_dir = Path.home() / ".elyan" / "skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def _enabled_set(self) -> set[str]:
        raw = elyan_config.get("skills.enabled", [])
        if not isinstance(raw, list):
            return set()
        return {str(x).strip() for x in raw if str(x).strip()}

    def _set_enabled_set(self, enabled: set[str]) -> None:
        elyan_config.set("skills.enabled", sorted(enabled))

    def _enabled_workflow_set(self) -> set[str]:
        raw = elyan_config.get("skills.workflows.enabled", [])
        if not isinstance(raw, list):
            return set()
        return {str(x).strip() for x in raw if str(x).strip()}

    def _set_enabled_workflow_set(self, enabled: set[str]) -> None:
        elyan_config.set("skills.workflows.enabled", sorted(enabled))

    def _manifest_path(self, name: str) -> Path:
        return self.skills_dir / name / "skill.json"

    def _skill_dir(self, name: str) -> Path:
        return self.skills_dir / name

    @staticmethod
    def _sanitize_name(name: str) -> str:
        return (name or "").strip().lower().replace(" ", "_").replace("-", "_")

    def _read_manifest(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Skill manifest okunamadı: {path} ({e})")
            return None

    def _write_manifest(self, name: str, data: Dict[str, Any]) -> Path:
        target_dir = self._skill_dir(name)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / "skill.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def _available_tools_set(self) -> set[str]:
        return {str(k).strip() for k in AVAILABLE_TOOLS.keys()}

    def _build_skill_info(self, raw: Dict[str, Any], *, installed: bool, enabled_set: set[str], path: str = "") -> SkillInfo:
        name = self._sanitize_name(raw.get("name", ""))
        required_tools = [str(x).strip() for x in raw.get("required_tools", []) if str(x).strip()]
        dependencies = [str(x).strip() for x in raw.get("dependencies", []) if str(x).strip()]
        commands = [str(x).strip() for x in raw.get("commands", []) if str(x).strip()]
        enabled = name in enabled_set

        available_tools = self._available_tools_set()
        missing_tools = sorted([t for t in required_tools if t not in available_tools])
        # Dependencies check intentionally lightweight; package-level validation can be expensive.
        missing_deps: List[str] = []
        blocked_tools: List[str] = []
        approval_tools: List[str] = []
        tool_access: Dict[str, Dict[str, Any]] = {}
        try:
            from security.tool_policy import tool_policy

            for tool in required_tools:
                group = tool_policy.infer_group(tool) or "other"
                access = tool_policy.check_access(tool, group)
                allowed = bool(access.get("allowed", False))
                requires_approval = bool(access.get("requires_approval", False))
                if not allowed:
                    blocked_tools.append(tool)
                elif requires_approval:
                    approval_tools.append(tool)
                tool_access[tool] = {
                    "group": group,
                    "allowed": allowed,
                    "requires_approval": requires_approval,
                    "reason": str(access.get("reason", "") or ""),
                }
        except Exception:
            tool_access = {}

        total_tools = len(required_tools)
        ready_tools = max(0, total_tools - len(missing_tools) - len(blocked_tools))
        coverage_score = round((ready_tools / max(1, total_tools)), 2)
        info = SkillInfo(
            name=name,
            version=str(raw.get("version", "1.0.0")),
            description=str(raw.get("description", "")),
            category=str(raw.get("category", "general")),
            source=str(raw.get("source", "local")),
            required_tools=required_tools,
            dependencies=dependencies,
            commands=commands,
            installed=installed,
            enabled=enabled,
            path=path,
            installed_at=str(raw.get("installed_at", "")),
            updated_at=str(raw.get("updated_at", "")),
            health_ok=(len(missing_tools) == 0 and len(missing_deps) == 0),
            missing_tools=missing_tools,
            missing_dependencies=missing_deps,
            blocked_tools=sorted(blocked_tools),
            approval_tools=sorted(approval_tools),
            runtime_ready=(len(missing_tools) == 0 and len(blocked_tools) == 0),
            coverage_score=coverage_score,
            tool_access=tool_access,
        )
        return info

    def _load_installed_from_disk(self) -> Dict[str, SkillInfo]:
        enabled = self._enabled_set()
        installed: Dict[str, SkillInfo] = {}
        for manifest in self.skills_dir.glob("*/skill.json"):
            raw = self._read_manifest(manifest)
            if not raw:
                continue
            name = self._sanitize_name(raw.get("name", manifest.parent.name))
            if not name:
                continue
            raw["name"] = name
            installed[name] = self._build_skill_info(raw, installed=True, enabled_set=enabled, path=str(manifest.parent))
        return installed

    def _catalog_infos(self, enabled_set: set[str], installed_names: set[str]) -> Dict[str, SkillInfo]:
        out: Dict[str, SkillInfo] = {}
        for name, raw in get_builtin_skill_catalog().items():
            normalized = self._sanitize_name(name)
            entry = dict(raw)
            entry["name"] = normalized
            out[normalized] = self._build_skill_info(
                entry,
                installed=(normalized in installed_names),
                enabled_set=enabled_set,
                path=str(self._skill_dir(normalized)) if normalized in installed_names else "",
            )
        return out

    def list_skills(self, *, available: bool = False, enabled_only: bool = False, query: str = "") -> List[Dict[str, Any]]:
        enabled = self._enabled_set()
        installed = self._load_installed_from_disk()
        installed_names = set(installed.keys())
        catalog = self._catalog_infos(enabled, installed_names)

        if available:
            merged = catalog
            # Include installed custom skills not in catalog.
            for name, info in installed.items():
                if name not in merged:
                    merged[name] = info
        else:
            merged = installed

        items = list(merged.values())
        if enabled_only:
            items = [i for i in items if i.enabled]
        if query:
            q = query.lower().strip()
            items = [
                i for i in items
                if q in i.name.lower()
                or q in i.description.lower()
                or q in i.category.lower()
            ]
        items.sort(key=lambda x: (not x.installed, x.name))
        return [i.to_dict() for i in items]

    def get_skill(self, name: str) -> Optional[Dict[str, Any]]:
        n = self._sanitize_name(name)
        if not n:
            return None
        all_items = self.list_skills(available=True)
        for item in all_items:
            if item.get("name") == n:
                return item
        return None

    def install_skill(self, name: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        n = self._sanitize_name(name)
        if not n:
            return False, "Geçersiz skill adı.", None

        existing = self._manifest_path(n)
        if existing.exists():
            info = self.get_skill(n)
            return True, f"'{n}' zaten yüklü.", info

        catalog = get_builtin_skill_catalog()
        raw = dict(catalog.get(n, {}))
        if not raw:
            raw = {
                "name": n,
                "version": "1.0.0",
                "description": f"{n} becerisi",
                "category": "custom",
                "source": "local",
                "required_tools": [],
                "dependencies": [],
                "commands": [],
            }
        raw["name"] = n
        raw["installed_at"] = _now_iso()
        raw["updated_at"] = raw["installed_at"]
        self._write_manifest(n, raw)

        enabled = self._enabled_set()
        enabled.add(n)
        self._set_enabled_set(enabled)

        info = self.get_skill(n)
        return True, f"'{n}' yüklendi ve etkinleştirildi.", info

    def remove_skill(self, name: str) -> Tuple[bool, str]:
        import shutil

        n = self._sanitize_name(name)
        if not n:
            return False, "Geçersiz skill adı."

        path = self._skill_dir(n)
        if path.exists():
            shutil.rmtree(path)

        enabled = self._enabled_set()
        if n in enabled:
            enabled.remove(n)
            self._set_enabled_set(enabled)
        return True, f"'{n}' kaldırıldı."

    def set_enabled(self, name: str, enabled_flag: bool) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        n = self._sanitize_name(name)
        if not n:
            return False, "Geçersiz skill adı.", None

        manifest = self._manifest_path(n)
        if not manifest.exists():
            ok, msg, info = self.install_skill(n)
            if not ok:
                return False, msg, None
            # install already enables.
            if enabled_flag:
                return True, msg, info

        enabled = self._enabled_set()
        if enabled_flag:
            enabled.add(n)
        else:
            enabled.discard(n)
        self._set_enabled_set(enabled)
        info = self.get_skill(n)
        return True, f"'{n}' {'etkinleştirildi' if enabled_flag else 'devre dışı bırakıldı'}.", info

    def update_skills(self, name: Optional[str] = None, update_all: bool = False) -> Dict[str, Any]:
        if update_all:
            targets = [s["name"] for s in self.list_skills(available=False)]
        else:
            targets = [self._sanitize_name(name)] if name else []
        updated = []
        skipped = []
        for n in targets:
            if not n:
                continue
            manifest_path = self._manifest_path(n)
            raw = self._read_manifest(manifest_path) if manifest_path.exists() else None
            if not raw:
                skipped.append(n)
                continue
            raw["updated_at"] = _now_iso()
            self._write_manifest(n, raw)
            updated.append(n)
        return {"updated": updated, "skipped": skipped}

    def search(self, query: str) -> List[Dict[str, Any]]:
        return self.list_skills(available=True, query=query or "")

    def check(self, name: Optional[str] = None) -> Dict[str, Any]:
        targets = self.list_skills(available=False)
        if name:
            n = self._sanitize_name(name)
            targets = [s for s in targets if s.get("name") == n]

        checks = []
        for s in targets:
            missing_tools = s.get("missing_tools", []) or []
            missing_deps = s.get("missing_dependencies", []) or []
            checks.append({
                "name": s.get("name"),
                "installed": bool(s.get("installed")),
                "enabled": bool(s.get("enabled")),
                "health_ok": len(missing_tools) == 0 and len(missing_deps) == 0,
                "runtime_ready": bool(s.get("runtime_ready", False)),
                "missing_tools": missing_tools,
                "missing_dependencies": missing_deps,
                "blocked_tools": s.get("blocked_tools", []) or [],
            })
        ok = all(c["health_ok"] for c in checks) if checks else True
        return {"ok": ok, "checks": checks}

    def list_workflows(self, *, enabled_only: bool = False, query: str = "") -> List[Dict[str, Any]]:
        workflows = get_builtin_workflow_catalog()
        enabled = self._enabled_workflow_set()
        out: List[Dict[str, Any]] = []
        available_tools = self._available_tools_set()
        enabled_skills = {str(s.get("name", "")).strip() for s in self.list_skills(available=False, enabled_only=True)}

        for wid, raw in workflows.items():
            wf_id = self._sanitize_name(str(raw.get("id") or wid))
            req_tools = [str(t).strip() for t in raw.get("required_tools", []) if str(t).strip()]
            req_skills = [self._sanitize_name(str(s)) for s in raw.get("required_skills", []) if str(s).strip()]
            missing_tools = sorted([t for t in req_tools if t not in available_tools])
            missing_skills = sorted([s for s in req_skills if s and s not in enabled_skills])
            is_enabled = wf_id in enabled
            runtime_ready = len(missing_tools) == 0

            item = {
                "id": wf_id,
                "name": str(raw.get("name") or wf_id),
                "version": str(raw.get("version") or "1.0.0"),
                "description": str(raw.get("description") or ""),
                "category": str(raw.get("category") or "general"),
                "source": str(raw.get("source") or "builtin"),
                "enabled": is_enabled,
                "executable": bool(raw.get("executable", False)),
                "auto_intent": bool(raw.get("auto_intent", False)),
                "required_tools": req_tools,
                "required_skills": req_skills,
                "missing_tools": missing_tools,
                "missing_skills": missing_skills,
                "runtime_ready": runtime_ready,
                "steps": list(raw.get("steps", []) or []),
                "trigger_markers": list(raw.get("trigger_markers", []) or []),
            }
            out.append(item)

        if enabled_only:
            out = [x for x in out if x.get("enabled")]
        if query:
            q = str(query or "").strip().lower()
            out = [
                x for x in out
                if q in str(x.get("id", "")).lower()
                or q in str(x.get("name", "")).lower()
                or q in str(x.get("description", "")).lower()
                or q in str(x.get("category", "")).lower()
            ]
        out.sort(key=lambda x: (not x.get("enabled", False), x.get("id", "")))
        return out

    def set_workflow_enabled(self, workflow_id: str, enabled_flag: bool) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        wid = self._sanitize_name(workflow_id)
        catalog = get_builtin_workflow_catalog()
        if not wid or wid not in {self._sanitize_name(k) for k in catalog.keys()}:
            return False, "Geçersiz workflow id.", None

        enabled = self._enabled_workflow_set()
        if enabled_flag:
            enabled.add(wid)
        else:
            enabled.discard(wid)
        self._set_enabled_workflow_set(enabled)

        info = None
        for item in self.list_workflows():
            if item.get("id") == wid:
                info = item
                break
        return True, f"'{wid}' {'etkinleştirildi' if enabled_flag else 'devre dışı bırakıldı'}.", info

    @staticmethod
    def _extract_first_url(text: str) -> str:
        m = re.search(r"(https?://\S+)", str(text or ""))
        if not m:
            return ""
        return str(m.group(1) or "").strip(" \t\r\n\"'`),.;:!?")

    @staticmethod
    def _is_image_path(path: str) -> bool:
        try:
            return Path(str(path or "")).expanduser().suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        except Exception:
            return False

    @staticmethod
    def _extract_output_paths(text: str) -> tuple[str, str]:
        raw = str(text or "")
        path_hits = re.findall(r"((?:~|/)[^\s,]+)", raw)
        result_path = ""
        summary_path = ""
        for hit in path_hits:
            p = str(hit).strip(" \t\r\n\"'`),.;:!?")
            low = p.lower()
            if low.endswith(".json") and not result_path:
                result_path = p
            if low.endswith((".md", ".txt")) and not summary_path:
                summary_path = p
        if not result_path:
            result_path = str(Path.home() / "Desktop" / "elyan-test" / "api" / "result.json")
        if not summary_path:
            summary_path = default_summary_path(result_path)
        return result_path, summary_path

    def resolve_workflow_intent(
        self,
        user_input: str,
        *,
        attachments: Optional[List[str]] = None,
        file_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        text = str(user_input or "").strip()
        low = text.lower()
        if not text:
            return None

        enabled_workflows = {w.get("id") for w in self.list_workflows(enabled_only=True)}
        if not enabled_workflows:
            return None

        # Workflow: wallpaper_with_proof
        if "wallpaper_with_proof" in enabled_workflows:
            if any(k in low for k in ("duvar kağıdı", "duvar kagidi", "wallpaper", "arka plan")):
                image_path = ""
                for a in list(attachments or []):
                    if self._is_image_path(a):
                        image_path = str(Path(str(a)).expanduser())
                        break
                if not image_path and isinstance(file_context, dict):
                    last_attachment = str(file_context.get("last_attachment") or "").strip()
                    if self._is_image_path(last_attachment):
                        image_path = last_attachment
                params: Dict[str, Any] = {"search_query": "dog wallpaper" if "köpek" in low or "kopek" in low else "wallpaper"}
                if image_path:
                    params["image_path"] = image_path
                return {
                    "action": "set_wallpaper",
                    "params": params,
                    "reply": "Workflow: Wallpaper + Proof çalıştırılıyor...",
                    "_workflow_id": "wallpaper_with_proof",
                }

        # Workflow: api_health_get_save
        if "api_health_get_save" in enabled_workflows:
            api_url = self._extract_first_url(text)
            health_markers = ("health check", "healthcheck", "sağlık kontrol", "saglik kontrol", "api check")
            save_markers = DEFAULT_SAVE_MARKERS
            wants_health = any(k in low for k in health_markers)
            wants_save = any(k in low for k in save_markers)
            if api_url and wants_health and wants_save:
                result_path, summary_path = self._extract_output_paths(text)
                return {
                    "action": "api_health_get_save",
                    "params": {
                        "url": api_url,
                        "method": "GET",
                        "result_path": result_path,
                        "summary_path": summary_path,
                    },
                    "reply": "Workflow: API Health + GET + Save çalıştırılıyor...",
                    "_workflow_id": "api_health_get_save",
                }

        return None

    # Async compatibility wrappers
    async def load_all(self):
        return True

    async def execute(self, skill_name: str, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compatibility stub for old skill execution API.
        Runtime skills execute through normal tool flow in this version.
        """
        info = self.get_skill(skill_name)
        if not info:
            return {"success": False, "error": f"Skill not found: {skill_name}"}
        if not info.get("enabled"):
            return {"success": False, "error": f"Skill disabled: {skill_name}"}
        if tool_name and tool_name in AVAILABLE_TOOLS:
            try:
                tool = AVAILABLE_TOOLS.get(tool_name)
                if tool is None:
                    return {"success": False, "error": f"Tool not found: {tool_name}"}
                if callable(tool):
                    result = await TaskExecutor().execute(tool, params or {})
                    return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "Skill execute API deprecated; use tool execution pipeline."}


skill_manager = SkillManager()
