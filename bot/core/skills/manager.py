from __future__ import annotations

import json
import inspect
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.elyan_config import elyan_config
from core.skills.catalog import get_builtin_skill_catalog
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

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["missing_tools"] = data.get("missing_tools") or []
        data["missing_dependencies"] = data.get("missing_dependencies") or []
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
                "missing_tools": missing_tools,
                "missing_dependencies": missing_deps,
            })
        ok = all(c["health_ok"] for c in checks) if checks else True
        return {"ok": ok, "checks": checks}

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
                    if inspect.iscoroutinefunction(tool):
                        result = await tool(**(params or {}))
                    else:
                        result = tool(**(params or {}))
                    return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "Skill execute API deprecated; use tool execution pipeline."}


skill_manager = SkillManager()
