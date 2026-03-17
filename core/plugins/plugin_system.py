"""
ELYAN Plugin System - Phase 8
Plugin registry, SDK, lifecycle management, security scanning.
"""

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set


class PluginStatus(Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    SUSPENDED = "suspended"


class PluginCategory(Enum):
    INTEGRATION = "integration"
    TOOL = "tool"
    MODEL = "model"
    WORKFLOW = "workflow"
    ANALYTICS = "analytics"
    SECURITY = "security"
    UI = "ui"
    LANGUAGE = "language"


class HookPoint(Enum):
    PRE_REQUEST = "pre_request"
    POST_REQUEST = "post_request"
    PRE_EXECUTE = "pre_execute"
    POST_EXECUTE = "post_execute"
    ON_ERROR = "on_error"
    ON_RESULT = "on_result"
    ON_LEARNING = "on_learning"
    ON_STARTUP = "on_startup"
    ON_SHUTDOWN = "on_shutdown"


@dataclass
class PluginManifest:
    name: str
    version: str
    description: str
    author: str
    category: PluginCategory
    entry_point: str
    hooks: List[HookPoint] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    min_elyan_version: str = "1.0.0"
    homepage: str = ""
    license: str = "MIT"
    tags: List[str] = field(default_factory=list)


@dataclass
class Plugin:
    plugin_id: str
    manifest: PluginManifest
    status: PluginStatus = PluginStatus.DRAFT
    install_count: int = 0
    rating: float = 0.0
    rating_count: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    checksum: str = ""
    is_verified: bool = False
    security_score: float = 0.0

    @property
    def avg_rating(self) -> float:
        return self.rating / max(1, self.rating_count)


@dataclass
class InstalledPlugin:
    plugin_id: str
    user_id: str
    version: str
    enabled: bool = True
    installed_at: float = 0.0
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityScanResult:
    plugin_id: str
    score: float
    issues: List[Dict[str, str]]
    scanned_at: float
    passed: bool


class PluginSecurityScanner:
    """Scan plugins for security issues before installation."""

    DANGEROUS_PATTERNS = [
        "eval(", "exec(", "__import__", "subprocess",
        "os.system", "os.popen", "shutil.rmtree",
        "open('/etc", "open('/sys", "open('C:\\\\",
    ]

    SUSPICIOUS_PERMISSIONS = [
        "file_system_write", "network_unrestricted",
        "system_execute", "credential_access",
    ]

    def scan(self, plugin: Plugin) -> SecurityScanResult:
        issues = []
        score = 1.0
        for perm in plugin.manifest.permissions:
            if perm in self.SUSPICIOUS_PERMISSIONS:
                issues.append({
                    "severity": "warning",
                    "type": "permission",
                    "detail": f"Suspicious permission requested: {perm}",
                })
                score -= 0.1
        if not plugin.manifest.author:
            issues.append({
                "severity": "info",
                "type": "metadata",
                "detail": "Missing author information",
            })
            score -= 0.05
        if not plugin.manifest.license:
            issues.append({
                "severity": "info",
                "type": "metadata",
                "detail": "Missing license information",
            })
            score -= 0.05
        if not plugin.is_verified:
            issues.append({
                "severity": "info",
                "type": "verification",
                "detail": "Plugin is not verified by ELYAN team",
            })
            score -= 0.1
        score = max(0.0, min(1.0, score))
        return SecurityScanResult(
            plugin_id=plugin.plugin_id,
            score=score,
            issues=issues,
            scanned_at=time.time(),
            passed=score >= 0.5,
        )


class PluginRegistry:
    """Central registry for discovering and managing plugins."""

    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._by_category: Dict[PluginCategory, List[str]] = {}
        self._by_tag: Dict[str, List[str]] = {}
        self.scanner = PluginSecurityScanner()

    def register(self, manifest: PluginManifest) -> Plugin:
        plugin_id = f"plg_{uuid.uuid4().hex[:8]}"
        checksum = hashlib.sha256(
            f"{manifest.name}:{manifest.version}:{manifest.author}".encode()
        ).hexdigest()[:16]
        plugin = Plugin(
            plugin_id=plugin_id,
            manifest=manifest,
            status=PluginStatus.DRAFT,
            created_at=time.time(),
            updated_at=time.time(),
            checksum=checksum,
        )
        scan_result = self.scanner.scan(plugin)
        plugin.security_score = scan_result.score
        self._plugins[plugin_id] = plugin
        cat = manifest.category
        self._by_category.setdefault(cat, []).append(plugin_id)
        for tag in manifest.tags:
            self._by_tag.setdefault(tag.lower(), []).append(plugin_id)
        return plugin

    def publish(self, plugin_id: str) -> bool:
        plugin = self._plugins.get(plugin_id)
        if plugin and plugin.security_score >= 0.5:
            plugin.status = PluginStatus.PUBLISHED
            plugin.updated_at = time.time()
            return True
        return False

    def deprecate(self, plugin_id: str) -> bool:
        plugin = self._plugins.get(plugin_id)
        if plugin:
            plugin.status = PluginStatus.DEPRECATED
            return True
        return False

    def get(self, plugin_id: str) -> Optional[Plugin]:
        return self._plugins.get(plugin_id)

    def search(
        self,
        query: str = "",
        category: Optional[PluginCategory] = None,
        tag: Optional[str] = None,
        limit: int = 20,
    ) -> List[Plugin]:
        results = list(self._plugins.values())
        results = [p for p in results if p.status == PluginStatus.PUBLISHED]
        if category:
            cat_ids = set(self._by_category.get(category, []))
            results = [p for p in results if p.plugin_id in cat_ids]
        if tag:
            tag_ids = set(self._by_tag.get(tag.lower(), []))
            results = [p for p in results if p.plugin_id in tag_ids]
        if query:
            q = query.lower()
            results = [
                p for p in results
                if q in p.manifest.name.lower() or q in p.manifest.description.lower()
            ]
        results.sort(key=lambda p: p.install_count, reverse=True)
        return results[:limit]

    def get_popular(self, limit: int = 10) -> List[Plugin]:
        published = [p for p in self._plugins.values() if p.status == PluginStatus.PUBLISHED]
        published.sort(key=lambda p: p.install_count, reverse=True)
        return published[:limit]

    def get_stats(self) -> Dict[str, Any]:
        all_plugins = list(self._plugins.values())
        return {
            "total_plugins": len(all_plugins),
            "published": sum(1 for p in all_plugins if p.status == PluginStatus.PUBLISHED),
            "by_category": {
                cat.value: len(ids) for cat, ids in self._by_category.items()
            },
            "total_installs": sum(p.install_count for p in all_plugins),
        }


class PluginManager:
    """Manage plugin installations per user."""

    def __init__(self, registry: Optional[PluginRegistry] = None):
        self.registry = registry or PluginRegistry()
        self._installed: Dict[str, Dict[str, InstalledPlugin]] = {}
        self._hooks: Dict[HookPoint, List[Callable]] = {}

    def install(self, user_id: str, plugin_id: str, config: Optional[Dict] = None) -> Optional[InstalledPlugin]:
        plugin = self.registry.get(plugin_id)
        if not plugin or plugin.status != PluginStatus.PUBLISHED:
            return None
        scan = self.registry.scanner.scan(plugin)
        if not scan.passed:
            return None
        installed = InstalledPlugin(
            plugin_id=plugin_id,
            user_id=user_id,
            version=plugin.manifest.version,
            installed_at=time.time(),
            config=config or {},
        )
        self._installed.setdefault(user_id, {})[plugin_id] = installed
        plugin.install_count += 1
        return installed

    def uninstall(self, user_id: str, plugin_id: str) -> bool:
        user_plugins = self._installed.get(user_id, {})
        if plugin_id in user_plugins:
            del user_plugins[plugin_id]
            return True
        return False

    def enable(self, user_id: str, plugin_id: str) -> bool:
        installed = self._installed.get(user_id, {}).get(plugin_id)
        if installed:
            installed.enabled = True
            return True
        return False

    def disable(self, user_id: str, plugin_id: str) -> bool:
        installed = self._installed.get(user_id, {}).get(plugin_id)
        if installed:
            installed.enabled = False
            return True
        return False

    def get_installed(self, user_id: str) -> List[InstalledPlugin]:
        return list(self._installed.get(user_id, {}).values())

    def get_enabled(self, user_id: str) -> List[InstalledPlugin]:
        return [p for p in self.get_installed(user_id) if p.enabled]

    def configure(self, user_id: str, plugin_id: str, config: Dict[str, Any]) -> bool:
        installed = self._installed.get(user_id, {}).get(plugin_id)
        if installed:
            installed.config.update(config)
            return True
        return False


class RBACManager:
    """Role-Based Access Control for ELYAN."""

    BUILT_IN_ROLES = {
        "owner": {"read", "write", "execute", "admin", "billing", "manage_users", "manage_plugins", "manage_models", "audit", "delete"},
        "admin": {"read", "write", "execute", "admin", "billing", "manage_users", "manage_plugins", "audit"},
        "developer": {"read", "write", "execute", "manage_plugins"},
        "analyst": {"read", "execute"},
        "viewer": {"read"},
        "billing_admin": {"read", "billing"},
    }

    def __init__(self):
        self._user_roles: Dict[str, Set[str]] = {}
        self._custom_roles: Dict[str, Set[str]] = {}
        self._all_roles = dict(self.BUILT_IN_ROLES)

    def assign_role(self, user_id: str, role: str) -> bool:
        if role not in self._all_roles:
            return False
        self._user_roles.setdefault(user_id, set()).add(role)
        return True

    def revoke_role(self, user_id: str, role: str) -> bool:
        roles = self._user_roles.get(user_id, set())
        if role in roles:
            roles.discard(role)
            return True
        return False

    def create_custom_role(self, name: str, permissions: Set[str]) -> bool:
        if name in self.BUILT_IN_ROLES:
            return False
        self._custom_roles[name] = permissions
        self._all_roles[name] = permissions
        return True

    def get_permissions(self, user_id: str) -> Set[str]:
        roles = self._user_roles.get(user_id, set())
        permissions: Set[str] = set()
        for role in roles:
            permissions.update(self._all_roles.get(role, set()))
        return permissions

    def check_permission(self, user_id: str, permission: str) -> bool:
        return permission in self.get_permissions(user_id)

    def get_user_roles(self, user_id: str) -> Set[str]:
        return self._user_roles.get(user_id, set())

    def list_roles(self) -> Dict[str, Set[str]]:
        return dict(self._all_roles)


_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager
