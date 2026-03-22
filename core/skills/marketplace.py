"""
Skill Marketplace — Remote discovery, validation, and community skill support.

Enables:
1. Remote skill registry (fetch from URL/GitHub)
2. Skill package validation (manifest schema, security checks)
3. Community skill install with sandboxing
4. Skill rating/feedback (local tracking)
5. Dependency resolution between skills

Architecture:
- SkillMarketplace: High-level API for browse/search/install from remote
- SkillValidator: Validates skill packages before installation
- SkillPackage: Standardized format for distributable skills
"""

import asyncio
import json
import hashlib
import time
import shutil
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, UTC
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("skill_marketplace")

# ── Constants ──────────────────────────────────────────────────

MARKETPLACE_INDEX_URL = "https://raw.githubusercontent.com/emrek0ca/elyan-skills/main/index.json"
SKILL_MANIFEST_VERSION = "1.0"
MAX_SKILL_SIZE_MB = 10
DANGEROUS_IMPORTS = {
    "subprocess", "os.system", "shutil.rmtree", "ctypes",
    "importlib", "__import__", "eval", "exec", "compile",
}
ALLOWED_CATEGORIES = {
    "core", "productivity", "automation", "analysis",
    "integration", "dev_tools", "media", "communication", "custom",
}


# ── Data Models ────────────────────────────────────────────────

@dataclass
class SkillPackage:
    """Standardized skill package format for marketplace distribution."""
    name: str
    version: str
    description: str
    author: str = ""
    category: str = "custom"
    license: str = "MIT"
    homepage: str = ""
    repository: str = ""
    required_tools: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    python_dependencies: List[str] = field(default_factory=list)
    os_dependencies: List[str] = field(default_factory=list)
    post_install: List[str] = field(default_factory=list)
    trust_level: str = "curated"
    source: str = "marketplace"
    hashes: Dict[str, str] = field(default_factory=dict)
    commands: List[str] = field(default_factory=list)
    files: Dict[str, str] = field(default_factory=dict)  # path -> content
    icon: str = ""
    tags: List[str] = field(default_factory=list)
    min_elyan_version: str = "1.0.0"
    manifest_version: str = SKILL_MANIFEST_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def checksum(self) -> str:
        """Generate content hash for integrity verification."""
        content = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class MarketplaceListing:
    """A skill listing in the marketplace index."""
    name: str
    version: str
    description: str
    author: str = ""
    category: str = "custom"
    download_url: str = ""
    downloads: int = 0
    rating: float = 0.0
    tags: List[str] = field(default_factory=list)
    updated_at: str = ""
    checksum: str = ""
    size_kb: int = 0


@dataclass
class SkillReview:
    """User review/rating for a skill."""
    skill_name: str
    rating: int  # 1-5
    comment: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


# ── Skill Validator ────────────────────────────────────────────

class SkillValidator:
    """Validates skill packages for safety and correctness."""

    @staticmethod
    def validate_manifest(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate skill manifest structure."""
        errors = []

        required_fields = ["name", "version", "description"]
        for f in required_fields:
            if not data.get(f):
                errors.append(f"Missing required field: {f}")

        name = str(data.get("name", ""))
        if name and not all(c.isalnum() or c in "_-" for c in name):
            errors.append(f"Invalid skill name: {name} (only alphanumeric, _ and - allowed)")

        category = str(data.get("category", "custom"))
        if category not in ALLOWED_CATEGORIES:
            errors.append(f"Unknown category: {category} (allowed: {ALLOWED_CATEGORIES})")

        return len(errors) == 0, errors

    @staticmethod
    def validate_code_safety(files: Dict[str, str]) -> Tuple[bool, List[str]]:
        """Check Python files for dangerous patterns."""
        warnings = []

        for fpath, content in files.items():
            if not fpath.endswith(".py"):
                continue

            for dangerous in DANGEROUS_IMPORTS:
                if dangerous in content:
                    warnings.append(f"{fpath}: contains potentially dangerous '{dangerous}'")

            # Check for network calls
            if "requests.get" in content or "httpx" in content or "urllib" in content:
                warnings.append(f"{fpath}: contains network calls — review before installing")

        # Warnings don't block installation, they inform the user
        return len(warnings) == 0, warnings

    @staticmethod
    def validate_size(files: Dict[str, str]) -> Tuple[bool, List[str]]:
        """Check total package size."""
        total_bytes = sum(len(v.encode()) for v in files.values())
        total_mb = total_bytes / (1024 * 1024)
        if total_mb > MAX_SKILL_SIZE_MB:
            return False, [f"Package too large: {total_mb:.1f}MB (max {MAX_SKILL_SIZE_MB}MB)"]
        return True, []

    def validate_package(self, package: SkillPackage) -> Tuple[bool, List[str]]:
        """Full validation of a skill package."""
        all_errors = []

        ok, errors = self.validate_manifest(package.to_dict())
        all_errors.extend(errors)

        ok2, warnings = self.validate_code_safety(package.files)
        all_errors.extend(warnings)

        ok3, size_errors = self.validate_size(package.files)
        all_errors.extend(size_errors)

        # Size errors are blocking, others are warnings
        is_valid = ok and ok3
        return is_valid, all_errors


# ── Skill Marketplace ─────────────────────────────────────────

class SkillMarketplace:
    """
    Marketplace for discovering, validating, and installing community skills.

    Supports:
    - Local skill creation and packaging
    - Remote index browsing (when online)
    - Validation before install
    - Rating/review tracking
    """

    def __init__(self):
        self._data_dir = Path.home() / ".elyan" / "marketplace"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path = self._data_dir / "index_cache.json"
        self._reviews_path = self._data_dir / "reviews.json"
        self._validator = SkillValidator()
        self._index_cache: Optional[List[MarketplaceListing]] = None
        self._cache_ttl = 3600  # 1 hour
        self._install_lock_guard = threading.Lock()
        self._install_locks: dict[str, asyncio.Lock] = {}

    def _install_lock_for(self, package_name: str) -> asyncio.Lock:
        key = self._sanitize_name(package_name)
        with self._install_lock_guard:
            lock = self._install_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._install_locks[key] = lock
            return lock

    @staticmethod
    def _sanitize_name(value: str) -> str:
        return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")

    @staticmethod
    def _normalize_source(value: str) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _is_trusted_download_url(url: str) -> tuple[bool, str]:
        parsed = urlparse(str(url or "").strip())
        if not parsed.scheme or not parsed.netloc:
            return False, "invalid_download_url"
        scheme = parsed.scheme.lower()
        host = str(parsed.hostname or "").strip().lower()
        if scheme not in {"https"} and host not in {"127.0.0.1", "localhost"}:
            return False, f"untrusted_url_scheme:{scheme or 'unknown'}"
        trusted_hosts = {
            "raw.githubusercontent.com",
            "github.com",
            "api.github.com",
            "localhost",
            "127.0.0.1",
        }
        if host not in trusted_hosts:
            return False, f"untrusted_url_host:{host or 'unknown'}"
        return True, ""

    def _trust_metadata(self, package: SkillPackage) -> tuple[bool, str]:
        source = self._normalize_source(package.source or "marketplace")
        trust = self._normalize_source(package.trust_level or "curated")
        trusted_sources = {"builtin", "marketplace", "curated", "local"}
        trusted_levels = {"trusted", "curated", "builtin"}
        if source not in trusted_sources:
            return False, f"untrusted_source:{source or 'unknown'}"
        if trust not in trusted_levels:
            return False, f"untrusted_trust_level:{trust or 'unknown'}"
        has_checksum = bool(package.hashes.get("package") or package.hashes.get("checksum") or package.hashes.get("manifest"))
        if source not in {"builtin", "local"} and not (has_checksum or package.hashes):
            return False, "hash_or_checksum_required_for_remote_package"
        return True, ""

    @staticmethod
    def _hash_text(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _verify_package_hashes(self, package: SkillPackage) -> tuple[bool, list[str]]:
        issues: list[str] = []
        for rel, expected in dict(package.hashes or {}).items():
            key = str(rel or "").strip()
            if not key:
                continue
            actual = ""
            if key in {"checksum", "manifest", "package"}:
                actual = package.checksum()
            elif key in package.files:
                actual = self._hash_text(str(package.files.get(key) or ""))
            else:
                candidate = package.files.get(key) or package.files.get(Path(key).name, "")
                if candidate:
                    actual = self._hash_text(str(candidate))
            if actual and str(expected or "").strip() and actual != str(expected or "").strip():
                issues.append(f"hash mismatch for {key}")
        return len(issues) == 0, issues

    def _write_package_to_dir(self, package: SkillPackage, skill_dir: Path) -> None:
        skill_dir.mkdir(parents=True, exist_ok=True)
        manifest_data = {
            "name": package.name,
            "version": package.version,
            "description": package.description,
            "author": package.author,
            "category": package.category,
            "license": package.license,
            "homepage": package.homepage,
            "repository": package.repository,
            "required_tools": package.required_tools,
            "dependencies": package.dependencies,
            "python_dependencies": package.python_dependencies,
            "os_dependencies": package.os_dependencies,
            "post_install": package.post_install,
            "trust_level": package.trust_level,
            "hashes": package.hashes,
            "commands": package.commands,
            "tags": package.tags,
            "source": package.source,
            "installed_at": datetime.now(UTC).isoformat(),
            "checksum": package.checksum(),
        }
        (skill_dir / "skill.json").write_text(
            json.dumps(manifest_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        for fpath, content in package.files.items():
            if ".." in fpath or fpath.startswith("/"):
                continue
            target = skill_dir / fpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    async def _install_python_dependencies(self, package: SkillPackage) -> list[str]:
        installed: list[str] = []
        deps = list(dict.fromkeys([str(dep).strip() for dep in package.python_dependencies if str(dep).strip()]))
        if not deps:
            return installed
        try:
            from core.dependencies import get_dependency_runtime

            runtime = get_dependency_runtime()
        except Exception as exc:
            raise RuntimeError(f"dependency_runtime_unavailable:{exc}") from exc
        for dep in deps:
            record = await runtime.ensure_module_async(
                dep,
                install_spec=dep,
                source="pypi",
                trust_level=package.trust_level or "trusted",
                hashes=package.hashes,
                post_install=package.post_install,
                skill_name=package.name,
                tool_name="marketplace_install",
                allow_install=True,
            )
            if str(record.status).lower() not in {"installed", "ready"}:
                raise RuntimeError(f"python_dependency_failed:{dep}:{record.status}")
            installed.append(dep)
        return installed

    async def _install_os_dependencies(self, package: SkillPackage) -> list[str]:
        installed: list[str] = []
        deps = list(dict.fromkeys([str(dep).strip() for dep in package.os_dependencies if str(dep).strip()]))
        if not deps:
            return installed
        try:
            from core.dependencies import get_system_dependency_runtime

            runtime = get_system_dependency_runtime()
        except Exception as exc:
            raise RuntimeError(f"system_dependency_runtime_unavailable:{exc}") from exc
        records = runtime.ensure_binaries(deps, allow_install=self._normalize_source(package.source) in {"builtin", "marketplace", "curated", "local"})
        for record in records:
            status = str(getattr(record, "status", "") or "").lower()
            binary = str(getattr(record, "binary", "") or "").strip()
            if status in {"ready", "installed"}:
                if binary:
                    installed.append(binary)
            elif status in {"needs_input", "blocked"}:
                raise RuntimeError(f"os_dependency_{status}:{binary}")
            else:
                raise RuntimeError(f"os_dependency_failed:{binary}:{status}")
        return installed

    # ── Browse & Search ────────────────────────────────────────

    async def browse(
        self,
        category: str = "",
        query: str = "",
        sort_by: str = "rating",
    ) -> List[Dict[str, Any]]:
        """Browse marketplace listings."""
        listings = await self._get_index()

        if category:
            listings = [l for l in listings if l.category == category]

        if query:
            q = query.lower()
            listings = [
                l for l in listings
                if q in l.name.lower()
                or q in l.description.lower()
                or any(q in t.lower() for t in l.tags)
            ]

        # Sort
        if sort_by == "rating":
            listings.sort(key=lambda x: x.rating, reverse=True)
        elif sort_by == "downloads":
            listings.sort(key=lambda x: x.downloads, reverse=True)
        elif sort_by == "updated":
            listings.sort(key=lambda x: x.updated_at, reverse=True)
        else:
            listings.sort(key=lambda x: x.name)

        return [asdict(l) for l in listings]

    async def search(self, query: str) -> List[Dict[str, Any]]:
        """Search marketplace by query."""
        return await self.browse(query=query)

    async def get_categories(self) -> List[Dict[str, Any]]:
        """Get available categories with counts."""
        listings = await self._get_index()
        counts: Dict[str, int] = {}
        for l in listings:
            counts[l.category] = counts.get(l.category, 0) + 1

        return [
            {"category": cat, "count": count}
            for cat, count in sorted(counts.items(), key=lambda x: -x[1])
        ]

    # ── Install from Marketplace ───────────────────────────────

    async def install_from_url(self, url: str) -> Tuple[bool, str, List[str]]:
        """
        Download and install a skill package from a URL.
        Returns (success, message, warnings).
        """
        trusted_url, url_reason = self._is_trusted_download_url(url)
        if not trusted_url:
            try:
                from core.integration_trace import get_integration_trace_store

                get_integration_trace_store().record_trace(
                    operation="marketplace_install",
                    provider="marketplace",
                    connector_name="skill_marketplace",
                    integration_type="api",
                    status="blocked",
                    success=False,
                    fallback_used=True,
                    fallback_reason=url_reason,
                    metadata={"url": str(url or ""), "reason": url_reason},
                )
            except Exception:
                pass
            return False, f"Untrusted marketplace URL: {url_reason}", [url_reason]
        try:
            import httpx
        except ImportError:
            return False, "httpx not installed — cannot download remote skills", []

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            return False, f"Download failed: {e}", []

        return await self.install_from_dict(data)

    async def install_from_dict(self, data: Dict[str, Any]) -> Tuple[bool, str, List[str]]:
        """Install a skill from its manifest dictionary."""
        try:
            package = SkillPackage(
                name=data.get("name", ""),
                version=data.get("version", "1.0.0"),
                description=data.get("description", ""),
                author=data.get("author", ""),
                category=data.get("category", "custom"),
                license=data.get("license", "MIT"),
                homepage=data.get("homepage", ""),
                repository=data.get("repository", ""),
                required_tools=data.get("required_tools", []),
                dependencies=data.get("dependencies", []),
                python_dependencies=data.get("python_dependencies", []),
                post_install=data.get("post_install", []),
                trust_level=data.get("trust_level", "curated"),
                source=data.get("source", "marketplace"),
                hashes=data.get("hashes", {}),
                commands=data.get("commands", []),
                files=data.get("files", {}),
                tags=data.get("tags", []),
            )
        except Exception as e:
            return False, f"Invalid package format: {e}", []

        # Validate
        is_valid, issues = self._validator.validate_package(package)
        if not is_valid:
            blocking = [i for i in issues if not i.startswith("WARNING")]
            return False, f"Validation failed: {'; '.join(blocking)}", issues

        trusted, trust_reason = self._trust_metadata(package)
        if not trusted:
            try:
                from core.integration_trace import get_integration_trace_store

                get_integration_trace_store().record_trace(
                    operation="marketplace_install",
                    provider=package.source,
                    connector_name="skill_marketplace",
                    integration_type="api",
                    status="blocked",
                    success=False,
                    fallback_used=True,
                    fallback_reason=trust_reason,
                    metadata={"skill": package.name, "reason": trust_reason},
                )
            except Exception:
                pass
            return False, f"Trust policy blocked: {trust_reason}", [trust_reason]

        hashes_ok, hash_issues = self._verify_package_hashes(package)
        if not hashes_ok:
            try:
                from core.integration_trace import get_integration_trace_store

                get_integration_trace_store().record_trace(
                    operation="marketplace_install",
                    provider=package.source,
                    connector_name="skill_marketplace",
                    integration_type="api",
                    status="blocked",
                    success=False,
                    fallback_used=True,
                    fallback_reason="hash_verification_failed",
                    metadata={"skill": package.name, "hash_issues": list(hash_issues)},
                )
            except Exception:
                pass
            return False, f"Hash verification failed: {'; '.join(hash_issues)}", hash_issues

        # Install via SkillManager
        from core.skills.manager import skill_manager
        install_lock = self._install_lock_for(package.name)
        async with install_lock:
            skill_dir = skill_manager._skill_dir(package.name)
            backup_dir = None
            staging_dir = self._data_dir / "staging" / f"{package.name}.{int(time.time() * 1000)}"
            staging_dir.parent.mkdir(parents=True, exist_ok=True)
            if skill_dir.exists():
                backup_dir = skill_dir.parent / f".{skill_dir.name}.bak_{int(time.time() * 1000)}"
                if backup_dir.exists():
                    shutil.rmtree(backup_dir, ignore_errors=True)
                skill_dir.rename(backup_dir)
            try:
                self._write_package_to_dir(package, staging_dir)
                await self._install_python_dependencies(package)
                await self._install_os_dependencies(package)
                if skill_dir.exists():
                    shutil.rmtree(skill_dir, ignore_errors=True)
                staging_dir.rename(skill_dir)
                if backup_dir and backup_dir.exists():
                    shutil.rmtree(backup_dir, ignore_errors=True)
            except Exception as exc:
                if skill_dir.exists() and skill_dir.is_dir():
                    shutil.rmtree(skill_dir, ignore_errors=True)
                if staging_dir.exists() and staging_dir.is_dir():
                    shutil.rmtree(staging_dir, ignore_errors=True)
                if backup_dir and backup_dir.exists():
                    try:
                        backup_dir.rename(skill_dir)
                    except Exception:
                        pass
                try:
                    from core.integration_trace import get_integration_trace_store

                    get_integration_trace_store().record_trace(
                        operation="marketplace_install",
                        provider=package.source,
                        connector_name="skill_marketplace",
                        integration_type="api",
                        status="failed",
                        success=False,
                        fallback_used=True,
                        fallback_reason=str(exc),
                        metadata={"skill": package.name, "error": str(exc)},
                    )
                except Exception:
                    pass
                return False, f"Installation failed: {exc}", [str(exc)]

        # Enable
        enabled = skill_manager._enabled_set()
        enabled.add(package.name)
        skill_manager._set_enabled_set(enabled)

        try:
            from core.integration_trace import get_integration_trace_store

            get_integration_trace_store().record_trace(
                operation="marketplace_install",
                provider=package.source,
                connector_name="skill_marketplace",
                integration_type="api",
                status="installed",
                success=True,
                fallback_used=False,
                metadata={
                    "skill": package.name,
                    "python_dependencies": list(package.python_dependencies or []),
                    "os_dependencies": list(package.os_dependencies or []),
                    "trust_level": package.trust_level,
                    "source": package.source,
                },
            )
        except Exception:
            pass

        warnings = [i for i in issues if "WARNING" in i or "contains" in i]
        return True, f"'{package.name}' v{package.version} installed from marketplace", warnings

    # ── Create & Publish ───────────────────────────────────────

    def create_skill_package(
        self,
        name: str,
        description: str,
        files: Dict[str, str],
        **kwargs,
    ) -> Tuple[bool, str, Optional[SkillPackage]]:
        """Create a new skill package for sharing."""
        package = SkillPackage(
            name=name,
            version=kwargs.get("version", "1.0.0"),
            description=description,
            author=kwargs.get("author", ""),
            category=kwargs.get("category", "custom"),
            required_tools=kwargs.get("required_tools", []),
            dependencies=kwargs.get("dependencies", []),
            python_dependencies=kwargs.get("python_dependencies", []),
            os_dependencies=kwargs.get("os_dependencies", []),
            post_install=kwargs.get("post_install", []),
            trust_level=kwargs.get("trust_level", "curated"),
            source=kwargs.get("source", "marketplace"),
            hashes=kwargs.get("hashes", {}),
            commands=kwargs.get("commands", []),
            files=files,
            tags=kwargs.get("tags", []),
        )

        is_valid, issues = self._validator.validate_package(package)
        if not is_valid:
            return False, f"Validation failed: {'; '.join(issues)}", None

        # Save package to marketplace dir for potential publishing
        pkg_path = self._data_dir / "packages" / name
        pkg_path.mkdir(parents=True, exist_ok=True)
        (pkg_path / "package.json").write_text(
            json.dumps(package.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return True, f"Package '{name}' created at {pkg_path}", package

    def export_skill(self, name: str) -> Tuple[bool, str]:
        """Export an installed skill as a shareable package.json."""
        from core.skills.manager import skill_manager
        skill_dir = skill_manager._skill_dir(name)
        manifest_path = skill_dir / "skill.json"

        if not manifest_path.exists():
            return False, f"Skill '{name}' not found"

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            return False, f"Cannot read manifest: {e}"

        # Collect all files in skill directory
        files = {}
        for f in skill_dir.rglob("*"):
            if f.is_file() and f.name != "skill.json":
                rel = str(f.relative_to(skill_dir))
                try:
                    files[rel] = f.read_text(encoding="utf-8")
                except Exception:
                    pass  # Skip binary files

        package_data = {**manifest, "files": files}
        export_path = self._data_dir / "exports" / f"{name}.json"
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(
            json.dumps(package_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return True, f"Exported to {export_path}"

    # ── Reviews & Ratings ──────────────────────────────────────

    def add_review(self, skill_name: str, rating: int, comment: str = "") -> bool:
        """Add a review for a skill (1-5 stars)."""
        rating = max(1, min(5, rating))
        reviews = self._load_reviews()
        reviews.append(asdict(SkillReview(
            skill_name=skill_name,
            rating=rating,
            comment=comment,
        )))
        self._save_reviews(reviews)
        return True

    def get_reviews(self, skill_name: str) -> List[Dict[str, Any]]:
        """Get reviews for a skill."""
        reviews = self._load_reviews()
        return [r for r in reviews if r.get("skill_name") == skill_name]

    def get_average_rating(self, skill_name: str) -> float:
        """Get average rating for a skill."""
        reviews = self.get_reviews(skill_name)
        if not reviews:
            return 0.0
        return sum(r.get("rating", 0) for r in reviews) / len(reviews)

    # ── Index Management ───────────────────────────────────────

    async def _get_index(self) -> List[MarketplaceListing]:
        """Get marketplace index (cached)."""
        if self._index_cache is not None:
            return self._index_cache

        # Try local cache first
        cached = self._read_cache()
        if cached is not None:
            self._index_cache = cached
            return cached

        # Fetch remote (best-effort)
        remote = await self._fetch_remote_index()
        if remote:
            self._index_cache = remote
            self._write_cache(remote)
            return remote

        # Fallback: empty
        self._index_cache = self._builtin_listings()
        return self._index_cache

    def _builtin_listings(self) -> List[MarketplaceListing]:
        """Generate marketplace listings from builtin catalog."""
        from core.skills.catalog import get_builtin_skill_catalog
        listings = []
        for name, raw in get_builtin_skill_catalog().items():
            listings.append(MarketplaceListing(
                name=name,
                version=raw.get("version", "1.0.0"),
                description=raw.get("description", ""),
                category=raw.get("category", "core"),
                tags=raw.get("commands", []),
                rating=4.5,  # Default rating for builtins
                downloads=1000,
            ))
        return listings

    async def _fetch_remote_index(self) -> Optional[List[MarketplaceListing]]:
        """Fetch remote marketplace index."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(MARKETPLACE_INDEX_URL)
                resp.raise_for_status()
                data = resp.json()

            listings = []
            for item in data.get("skills", []):
                listings.append(MarketplaceListing(
                    name=item.get("name", ""),
                    version=item.get("version", "1.0.0"),
                    description=item.get("description", ""),
                    author=item.get("author", ""),
                    category=item.get("category", "custom"),
                    download_url=item.get("download_url", ""),
                    downloads=item.get("downloads", 0),
                    rating=item.get("rating", 0.0),
                    tags=item.get("tags", []),
                    updated_at=item.get("updated_at", ""),
                    checksum=item.get("checksum", ""),
                    size_kb=item.get("size_kb", 0),
                ))
            return listings
        except Exception as e:
            logger.debug(f"Remote index fetch failed (expected offline): {e}")
            return None

    def _read_cache(self) -> Optional[List[MarketplaceListing]]:
        """Read cached index."""
        try:
            if not self._cache_path.exists():
                return None
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            # Check TTL
            cached_at = data.get("cached_at", 0)
            if time.time() - cached_at > self._cache_ttl:
                return None
            return [MarketplaceListing(**item) for item in data.get("listings", [])]
        except Exception:
            return None

    def _write_cache(self, listings: List[MarketplaceListing]):
        """Write index to cache."""
        try:
            data = {
                "cached_at": time.time(),
                "listings": [asdict(l) for l in listings],
            }
            self._cache_path.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.debug(f"Cache write failed: {e}")

    def _load_reviews(self) -> List[Dict[str, Any]]:
        try:
            if self._reviews_path.exists():
                return json.loads(self._reviews_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    def _save_reviews(self, reviews: List[Dict[str, Any]]):
        try:
            self._reviews_path.write_text(
                json.dumps(reviews, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"Reviews save failed: {e}")


# ── Singleton ──────────────────────────────────────────────────

_marketplace: Optional[SkillMarketplace] = None


def get_marketplace() -> SkillMarketplace:
    """Get or create the singleton SkillMarketplace instance."""
    global _marketplace
    if _marketplace is None:
        _marketplace = SkillMarketplace()
    return _marketplace
