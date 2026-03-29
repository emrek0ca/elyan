from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple

from core.contracts.operator_runtime import ProjectArtifact, ProjectBrief


def _stable_id(prefix: str, seed: str) -> str:
    digest = hashlib.sha1(str(seed or prefix).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return path.name


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _sanitize_project_slug(name: str) -> str:
    raw = str(name or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9\-_ ]+", " ", raw)
    cleaned = re.sub(r"\s+", "-", cleaned).strip("-_ ")
    return cleaned[:80] or "elyan-project"


def _skip_workspace_rel(rel: str) -> bool:
    value = str(rel or "").replace("\\", "/").strip()
    if not value:
        return True
    if value.startswith(".git/") or value.startswith(".venv/") or value.startswith("node_modules/"):
        return True
    return "/." in value


def _iter_workspace_files(root: Path, limit: int = 1200) -> tuple[list[str], int]:
    if not root.exists() or not root.is_dir():
        return [], 0
    files: list[str] = []
    file_count = 0
    for current_root, dirnames, filenames in os.walk(root):
        current_path = Path(current_root)
        kept_dirs: list[str] = []
        for dirname in list(dirnames):
            rel_dir = _safe_rel((current_path / dirname), root)
            if _skip_workspace_rel(rel_dir):
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in sorted(filenames):
            rel = _safe_rel((current_path / filename), root)
            if _skip_workspace_rel(rel):
                continue
            file_count += 1
            if len(files) < limit:
                files.append(rel)
    return sorted(files), file_count


def _infer_package_manager(root: Path, files: list[str]) -> str:
    lower = {item.lower() for item in files}
    if "pnpm-lock.yaml" in lower:
        return "pnpm"
    if "yarn.lock" in lower:
        return "yarn"
    if "package-lock.json" in lower:
        return "npm"
    if "poetry.lock" in lower:
        return "poetry"
    if "pipfile.lock" in lower:
        return "pipenv"
    if "cargo.lock" in lower:
        return "cargo"
    if "go.mod" in lower:
        return "go"
    if "pom.xml" in lower:
        return "maven"
    if "build.gradle" in lower or "build.gradle.kts" in lower:
        return "gradle"
    if "composer.lock" in lower or "composer.json" in lower:
        return "composer"
    if any(item.endswith(".csproj") for item in lower):
        return "dotnet"
    if "package.json" in lower:
        return "npm"
    if "pyproject.toml" in lower or "requirements.txt" in lower:
        return "pip"
    return "none"


def _parse_package_scripts(root: Path) -> dict[str, str]:
    package_json = root / "package.json"
    payload = _read_json(package_json)
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in scripts.items():
        if isinstance(value, str) and value.strip():
            out[str(key).strip()] = value.strip()
    return out


def _detect_html_refs(root: Path, html_path: Path) -> list[tuple[str, str]]:
    try:
        content = html_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    refs: list[tuple[str, str]] = []
    for attr in ("src", "href"):
        for match in re.finditer(rf'{attr}\s*=\s*["\']([^"\']+)["\']', content, re.IGNORECASE):
            ref = str(match.group(1) or "").strip()
            if not ref or ref.startswith(("http://", "https://", "//", "#", "data:", "mailto:")):
                continue
            candidate = (html_path.parent / ref).resolve()
            refs.append((ref, "present" if candidate.exists() else "missing"))
    return refs


def _detect_multi_skeleton(files: list[str]) -> bool:
    lowered = {item.lower() for item in files}
    root_js = any(item in lowered for item in {"script.js", "main.js", "app.js"})
    nested_js = any(item.startswith("scripts/") and item.endswith(".js") for item in lowered)
    root_css = "styles.css" in lowered
    nested_css = any(item.startswith("styles/") and item.endswith(".css") for item in lowered)
    html_index = "index.html" in lowered
    app_roots = any(item.startswith(("src/", "app/", "pages/")) for item in lowered)
    return bool((root_js and nested_js) or (root_css and nested_css) or (html_index and app_roots))


def _infer_available_gates(repo_type: str, scripts: dict[str, str], files: list[str]) -> list[str]:
    gates: list[str] = []
    if "lint" in scripts:
        gates.append("lint")
    if "typecheck" in scripts:
        gates.append("typecheck")
    if "test" in scripts:
        gates.append("test")
    if "build" in scripts:
        gates.append("build")
    if repo_type == "vanilla_web":
        gates.extend(["smoke", "dom_contract", "style"])
    lowered = {item.lower() for item in files}
    if repo_type == "python":
        has_pyproject = "pyproject.toml" in lowered or "setup.cfg" in lowered or "tox.ini" in lowered
        has_tests = any(item.startswith("tests/") or item.endswith("_test.py") or item.startswith("test_") for item in lowered)
        if has_pyproject:
            gates.extend(["format", "lint"])
        if has_tests:
            gates.append("test")
    if repo_type == "go" and "go.mod" in lowered:
        gates.extend(["fmt", "test"])
    if repo_type == "rust" and "cargo.toml" in lowered:
        gates.extend(["fmt", "clippy", "test"])
    if repo_type == "dotnet":
        gates.extend(["build", "test"])
    if repo_type == "java":
        gates.extend(["build", "test"])
    if repo_type == "php":
        gates.extend(["lint", "test"])
    return _dedupe_keep_order(gates)


@dataclass
class FailureEnvelope:
    code: str
    reason: str
    details: list[str] = field(default_factory=list)
    retryable: bool = False
    guidance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationGateResult:
    gate: str
    ok: bool
    command: str = ""
    evidence: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StyleIntent:
    visual_direction: str = ""
    design_tokens: dict[str, Any] = field(default_factory=dict)
    layout_rules: list[str] = field(default_factory=list)
    interaction_rules: list[str] = field(default_factory=list)
    forbidden_patterns: list[str] = field(default_factory=list)
    acceptance_screens: list[str] = field(default_factory=list)
    code_style: str = "clean_code"
    user_tone: str = "pragmatic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StyleLockSpec:
    visual_direction: str = ""
    design_tokens: dict[str, Any] = field(default_factory=dict)
    layout_rules: list[str] = field(default_factory=list)
    interaction_rules: list[str] = field(default_factory=list)
    forbidden_patterns: list[str] = field(default_factory=list)
    canonical_file_set: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WriteScopePolicy:
    allowed_roots: list[str] = field(default_factory=list)
    forbidden_roots: list[str] = field(default_factory=list)
    canonical_file_set: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepoSnapshot:
    snapshot_id: str
    root_path: str
    repo_type: str
    language: str
    framework: str
    package_manager: str
    stack_family: str = ""
    entrypoints: list[str] = field(default_factory=list)
    test_runner: str = ""
    formatter: str = ""
    linter: str = ""
    build_system: str = ""
    workspace_roots: list[str] = field(default_factory=list)
    available_gates: list[str] = field(default_factory=list)
    commands: dict[str, str] = field(default_factory=dict)
    available_commands: dict[str, str] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    existing_files: list[str] = field(default_factory=list)
    is_greenfield: bool = False
    supported: bool = True
    adapter_hint: str = ""
    fingerprint: str = ""
    cache_hit: bool = False
    file_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LanguageAdapter:
    adapter_id: str
    repo_types: list[str]
    language: str
    framework: str
    default_gates: list[str] = field(default_factory=list)
    supported_gates: list[str] = field(default_factory=list)
    claim_policy: dict[str, Any] = field(default_factory=dict)
    canonical_roots: list[str] = field(default_factory=list)
    canonical_file_set: list[str] = field(default_factory=list)
    greenfield_supported: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdapterRunner:
    adapter_id: str
    repo_type: str
    root_path: str
    gate_commands: dict[str, str] = field(default_factory=dict)
    supported_gates: list[str] = field(default_factory=list)
    canonical_file_set: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CodingContract:
    contract_id: str
    execution_mode: str
    repo_snapshot_id: str
    adapter_id: str
    repo_type: str
    supported: bool
    required_gates: list[str] = field(default_factory=list)
    evidence_requirements: list[str] = field(default_factory=list)
    allowed_write_paths: list[str] = field(default_factory=list)
    forbidden_write_paths: list[str] = field(default_factory=list)
    execution_adapter: str = ""
    write_scope: dict[str, Any] = field(default_factory=dict)
    claim_policy: dict[str, Any] = field(default_factory=dict)
    style_intent: dict[str, Any] = field(default_factory=dict)
    style_lock: dict[str, Any] = field(default_factory=dict)
    repair_budget: int = 2
    model_ladder_trace: list[str] = field(default_factory=list)
    failure_envelope: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionEvidence:
    root_path: str = ""
    commands_run: list[str] = field(default_factory=list)
    gate_results: list[dict[str, Any]] = field(default_factory=list)
    artifact_paths: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    diff_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceBundle:
    bundle_id: str
    artifact_paths: list[str] = field(default_factory=list)
    gate_results: list[dict[str, Any]] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    diff_summary: str = ""
    claims_blocked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SNAPSHOT_CACHE_MAX = 24
_SNAPSHOT_CACHE_DIR = Path.home() / ".elyan" / "runtime_cache" / "repo_snapshots"
_SNAPSHOT_MEMORY_CACHE: "OrderedDict[str, RepoSnapshot]" = OrderedDict()
_WRITE_SHELL_MARKERS = (" > ", ">>", " tee ", "touch ", "mkdir ", "cp ", "mv ", "rm ", "sed -i", "perl -pi")


def _snapshot_from_payload(payload: dict[str, Any], *, cache_hit: bool) -> RepoSnapshot | None:
    if not isinstance(payload, dict):
        return None
    try:
        snapshot = RepoSnapshot(
            snapshot_id=str(payload.get("snapshot_id") or ""),
            root_path=str(payload.get("root_path") or ""),
            repo_type=str(payload.get("repo_type") or "unknown"),
            language=str(payload.get("language") or "unknown"),
            framework=str(payload.get("framework") or ""),
            package_manager=str(payload.get("package_manager") or "none"),
            stack_family=str(payload.get("stack_family") or payload.get("repo_type") or "unknown"),
            entrypoints=list(payload.get("entrypoints") or []),
            test_runner=str(payload.get("test_runner") or ""),
            formatter=str(payload.get("formatter") or ""),
            linter=str(payload.get("linter") or ""),
            build_system=str(payload.get("build_system") or ""),
            workspace_roots=list(payload.get("workspace_roots") or []),
            available_gates=list(payload.get("available_gates") or []),
            commands=dict(payload.get("commands") or {}),
            available_commands=dict(payload.get("available_commands") or payload.get("commands") or {}),
            issues=list(payload.get("issues") or []),
            existing_files=list(payload.get("existing_files") or []),
            is_greenfield=bool(payload.get("is_greenfield", False)),
            supported=bool(payload.get("supported", True)),
            adapter_hint=str(payload.get("adapter_hint") or ""),
            fingerprint=str(payload.get("fingerprint") or ""),
            cache_hit=cache_hit,
            file_count=int(payload.get("file_count", 0) or 0),
        )
    except Exception:
        return None
    return snapshot


def _remember_snapshot(cache_key: str, snapshot: RepoSnapshot) -> None:
    _SNAPSHOT_MEMORY_CACHE[cache_key] = snapshot
    _SNAPSHOT_MEMORY_CACHE.move_to_end(cache_key)
    while len(_SNAPSHOT_MEMORY_CACHE) > _SNAPSHOT_CACHE_MAX:
        _SNAPSHOT_MEMORY_CACHE.popitem(last=False)


def _cache_path(cache_key: str) -> Path:
    return _SNAPSHOT_CACHE_DIR / f"{cache_key}.json"


def _read_git_head(root: Path) -> str:
    git_dir = root / ".git"
    try:
        if not git_dir.exists():
            return ""
        if git_dir.is_file():
            text = git_dir.read_text(encoding="utf-8", errors="ignore").strip()
            if text.startswith("gitdir:"):
                git_dir = (root / text.split(":", 1)[1].strip()).resolve()
        head_file = git_dir / "HEAD"
        if not head_file.exists():
            return ""
        head = head_file.read_text(encoding="utf-8", errors="ignore").strip()
        if head.startswith("ref:"):
            ref_file = git_dir / head.split(":", 1)[1].strip()
            if ref_file.exists():
                return ref_file.read_text(encoding="utf-8", errors="ignore").strip()
        return head
    except Exception:
        return ""


def _manifest_entries(root: Path) -> list[str]:
    patterns = [
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "pyproject.toml",
        "requirements.txt",
        "go.mod",
        "go.sum",
        "Cargo.toml",
        "Cargo.lock",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "composer.json",
        "composer.lock",
        "*.csproj",
        "*.sln",
        "index.html",
        "styles.css",
        "script.js",
    ]
    entries: list[str] = []
    for pattern in patterns:
        for path in root.glob(pattern):
            if not path.exists() or not path.is_file():
                continue
            try:
                stat = path.stat()
            except Exception:
                continue
            entries.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
    return sorted(set(entries))


def _repo_snapshot_cache_key(root: Path) -> str:
    try:
        root_stat = root.stat()
        root_marker = f"{root_stat.st_mtime_ns}:{root_stat.st_ctime_ns}"
    except Exception:
        root_marker = "0:0"
    seed = "|".join(
        [
            str(root),
            _read_git_head(root),
            root_marker,
            *list(_manifest_entries(root)),
        ]
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def _load_snapshot_cache(cache_key: str) -> RepoSnapshot | None:
    snapshot = _SNAPSHOT_MEMORY_CACHE.get(cache_key)
    if isinstance(snapshot, RepoSnapshot):
        cached = _snapshot_from_payload(snapshot.to_dict(), cache_hit=True)
        if cached is not None:
            _remember_snapshot(cache_key, cached)
        return cached
    cache_path = _cache_path(cache_key)
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    cached = _snapshot_from_payload(payload, cache_hit=True)
    if cached is not None:
        _remember_snapshot(cache_key, cached)
    return cached


def _store_snapshot_cache(cache_key: str, snapshot: RepoSnapshot) -> None:
    cached = _snapshot_from_payload(snapshot.to_dict(), cache_hit=False)
    if cached is None:
        return
    _remember_snapshot(cache_key, cached)
    try:
        _SNAPSHOT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(cache_key).write_text(json.dumps(cached.to_dict(), ensure_ascii=False), encoding="utf-8")
    except Exception:
        return


_ADAPTERS: list[LanguageAdapter] = [
    LanguageAdapter(
        adapter_id="vanilla_web",
        repo_types=["greenfield", "vanilla_web"],
        language="javascript",
        framework="vanilla",
        default_gates=["smoke", "dom_contract", "style"],
        supported_gates=["smoke", "dom_contract", "style"],
        claim_policy={"require_evidence": True, "require_verified_gates": False},
        canonical_roots=["index.html", "styles.css", "script.js", "assets", "styles", "scripts"],
        canonical_file_set=["index.html", "styles.css", "script.js"],
    ),
    LanguageAdapter(
        adapter_id="vite",
        repo_types=["vite"],
        language="typescript",
        framework="vite",
        default_gates=["lint", "typecheck", "test", "build"],
        supported_gates=["lint", "typecheck", "test", "build"],
        claim_policy={"require_evidence": True, "require_verified_gates": True},
        canonical_roots=["src", "public", "tests", "package.json"],
    ),
    LanguageAdapter(
        adapter_id="react",
        repo_types=["react"],
        language="typescript",
        framework="react",
        default_gates=["lint", "typecheck", "test", "build"],
        supported_gates=["lint", "typecheck", "test", "build"],
        claim_policy={"require_evidence": True, "require_verified_gates": True},
        canonical_roots=["src", "public", "tests", "package.json"],
    ),
    LanguageAdapter(
        adapter_id="next",
        repo_types=["next"],
        language="typescript",
        framework="next",
        default_gates=["lint", "typecheck", "test", "build"],
        supported_gates=["lint", "typecheck", "test", "build"],
        claim_policy={"require_evidence": True, "require_verified_gates": True},
        canonical_roots=["app", "pages", "components", "public", "tests", "package.json"],
    ),
    LanguageAdapter(
        adapter_id="node_service",
        repo_types=["node"],
        language="javascript",
        framework="node",
        default_gates=["lint", "test", "build"],
        supported_gates=["lint", "test", "build"],
        claim_policy={"require_evidence": True, "require_verified_gates": True},
        canonical_roots=["src", "lib", "tests", "package.json"],
    ),
    LanguageAdapter(
        adapter_id="python_app",
        repo_types=["python"],
        language="python",
        framework="python",
        default_gates=["format", "lint", "test"],
        supported_gates=["format", "lint", "test"],
        claim_policy={"require_evidence": True, "require_verified_gates": True},
        canonical_roots=["src", "app", "tests", "pyproject.toml", "requirements.txt"],
    ),
    LanguageAdapter(
        adapter_id="go_app",
        repo_types=["go"],
        language="go",
        framework="go",
        default_gates=["fmt", "test"],
        supported_gates=["fmt", "test"],
        claim_policy={"require_evidence": True, "require_verified_gates": True},
        canonical_roots=["cmd", "internal", "pkg", "go.mod"],
    ),
    LanguageAdapter(
        adapter_id="rust_app",
        repo_types=["rust"],
        language="rust",
        framework="rust",
        default_gates=["fmt", "clippy", "test"],
        supported_gates=["fmt", "clippy", "test"],
        claim_policy={"require_evidence": True, "require_verified_gates": True},
        canonical_roots=["src", "tests", "Cargo.toml"],
    ),
    LanguageAdapter(
        adapter_id="java_app",
        repo_types=["java"],
        language="java",
        framework="java",
        default_gates=["test", "build"],
        supported_gates=["test", "build"],
        claim_policy={"require_evidence": True, "require_verified_gates": True},
        canonical_roots=["src", "pom.xml", "build.gradle", "build.gradle.kts"],
    ),
    LanguageAdapter(
        adapter_id="dotnet_app",
        repo_types=["dotnet"],
        language="csharp",
        framework="dotnet",
        default_gates=["build", "test"],
        supported_gates=["build", "test"],
        claim_policy={"require_evidence": True, "require_verified_gates": True},
        canonical_roots=["src", "tests"],
    ),
    LanguageAdapter(
        adapter_id="php_app",
        repo_types=["php"],
        language="php",
        framework="php",
        default_gates=["lint", "test"],
        supported_gates=["lint", "test"],
        claim_policy={"require_evidence": True, "require_verified_gates": True},
        canonical_roots=["src", "app", "tests", "composer.json"],
    ),
]


def iter_adapters() -> list[LanguageAdapter]:
    return list(_ADAPTERS)


def build_style_lock_spec(style_intent: StyleIntent, adapter: LanguageAdapter) -> StyleLockSpec:
    return StyleLockSpec(
        visual_direction=str(style_intent.visual_direction or ""),
        design_tokens=dict(style_intent.design_tokens or {}),
        layout_rules=list(style_intent.layout_rules or []),
        interaction_rules=list(style_intent.interaction_rules or []),
        forbidden_patterns=list(style_intent.forbidden_patterns or []),
        canonical_file_set=list(adapter.canonical_file_set or []),
    )


def _extract_greenfield_targets(task_spec: dict[str, Any] | None, root: Path) -> list[str]:
    targets: list[str] = []
    spec = dict(task_spec or {})
    for artifact in list(spec.get("artifacts_expected") or []):
        if not isinstance(artifact, dict):
            continue
        raw = str(artifact.get("path") or "").strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        targets.append(str(candidate))
    for step in list(spec.get("steps") or []):
        if not isinstance(step, dict):
            continue
        if str(step.get("action") or "").strip().lower() != "create_coding_project":
            continue
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        output_dir = str(params.get("output_dir") or "").strip()
        project_name = str(params.get("project_name") or "").strip() or "elyan-project"
        if not output_dir:
            continue
        base_dir = Path(output_dir).expanduser()
        if not base_dir.is_absolute():
            base_dir = (root / base_dir).resolve()
        else:
            base_dir = base_dir.resolve()
        targets.append(str(base_dir))
        targets.append(str((base_dir / _sanitize_project_slug(project_name)).resolve()))
    return _dedupe_keep_order(targets)


def detect_repo_snapshot(workspace_path: str, *, workspace_files: dict[str, str] | list[str] | None = None) -> RepoSnapshot:
    root = Path(str(workspace_path or Path.cwd())).expanduser().resolve()
    cache_key = ""
    if workspace_files is None:
        cache_key = _repo_snapshot_cache_key(root)
        cached = _load_snapshot_cache(cache_key)
        if cached is not None:
            return cached
    files: list[str]
    file_count = 0
    if isinstance(workspace_files, dict):
        files = [str(key or "").strip() for key in workspace_files.keys() if str(key or "").strip()]
        file_count = len(files)
    elif isinstance(workspace_files, list):
        files = [str(item or "").strip() for item in workspace_files if str(item or "").strip()]
        file_count = len(files)
    else:
        files, file_count = _iter_workspace_files(root)
    files = _dedupe_keep_order(files)
    lowered = {item.lower() for item in files}
    scripts = _parse_package_scripts(root)
    package_json = _read_json(root / "package.json")
    deps = {}
    if isinstance(package_json.get("dependencies"), dict):
        deps.update(package_json.get("dependencies") or {})
    if isinstance(package_json.get("devDependencies"), dict):
        deps.update(package_json.get("devDependencies") or {})
    dep_names = {str(key).strip().lower() for key in deps.keys()}

    repo_type = "unknown"
    language = "unknown"
    framework = ""
    build_system = ""
    test_runner = ""
    formatter = ""
    linter = ""
    entrypoints: list[str] = []

    if not files:
        repo_type = "greenfield"
        build_system = "greenfield"
    elif "next" in dep_names:
        repo_type = "next"
        language = "typescript"
        framework = "next"
        build_system = "npm"
        entrypoints = [item for item in files if item.lower() in {"app/page.tsx", "app/page.jsx", "pages/index.tsx", "pages/index.jsx"}][:3]
    elif "vite" in dep_names:
        repo_type = "vite"
        language = "typescript"
        framework = "vite"
        build_system = "npm"
        entrypoints = [item for item in files if item.lower() in {"src/main.ts", "src/main.tsx", "src/main.js", "src/main.jsx"}][:3]
    elif "react" in dep_names:
        repo_type = "react"
        language = "typescript"
        framework = "react"
        build_system = "npm"
        entrypoints = [item for item in files if item.lower() in {"src/main.tsx", "src/main.jsx", "src/index.tsx", "src/index.jsx"}][:3]
    elif "package.json" in lowered:
        repo_type = "node"
        language = "javascript"
        framework = "node"
        build_system = "npm"
        entrypoints = [item for item in files if item.lower() in {"src/index.js", "src/index.ts", "index.js", "index.ts", "server.js", "server.ts"}][:3]
    elif "pyproject.toml" in lowered or "requirements.txt" in lowered or any(item.endswith(".py") for item in lowered):
        repo_type = "python"
        language = "python"
        framework = "python"
        build_system = "python"
        entrypoints = [item for item in files if item.lower() in {"main.py", "app.py", "src/main.py"}][:3]
    elif "go.mod" in lowered:
        repo_type = "go"
        language = "go"
        framework = "go"
        build_system = "go"
        entrypoints = [item for item in files if item.endswith("/main.go") or item.lower() == "main.go"][:3]
    elif "cargo.toml" in lowered:
        repo_type = "rust"
        language = "rust"
        framework = "rust"
        build_system = "cargo"
        entrypoints = [item for item in files if item.lower() in {"src/main.rs", "src/lib.rs"}][:3]
    elif "pom.xml" in lowered or "build.gradle" in lowered or "build.gradle.kts" in lowered:
        repo_type = "java"
        language = "java"
        framework = "java"
        build_system = "java"
        entrypoints = [item for item in files if item.endswith(".java")][:3]
    elif any(item.endswith(".csproj") for item in lowered) or any(item.endswith(".sln") for item in lowered):
        repo_type = "dotnet"
        language = "csharp"
        framework = "dotnet"
        build_system = "dotnet"
        entrypoints = [item for item in files if item.endswith(".csproj") or item.lower() == "program.cs"][:3]
    elif "composer.json" in lowered or any(item.endswith(".php") for item in lowered):
        repo_type = "php"
        language = "php"
        framework = "php"
        build_system = "php"
        entrypoints = [item for item in files if item.endswith(".php")][:3]
    elif "index.html" in lowered or any(item.endswith(".html") for item in lowered):
        repo_type = "vanilla_web"
        language = "javascript"
        framework = "vanilla"
        build_system = "static"
        entrypoints = [item for item in files if item.lower() == "index.html"][:1] or [item for item in files if item.endswith(".html")][:3]

    if "eslint" in dep_names or any("eslint" in command.lower() for command in scripts.values()):
        linter = "eslint"
    elif repo_type in {"python", "go", "rust", "php"}:
        linter = {"python": "ruff", "go": "go vet", "rust": "clippy", "php": "php -l"}.get(repo_type, "")

    if repo_type in {"react", "vite", "next", "node"}:
        formatter = "prettier"
    elif repo_type == "python":
        formatter = "black"
    elif repo_type == "go":
        formatter = "gofmt"
    elif repo_type == "rust":
        formatter = "cargo fmt"
    elif repo_type == "dotnet":
        formatter = "dotnet format"

    if "jest" in dep_names:
        test_runner = "jest"
    elif "vitest" in dep_names:
        test_runner = "vitest"
    elif repo_type == "python":
        test_runner = "pytest"
    elif repo_type == "go":
        test_runner = "go test"
    elif repo_type == "rust":
        test_runner = "cargo test"
    elif repo_type == "java":
        test_runner = "maven" if "pom.xml" in lowered else "gradle"
    elif repo_type == "dotnet":
        test_runner = "dotnet test"

    issues: list[str] = []
    if repo_type == "vanilla_web":
        html_files = [item for item in files if item.endswith(".html")]
        for rel in html_files[:6]:
            html_path = (root / rel).resolve()
            for ref, state in _detect_html_refs(root, html_path):
                if state == "missing":
                    issues.append(f"missing_local_ref:{rel}->{ref}")
                    if ref.endswith((".js", ".css")):
                        issues.append(f"entrypoint_mismatch:{rel}->{ref}")
    if _detect_multi_skeleton(files):
        issues.append("multi_skeleton_repo")

    workspace_roots = _dedupe_keep_order(Path(item).parts[0] for item in files if Path(item).parts)
    snapshot_id = _stable_id("repo", f"{root}:{'|'.join(files[:60])}:{repo_type}")
    snapshot = RepoSnapshot(
        snapshot_id=snapshot_id,
        root_path=str(root),
        repo_type=repo_type,
        language=language,
        framework=framework,
        package_manager=_infer_package_manager(root, files),
        stack_family=repo_type,
        entrypoints=entrypoints,
        test_runner=test_runner,
        formatter=formatter,
        linter=linter,
        build_system=build_system,
        workspace_roots=workspace_roots,
        available_gates=_infer_available_gates(repo_type, scripts, files),
        commands=scripts,
        available_commands=dict(scripts),
        issues=_dedupe_keep_order(issues),
        existing_files=files,
        is_greenfield=repo_type == "greenfield",
        supported=repo_type != "unknown",
        adapter_hint=repo_type,
        fingerprint=cache_key or snapshot_id,
        cache_hit=False,
        file_count=file_count,
    )
    if workspace_files is None and cache_key:
        _store_snapshot_cache(cache_key, snapshot)
    return snapshot


def _infer_greenfield_repo_type(user_input: str, task_spec: dict[str, Any] | None = None) -> str:
    low = str(user_input or "").strip().lower()
    if any(token in low for token in ("next.js", "nextjs", "next ")):
        return "next"
    if "vite" in low:
        return "vite"
    if "react" in low:
        return "react"
    if any(token in low for token in ("html", "css", "javascript", "website", "web sitesi", "landing page")):
        return "vanilla_web"
    if any(token in low for token in ("python", "django", "flask", "fastapi")):
        return "python"
    if "golang" in low or re.search(r"\bgo\b", low):
        return "go"
    if "rust" in low:
        return "rust"
    if "java" in low:
        return "java"
    if any(token in low for token in ("c#", ".net", "dotnet")):
        return "dotnet"
    if "php" in low:
        return "php"
    if isinstance(task_spec, dict):
        params = task_spec.get("steps") if isinstance(task_spec.get("steps"), list) else []
        if any(str((step or {}).get("action") or "").strip().lower() == "create_coding_project" for step in params if isinstance(step, dict)):
            return "vanilla_web"
    return "unknown"


def select_language_adapter(
    snapshot: RepoSnapshot,
    *,
    user_input: str = "",
    task_spec: dict[str, Any] | None = None,
    allowlist: list[str] | None = None,
) -> tuple[LanguageAdapter | None, FailureEnvelope | None]:
    repo_type = str(snapshot.repo_type or "unknown").strip().lower()
    if repo_type == "greenfield":
        repo_type = _infer_greenfield_repo_type(user_input, task_spec=task_spec)
    adapter = next((item for item in _ADAPTERS if repo_type in item.repo_types), None)
    if adapter is None:
        return None, FailureEnvelope(
            code="unsupported_stack",
            reason=f"Desteklenmeyen repo tipi: {repo_type or 'unknown'}",
            details=list(snapshot.issues or []),
            retryable=False,
            guidance="Desteklenen stack ailelerinden birini belirt veya repoyu açıkça tanımla.",
        )
    normalized_allowlist = [str(item).strip() for item in list(allowlist or []) if str(item).strip()]
    if normalized_allowlist and adapter.adapter_id not in normalized_allowlist:
        return None, FailureEnvelope(
            code="adapter_blocked",
            reason=f"Adapter allowlist bu repo için {adapter.adapter_id} kullanımına izin vermiyor.",
            details=[f"allowlist={','.join(normalized_allowlist)}"],
            retryable=False,
            guidance="coding.adapter_allowlist politikasını güncelle.",
        )
    return adapter, None


def build_style_intent(
    user_input: str,
    *,
    repo_snapshot: RepoSnapshot | None = None,
    task_spec: dict[str, Any] | None = None,
) -> StyleIntent:
    low = str(user_input or "").strip().lower()
    repo_type = str((repo_snapshot.repo_type if isinstance(repo_snapshot, RepoSnapshot) else "") or "").strip().lower()
    frontend = repo_type in {"greenfield", "vanilla_web", "react", "vite", "next"} or any(
        token in low for token in ("website", "web sitesi", "landing page", "html", "css", "frontend", "ui")
    )
    visual_direction = "pragmatic_product"
    if frontend:
        visual_direction = "editorial_warm"
        if any(token in low for token in ("minimal", "clean", "sade")):
            visual_direction = "minimal_editorial"
        elif any(token in low for token in ("dashboard", "saas", "panel")):
            visual_direction = "structured_saas"
        elif any(token in low for token in ("retro", "nostalji", "vintage")):
            visual_direction = "retro_playful"
        elif any(token in low for token in ("bold", "çarpıcı", "carpici", "iddialı", "iddiali")):
            visual_direction = "bold_magazine"

    palette = {
        "bg": "#f6efe6",
        "surface": "#fffaf4",
        "text": "#2d2119",
        "accent": "#cf6b2a",
        "accent_alt": "#3f7a52",
    }
    if "kedi" in low or "cat" in low:
        palette = {
            "bg": "#f4eadf",
            "surface": "#fffaf2",
            "text": "#2a1d17",
            "accent": "#d46a2e",
            "accent_alt": "#5b7b56",
        }

    forbidden = [
        "generic_feature_grid",
        "default_inter_font_stack",
        "placeholder_copy",
        "unverified_delivery_claim",
    ]
    if frontend:
        forbidden.extend(["purple_on_white_default", "template_hero_with_three_cards"])

    return StyleIntent(
        visual_direction=visual_direction,
        design_tokens={
            "palette": palette,
            "radius": "18px" if frontend else "10px",
            "shadow": "soft" if frontend else "minimal",
            "density": "comfortable",
        },
        layout_rules=[
            "single_canonical_solution",
            "semantic_structure_required",
            "responsive_first",
        ],
        interaction_rules=[
            "short_feedback_loops",
            "progressive_reveal_only_when_useful",
        ],
        forbidden_patterns=_dedupe_keep_order(forbidden),
        acceptance_screens=["desktop_home", "mobile_home"] if frontend else [],
        code_style="clean_code",
        user_tone="pragmatic",
    )


def _contract_payload(contract: CodingContract | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(contract, CodingContract):
        return contract.to_dict()
    return dict(contract or {})


def build_project_brief(
    *,
    user_input: str,
    task_spec: dict[str, Any] | None,
    snapshot: RepoSnapshot,
    contract: CodingContract | dict[str, Any] | None,
    style_intent: StyleIntent,
) -> ProjectBrief:
    spec = dict(task_spec or {})
    contract_payload = _contract_payload(contract)
    deliverables = [dict(item) for item in list(spec.get("deliverables") or []) if isinstance(item, dict)]
    if not deliverables:
        deliverables = [dict(item) for item in list(spec.get("artifacts_expected") or []) if isinstance(item, dict)]
    title = str(spec.get("goal") or spec.get("user_goal") or user_input or "Project brief").strip()
    objective = str(user_input or spec.get("goal") or spec.get("user_goal") or title).strip()
    project_name = ""
    for candidate in deliverables:
        project_name = str(candidate.get("name") or candidate.get("label") or candidate.get("path") or "").strip()
        if project_name:
            break
    return ProjectBrief(
        task_id=str(spec.get("task_id") or ""),
        title=title,
        objective=objective,
        repo_root=str(snapshot.root_path or ""),
        repo_type=str(snapshot.repo_type or "unknown"),
        language=str(snapshot.language or "unknown"),
        framework=str(snapshot.framework or ""),
        package_manager=str(snapshot.package_manager or "none"),
        stack_family=str(snapshot.stack_family or snapshot.repo_type or "unknown"),
        risk_level=str(spec.get("risk_level") or contract_payload.get("risk_level") or "normal"),
        deliverables=deliverables,
        verification_gates=_dedupe_keep_order([str(item).strip().lower() for item in list(contract_payload.get("required_gates") or []) if str(item).strip()]),
        output_dir=project_name,
        style_direction=str(style_intent.visual_direction or ""),
        privacy_mode="local_first",
        metadata={
            "adapter_id": str(contract_payload.get("adapter_id") or contract_payload.get("execution_adapter") or ""),
            "contract_id": str(contract_payload.get("contract_id") or ""),
            "repo_snapshot_id": str(snapshot.snapshot_id or ""),
            "workspace_roots": list(snapshot.workspace_roots or []),
            "entrypoints": list(snapshot.entrypoints or []),
            "allowed_write_paths": list(contract_payload.get("allowed_write_paths") or []),
            "forbidden_write_paths": list(contract_payload.get("forbidden_write_paths") or []),
        },
    )


def build_project_artifacts(
    *,
    task_spec: dict[str, Any] | None,
    snapshot: RepoSnapshot,
    contract: CodingContract | dict[str, Any] | None,
    brief: ProjectBrief,
) -> list[ProjectArtifact]:
    spec = dict(task_spec or {})
    contract_payload = _contract_payload(contract)
    items: list[ProjectArtifact] = []
    deliverables = [item for item in list(spec.get("deliverables") or []) if isinstance(item, dict)]
    if not deliverables:
        deliverables = [item for item in list(spec.get("artifacts_expected") or []) if isinstance(item, dict)]
    for index, item in enumerate(deliverables, start=1):
        path = str(item.get("path") or item.get("output_path") or item.get("artifact_path") or "").strip()
        if not path:
            continue
        items.append(
            ProjectArtifact(
                brief_id=brief.brief_id,
                path=path,
                kind=str(item.get("kind") or item.get("type") or "artifact"),
                label=str(item.get("name") or item.get("label") or Path(path).name or f"artifact_{index}"),
                expected=bool(item.get("required", True)),
                source="deliverables",
                metadata={
                    "must_exist": bool(item.get("must_exist", False)),
                    "index": index,
                    "repo_snapshot_id": str(snapshot.snapshot_id or ""),
                },
            )
        )
    if not items:
        for index, path in enumerate(list(contract_payload.get("allowed_write_paths") or [])[:4], start=1):
            candidate = str(path or "").strip()
            if not candidate:
                continue
            items.append(
                ProjectArtifact(
                    brief_id=brief.brief_id,
                    path=candidate,
                    kind="path",
                    label=Path(candidate).name or f"artifact_{index}",
                    expected=False,
                    source="allowed_write_paths",
                    metadata={
                        "index": index,
                        "repo_snapshot_id": str(snapshot.snapshot_id or ""),
                    },
                )
            )
    return items


def _recommended_write_paths(
    root: Path,
    snapshot: RepoSnapshot,
    adapter: LanguageAdapter,
    *,
    task_spec: dict[str, Any] | None = None,
) -> list[str]:
    if snapshot.is_greenfield:
        greenfield_targets = _extract_greenfield_targets(task_spec, root)
        return greenfield_targets or [str(root)]
    preferred: list[str] = []
    for rel in list(snapshot.entrypoints or []):
        preferred.append(str((root / rel).resolve()))
    for rel in snapshot.existing_files:
        parts = Path(rel).parts
        if not parts:
            continue
        first = parts[0]
        if first.startswith("."):
            continue
        if first in {"src", "app", "pages", "public", "styles", "scripts", "tests", "components", "assets", "lib", "internal", "pkg", "cmd"}:
            preferred.append(str((root / first).resolve()))
        elif rel in {"index.html", "styles.css", "script.js", "package.json", "pyproject.toml", "go.mod", "Cargo.toml", "pom.xml", "composer.json", "README.md"}:
            preferred.append(str((root / rel).resolve()))
    for rel in adapter.canonical_roots:
        preferred.append(str((root / rel).resolve()))
    return _dedupe_keep_order(preferred) or [str(root)]


def build_coding_contract(
    *,
    user_input: str,
    task_spec: dict[str, Any] | None,
    workspace_path: str,
    runtime_policy: dict[str, Any] | None = None,
    workspace_files: dict[str, str] | list[str] | None = None,
) -> tuple[RepoSnapshot, CodingContract, StyleIntent, FailureEnvelope | None]:
    policy = runtime_policy if isinstance(runtime_policy, dict) else {}
    coding_policy = policy.get("coding", {}) if isinstance(policy.get("coding"), dict) else {}
    security = policy.get("security", {}) if isinstance(policy.get("security"), dict) else {}
    root = Path(str(workspace_path or Path.cwd())).expanduser().resolve()
    snapshot = detect_repo_snapshot(str(root), workspace_files=workspace_files)
    adapter, failure = select_language_adapter(
        snapshot,
        user_input=user_input,
        task_spec=task_spec,
        allowlist=list(coding_policy.get("adapter_allowlist") or []),
    )
    style_intent = build_style_intent(user_input, repo_snapshot=snapshot, task_spec=task_spec)
    if adapter is None:
        contract = CodingContract(
            contract_id=_stable_id("contract", f"{snapshot.snapshot_id}:unsupported"),
            execution_mode="contract_first_coding",
            repo_snapshot_id=snapshot.snapshot_id,
            adapter_id="unsupported",
            repo_type=snapshot.repo_type,
            supported=False,
            required_gates=[],
            evidence_requirements=["artifact_paths", "gate_results"],
            allowed_write_paths=[],
            forbidden_write_paths=list(security.get("denied_roots") or []),
            execution_adapter="unsupported",
            write_scope=WriteScopePolicy(
                allowed_roots=[],
                forbidden_roots=list(security.get("denied_roots") or []),
                canonical_file_set=[],
            ).to_dict(),
            claim_policy={"require_evidence": True, "require_verified_gates": True},
            style_intent=style_intent.to_dict(),
            style_lock={},
            repair_budget=max(0, int(coding_policy.get("max_repair_loops", 2) or 2)),
            model_ladder_trace=["deterministic_repo_truth", "small_router", "mid_planner"],
            failure_envelope=failure.to_dict() if isinstance(failure, FailureEnvelope) else {},
        )
        return snapshot, contract, style_intent, failure

    style_lock = build_style_lock_spec(style_intent, adapter)
    required_gates = [gate for gate in adapter.default_gates if gate in list(snapshot.available_gates or [])]
    if snapshot.is_greenfield and not required_gates:
        required_gates = list(adapter.default_gates[:1] or ["smoke"])
    elif not required_gates:
        required_gates = list(snapshot.available_gates or [])
    if adapter.adapter_id == "vanilla_web" and bool(coding_policy.get("style_lock", True)):
        required_gates = _dedupe_keep_order([*required_gates, "dom_contract", "style"])
    denied = [str(item).strip() for item in list(security.get("denied_roots") or []) if str(item).strip()]
    allowed = _recommended_write_paths(root, snapshot, adapter, task_spec=task_spec)
    write_scope = WriteScopePolicy(
        allowed_roots=allowed,
        forbidden_roots=denied,
        canonical_file_set=list(adapter.canonical_file_set or []),
    )
    model_ladder = [
        "deterministic_repo_truth",
        "small_router",
        "mid_planner",
        "strong_debug" if bool(coding_policy.get("cloud_debug_budget", 1.0)) else "local_only",
    ]
    contract = CodingContract(
        contract_id=_stable_id("contract", f"{snapshot.snapshot_id}:{adapter.adapter_id}:{user_input}"),
        execution_mode="contract_first_coding",
        repo_snapshot_id=snapshot.snapshot_id,
        adapter_id=adapter.adapter_id,
        execution_adapter=adapter.adapter_id,
        repo_type=snapshot.repo_type if snapshot.repo_type != "greenfield" else adapter.repo_types[0],
        supported=True,
        required_gates=_dedupe_keep_order(required_gates),
        evidence_requirements=["artifact_paths", "commands", "gate_results", "diff_summary"],
        allowed_write_paths=list(write_scope.allowed_roots),
        forbidden_write_paths=denied,
        write_scope=write_scope.to_dict(),
        claim_policy={
            "require_evidence": bool(coding_policy.get("require_evidence", True)),
            "require_verified_gates": bool(adapter.claim_policy.get("require_verified_gates", True)),
            "style_lock": bool(coding_policy.get("style_lock", True)),
        },
        style_intent=style_intent.to_dict(),
        style_lock=style_lock.to_dict(),
        repair_budget=max(0, int(coding_policy.get("max_repair_loops", 2) or 2)),
        model_ladder_trace=model_ladder,
        failure_envelope={},
    )
    return snapshot, contract, style_intent, None


def prepare_contract_first_coding(
    *,
    user_input: str,
    task_spec: dict[str, Any] | None,
    workspace_path: str,
    runtime_policy: dict[str, Any] | None = None,
    workspace_files: dict[str, str] | list[str] | None = None,
) -> dict[str, Any]:
    snapshot, contract, style_intent, failure = build_coding_contract(
        user_input=user_input,
        task_spec=task_spec,
        workspace_path=workspace_path,
        runtime_policy=runtime_policy,
        workspace_files=workspace_files,
    )
    project_brief = build_project_brief(
        user_input=user_input,
        task_spec=task_spec,
        snapshot=snapshot,
        contract=contract,
        style_intent=style_intent,
    )
    project_artifacts = [artifact.to_dict() for artifact in build_project_artifacts(
        task_spec=task_spec,
        snapshot=snapshot,
        contract=contract,
        brief=project_brief,
    )]
    spec = dict(task_spec or {})
    if spec:
        spec["execution_mode"] = str(spec.get("execution_mode") or contract.execution_mode)
        spec["repo_snapshot"] = snapshot.to_dict()
        spec["coding_contract"] = contract.to_dict()
        spec["style_intent"] = style_intent.to_dict()
        spec["project_brief"] = project_brief.to_dict()
        spec["project_artifacts"] = list(project_artifacts)
        spec["required_gates"] = list(contract.required_gates)
        spec["evidence_requirements"] = list(contract.evidence_requirements)
        spec["allowed_write_paths"] = list(contract.allowed_write_paths)
        spec["forbidden_write_paths"] = list(contract.forbidden_write_paths)
        spec["claim_policy"] = dict(contract.claim_policy)
        spec["write_scope"] = dict(contract.write_scope)
        spec["style_lock"] = dict(contract.style_lock)
    return {
        "task_spec": spec if spec else None,
        "repo_snapshot": snapshot.to_dict(),
        "coding_contract": contract.to_dict(),
        "style_intent": style_intent.to_dict(),
        "project_brief": project_brief.to_dict(),
        "project_artifacts": list(project_artifacts),
        "failure": failure.to_dict() if isinstance(failure, FailureEnvelope) else {},
    }


def build_write_scope_policy(contract: dict[str, Any] | CodingContract | None) -> WriteScopePolicy:
    payload = contract.to_dict() if isinstance(contract, CodingContract) else dict(contract or {})
    write_scope = payload.get("write_scope") if isinstance(payload.get("write_scope"), dict) else {}
    allowed = list(write_scope.get("allowed_roots") or payload.get("allowed_write_paths") or [])
    forbidden = list(write_scope.get("forbidden_roots") or payload.get("forbidden_write_paths") or [])
    canonical = list(write_scope.get("canonical_file_set") or [])
    return WriteScopePolicy(
        allowed_roots=[str(item).strip() for item in allowed if str(item).strip()],
        forbidden_roots=[str(item).strip() for item in forbidden if str(item).strip()],
        canonical_file_set=[str(item).strip() for item in canonical if str(item).strip()],
    )


def _package_script_command(package_manager: str, script: str) -> str:
    pm = str(package_manager or "npm").strip().lower()
    script_name = str(script or "").strip()
    if not script_name:
        return ""
    if pm == "pnpm":
        return f"pnpm {script_name}"
    if pm == "yarn":
        return f"yarn {script_name}"
    if pm == "bun":
        return f"bun run {script_name}"
    return f"npm run {script_name}"


def build_adapter_runner(snapshot: RepoSnapshot, adapter: LanguageAdapter) -> AdapterRunner:
    commands: dict[str, str] = {}
    available_scripts = dict(snapshot.available_commands or snapshot.commands or {})
    for gate in list(adapter.supported_gates or adapter.default_gates or []):
        if gate in available_scripts:
            commands[gate] = _package_script_command(snapshot.package_manager, gate)
    repo_type = str(snapshot.repo_type or "").strip().lower()
    if adapter.adapter_id == "python_app":
        if "format" in list(snapshot.available_gates or []):
            commands.setdefault("format", "python -m black --check .")
        if "lint" in list(snapshot.available_gates or []):
            commands.setdefault("lint", "python -m ruff check .")
        if "test" in list(snapshot.available_gates or []):
            commands.setdefault("test", "python -m pytest")
    elif adapter.adapter_id == "go_app":
        commands.setdefault("fmt", "gofmt -l .")
        commands.setdefault("test", "go test ./...")
    elif adapter.adapter_id == "rust_app":
        commands.setdefault("fmt", "cargo fmt -- --check")
        commands.setdefault("clippy", "cargo clippy --all-targets -- -D warnings")
        commands.setdefault("test", "cargo test")
    elif adapter.adapter_id == "java_app":
        if (Path(snapshot.root_path) / "pom.xml").exists():
            commands.setdefault("build", "mvn -q -DskipTests package")
            commands.setdefault("test", "mvn -q test")
        elif (Path(snapshot.root_path) / "build.gradle").exists() or (Path(snapshot.root_path) / "build.gradle.kts").exists():
            commands.setdefault("build", "./gradlew build")
            commands.setdefault("test", "./gradlew test")
    elif adapter.adapter_id == "dotnet_app":
        commands.setdefault("build", "dotnet build")
        commands.setdefault("test", "dotnet test")
    elif adapter.adapter_id == "php_app":
        if "lint" in list(snapshot.available_gates or []):
            commands.setdefault("lint", "php -l index.php")
        if "test" in available_scripts:
            commands.setdefault("test", _package_script_command(snapshot.package_manager, "test"))
    elif adapter.adapter_id == "node_service":
        if "test" in available_scripts:
            commands.setdefault("test", _package_script_command(snapshot.package_manager, "test"))
        if "build" in available_scripts:
            commands.setdefault("build", _package_script_command(snapshot.package_manager, "build"))
        if "lint" in available_scripts:
            commands.setdefault("lint", _package_script_command(snapshot.package_manager, "lint"))
    return AdapterRunner(
        adapter_id=adapter.adapter_id,
        repo_type=repo_type,
        root_path=str(snapshot.root_path),
        gate_commands=commands,
        supported_gates=list(adapter.supported_gates or adapter.default_gates or []),
        canonical_file_set=list(adapter.canonical_file_set or []),
    )


def _resolve_execution_root(snapshot: RepoSnapshot, artifact_paths: list[str] | None = None) -> Path:
    for raw in list(artifact_paths or []):
        value = str(raw or "").strip()
        if not value:
            continue
        candidate = Path(value).expanduser()
        if candidate.exists() and candidate.is_dir():
            return candidate.resolve()
        if candidate.suffix:
            return candidate.expanduser().resolve().parent
        return candidate.expanduser().resolve()
    return Path(snapshot.root_path).expanduser().resolve()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _extract_html_inventory(root: Path) -> tuple[set[str], set[str], list[str]]:
    ids: set[str] = set()
    classes: set[str] = set()
    issues: list[str] = []
    html_files = [root / "index.html"] if (root / "index.html").exists() else sorted(root.glob("*.html"))[:4]
    for html_path in html_files:
        content = _read_text(html_path)
        ids.update(match.group(1).strip() for match in re.finditer(r'id=["\']([^"\']+)["\']', content, re.IGNORECASE))
        for match in re.finditer(r'class=["\']([^"\']+)["\']', content, re.IGNORECASE):
            classes.update(token.strip() for token in str(match.group(1) or "").split() if token.strip())
        for ref, state in _detect_html_refs(root, html_path):
            if state == "missing":
                issues.append(f"missing_local_ref:{html_path.name}->{ref}")
    return ids, classes, _dedupe_keep_order(issues)


def _extract_js_selectors(root: Path) -> dict[str, list[str]]:
    ids: list[str] = []
    classes: list[str] = []
    js_files = [path for path in [root / "script.js", root / "main.js", root / "app.js"] if path.exists()]
    if not js_files:
        js_files = sorted(root.glob("*.js"))[:4]
    for js_path in js_files:
        content = _read_text(js_path)
        ids.extend(match.group(1).strip() for match in re.finditer(r'getElementById\(["\']([^"\']+)["\']\)', content))
        for match in re.finditer(r'querySelector(?:All)?\(["\']([.#][^"\']+)["\']\)', content):
            selector = str(match.group(1) or "").strip()
            if selector.startswith("#"):
                ids.append(selector[1:])
            elif selector.startswith("."):
                classes.append(selector[1:])
    return {
        "ids": _dedupe_keep_order(ids),
        "classes": _dedupe_keep_order(classes),
    }


def _verify_vanilla_web_smoke(root: Path) -> VerificationGateResult:
    if not root.exists():
        return VerificationGateResult(gate="smoke", ok=False, reason=f"missing_root:{root}")
    snapshot = detect_repo_snapshot(str(root), workspace_files=None)
    blockers = [issue for issue in list(snapshot.issues or []) if issue.startswith(("missing_local_ref", "entrypoint_mismatch"))]
    if not (root / "index.html").exists():
        blockers.append("missing:index.html")
    return VerificationGateResult(
        gate="smoke",
        ok=not blockers,
        evidence=[str(root / "index.html")] if (root / "index.html").exists() else [],
        reason=", ".join(blockers[:4]),
    )


def _verify_dom_contract(root: Path) -> VerificationGateResult:
    html_ids, html_classes, html_issues = _extract_html_inventory(root)
    js_selectors = _extract_js_selectors(root)
    missing_ids = [item for item in js_selectors.get("ids", []) if item not in html_ids]
    missing_classes = [item for item in js_selectors.get("classes", []) if item not in html_classes]
    problems = [*html_issues, *[f"missing_id:{item}" for item in missing_ids], *[f"missing_class:{item}" for item in missing_classes]]
    return VerificationGateResult(
        gate="dom_contract",
        ok=not problems,
        evidence=[str(root / "index.html"), str(root / "script.js")] if (root / "index.html").exists() else [],
        reason=", ".join(problems[:6]),
    )


def _verify_style_lock(root: Path, style_lock: dict[str, Any] | None = None) -> VerificationGateResult:
    payload = dict(style_lock or {})
    canonical = [str(item).strip() for item in list(payload.get("canonical_file_set") or []) if str(item).strip()]
    forbidden = [str(item).strip().lower() for item in list(payload.get("forbidden_patterns") or []) if str(item).strip()]
    css_path = root / "styles.css"
    html_path = root / "index.html"
    problems: list[str] = []
    for rel in canonical:
        if not (root / rel).exists():
            problems.append(f"missing:{rel}")
    if canonical:
        non_canonical_dirs = [name for name in ("docs", "tests", "src", "app", "pages", "scripts", "styles", "components") if (root / name).exists()]
        if non_canonical_dirs:
            problems.append(f"non_canonical_layout:{','.join(sorted(non_canonical_dirs))}")
    css_text = _read_text(css_path)
    html_text = _read_text(html_path)
    if css_path.exists():
        if ":root" not in css_text or css_text.count("--") < 3:
            problems.append("missing_design_tokens")
        if "default_inter_font_stack" in forbidden and re.search(r"\b(inter|arial|system-ui)\b", css_text, re.IGNORECASE):
            problems.append("forbidden_font_stack")
    if "placeholder_copy" in forbidden and re.search(r"(lorem ipsum|placeholder)", f"{css_text}\n{html_text}", re.IGNORECASE):
        problems.append("placeholder_copy_detected")
    return VerificationGateResult(
        gate="style",
        ok=not problems,
        evidence=[str(css_path)] if css_path.exists() else [],
        reason=", ".join(problems[:5]),
    )


def _run_gate_command(
    command: str,
    *,
    cwd: str,
    timeout_s: int = 180,
    command_runner: Callable[[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if callable(command_runner):
        result = command_runner(command, cwd)
        if isinstance(result, dict):
            return result
        return {"ok": bool(result), "stdout": "", "stderr": "", "exit_code": 0 if result else 1}
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_s or 180)),
        )
        return {
            "ok": completed.returncode == 0,
            "stdout": str(completed.stdout or "")[-1200:],
            "stderr": str(completed.stderr or "")[-1200:],
            "exit_code": int(completed.returncode),
        }
    except Exception as exc:
        return {"ok": False, "stdout": "", "stderr": str(exc), "exit_code": 1}


def run_adapter_verification_gates(
    *,
    snapshot: RepoSnapshot,
    contract: dict[str, Any] | CodingContract,
    artifact_paths: list[str] | None = None,
    style_intent: dict[str, Any] | StyleIntent | None = None,
    command_runner: Callable[[str, str], dict[str, Any]] | None = None,
    timeout_s: int = 180,
) -> ExecutionEvidence:
    contract_payload = contract.to_dict() if isinstance(contract, CodingContract) else dict(contract or {})
    adapter_id = str(contract_payload.get("execution_adapter") or contract_payload.get("adapter_id") or snapshot.adapter_hint or "").strip()
    adapter = next((item for item in _ADAPTERS if item.adapter_id == adapter_id), None)
    root = _resolve_execution_root(snapshot, artifact_paths=artifact_paths)
    if adapter is None:
        return ExecutionEvidence(
            root_path=str(root),
            artifact_paths=_dedupe_keep_order(list(artifact_paths or []) or [str(root)]),
            metadata={"failure": "unsupported_adapter", "adapter_id": adapter_id},
        )
    runner = build_adapter_runner(snapshot, adapter)
    requested = [str(item).strip().lower() for item in list(contract_payload.get("required_gates") or []) if str(item).strip()]
    gate_results: list[VerificationGateResult] = []
    commands_run: list[str] = []
    style_lock = contract_payload.get("style_lock") if isinstance(contract_payload.get("style_lock"), dict) else {}
    for gate in requested:
        if gate == "smoke" and adapter.adapter_id == "vanilla_web":
            gate_results.append(_verify_vanilla_web_smoke(root))
            continue
        if gate == "dom_contract" and adapter.adapter_id == "vanilla_web":
            gate_results.append(_verify_dom_contract(root))
            continue
        if gate == "style" and adapter.adapter_id == "vanilla_web":
            gate_results.append(_verify_style_lock(root, style_lock=style_lock))
            continue
        command = str(runner.gate_commands.get(gate) or "").strip()
        if not command:
            gate_results.append(VerificationGateResult(gate=gate, ok=False, reason="missing_command"))
            continue
        commands_run.append(command)
        outcome = _run_gate_command(command, cwd=str(root), timeout_s=timeout_s, command_runner=command_runner)
        evidence = []
        for key in ("stdout", "stderr"):
            chunk = str(outcome.get(key) or "").strip()
            if chunk:
                evidence.append(chunk[:300])
        gate_results.append(
            VerificationGateResult(
                gate=gate,
                ok=bool(outcome.get("ok", False)),
                command=command,
                evidence=evidence,
                reason="" if bool(outcome.get("ok", False)) else str(outcome.get("stderr") or outcome.get("stdout") or "command_failed")[:300],
            )
        )
    artifact_rows = _dedupe_keep_order(list(artifact_paths or []) or [str(root)])
    screenshots = [path for path in artifact_rows if str(path).lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
    return ExecutionEvidence(
        root_path=str(root),
        commands_run=_dedupe_keep_order(commands_run),
        gate_results=[row.to_dict() for row in gate_results],
        artifact_paths=artifact_rows,
        screenshots=_dedupe_keep_order(screenshots),
        metadata={"adapter_id": adapter.adapter_id, "runner": runner.to_dict(), "style_intent": style_intent.to_dict() if isinstance(style_intent, StyleIntent) else dict(style_intent or {})},
    )


def is_contract_first_coding_candidate(action: str, job_type: str, user_input: str = "") -> bool:
    low_action = str(action or "").strip().lower()
    low_job = str(job_type or "").strip().lower()
    low_input = str(user_input or "").strip().lower()
    if low_job == "code_project":
        return True
    if low_action in {"create_coding_project", "create_software_project_pack", "debug_code"}:
        return True
    markers = ("kod", "code", "python", "javascript", "typescript", "react", "website", "web sitesi", "refactor", "debug")
    return any(marker in low_input for marker in markers)


def _collect_artifact_paths(tool_results: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for row in tool_results:
        if not isinstance(row, dict):
            continue
        for key in ("path", "file_path", "output_path", "project_dir", "pack_dir", "image_path", "screenshot"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                paths.append(value.strip())
        raw = row.get("raw")
        if isinstance(raw, dict):
            for key in ("project_dir", "pack_dir", "path", "file_path", "output_path"):
                value = raw.get(key)
                if isinstance(value, str) and value.strip():
                    paths.append(value.strip())
            nested_paths = raw.get("artifact_paths")
            if isinstance(nested_paths, list):
                paths.extend(str(item).strip() for item in nested_paths if str(item).strip())
        nested = row.get("artifact_paths")
        if isinstance(nested, list):
            paths.extend(str(item).strip() for item in nested if str(item).strip())
    return _dedupe_keep_order(paths)


def _extract_gate_results(qa_results: dict[str, Any], required_gates: list[str]) -> list[VerificationGateResult]:
    results: dict[str, VerificationGateResult] = {}
    adapter_gate_rows = qa_results.get("adapter_gate_results")
    if isinstance(adapter_gate_rows, list):
        for row in adapter_gate_rows:
            if not isinstance(row, dict):
                continue
            gate_name = str(row.get("gate") or "").strip().lower()
            if not gate_name:
                continue
            results[gate_name] = VerificationGateResult(
                gate=gate_name,
                ok=bool(row.get("ok", False)),
                command=str(row.get("command") or ""),
                evidence=[str(item).strip() for item in list(row.get("evidence") or []) if str(item).strip()],
                reason=str(row.get("reason") or ""),
            )
    code_gate = qa_results.get("code_gate") if isinstance(qa_results.get("code_gate"), dict) else {}
    failed = [str(item).strip().lower() for item in list(code_gate.get("failed") or []) if str(item).strip()]
    if required_gates:
        for gate in required_gates:
            results.setdefault(gate, VerificationGateResult(gate=gate, ok=gate not in failed, reason="" if gate not in failed else "failed"))
    for gate in list(code_gate.get("failed") or []):
        gate_name = str(gate).strip().lower()
        results[gate_name] = VerificationGateResult(gate=gate_name, ok=False, reason="failed")
    upgrade_contract = qa_results.get("upgrade_output_contract") if isinstance(qa_results.get("upgrade_output_contract"), dict) else {}
    if upgrade_contract:
        results.setdefault(
            "output_contract",
            VerificationGateResult(
                gate="output_contract",
                ok=bool(upgrade_contract.get("ok", False)),
                reason=", ".join(str(item) for item in list(upgrade_contract.get("errors") or [])),
            ),
        )
    return list(results.values())


def build_evidence_bundle(
    *,
    tool_results: list[dict[str, Any]] | None = None,
    qa_results: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
    final_response: str = "",
) -> EvidenceBundle:
    results = [row for row in list(tool_results or []) if isinstance(row, dict)]
    qa = dict(qa_results or {})
    contract_payload = dict(contract or {})
    artifact_paths = _collect_artifact_paths(results)
    required_gates = [str(item).strip().lower() for item in list(contract_payload.get("required_gates") or []) if str(item).strip()]
    gate_results = [item.to_dict() for item in _extract_gate_results(qa, required_gates)]
    commands: list[str] = []
    adapter_execution = qa.get("adapter_execution") if isinstance(qa.get("adapter_execution"), dict) else {}
    if isinstance(adapter_execution.get("commands_run"), list):
        commands.extend(str(item).strip() for item in adapter_execution.get("commands_run") if str(item).strip())
    if isinstance(adapter_execution.get("artifact_paths"), list):
        artifact_paths.extend(str(item).strip() for item in adapter_execution.get("artifact_paths") if str(item).strip())
    code_repair_plan = qa.get("code_repair_plan") if isinstance(qa.get("code_repair_plan"), dict) else {}
    if isinstance(code_repair_plan.get("commands"), list):
        commands.extend(str(item).strip() for item in code_repair_plan.get("commands") if str(item).strip())
    upgrade_contract = qa.get("upgrade_output_contract") if isinstance(qa.get("upgrade_output_contract"), dict) else {}
    if upgrade_contract:
        commands.extend(str(item).strip() for item in list(upgrade_contract.get("commands") or []) if str(item).strip())
    bundle = EvidenceBundle(
        bundle_id=_stable_id("evidence", f"{time.time()}:{'|'.join(artifact_paths)}:{final_response[:80]}"),
        artifact_paths=_dedupe_keep_order(artifact_paths),
        gate_results=gate_results,
        commands=_dedupe_keep_order(commands),
        screenshots=_dedupe_keep_order([path for path in artifact_paths if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]),
        diff_summary=str(adapter_execution.get("diff_summary") or qa.get("diff_summary") or "")[:500],
        claims_blocked=False,
        metadata={"required_gates": required_gates, "adapter_execution": dict(adapter_execution or {})},
    )
    return bundle


def evaluate_coding_gate_state(contract: dict[str, Any] | None, bundle: dict[str, Any] | EvidenceBundle | None) -> dict[str, Any]:
    contract_payload = dict(contract or {})
    if isinstance(bundle, EvidenceBundle):
        bundle_payload = bundle.to_dict()
    else:
        bundle_payload = dict(bundle or {})
    required = [str(item).strip().lower() for item in list(contract_payload.get("required_gates") or []) if str(item).strip()]
    gate_rows = bundle_payload.get("gate_results")
    if not isinstance(gate_rows, list):
        gate_rows = []
    passed = [str(item.get("gate") or "").strip().lower() for item in gate_rows if isinstance(item, dict) and item.get("ok") is True]
    failed = [str(item.get("gate") or "").strip().lower() for item in gate_rows if isinstance(item, dict) and item.get("ok") is False]
    missing = [gate for gate in required if gate not in passed and gate not in failed]
    artifact_paths = [str(item).strip() for item in list(bundle_payload.get("artifact_paths") or []) if str(item).strip()]
    claim_policy = contract_payload.get("claim_policy") if isinstance(contract_payload.get("claim_policy"), dict) else {}
    claim_blocked_reason = ""
    if bool(claim_policy.get("require_evidence", True)) and not artifact_paths:
        claim_blocked_reason = "missing_artifact_evidence"
    elif bool(claim_policy.get("require_verified_gates", True)) and (failed or missing):
        claim_blocked_reason = "missing_verified_gates"
    ok = not claim_blocked_reason
    return {
        "ok": ok,
        "required": required,
        "passed": _dedupe_keep_order(passed),
        "failed": _dedupe_keep_order(failed),
        "missing": _dedupe_keep_order(missing),
        "claim_blocked_reason": claim_blocked_reason,
    }


__all__ = [
    "AdapterRunner",
    "CodingContract",
    "EvidenceBundle",
    "ExecutionEvidence",
    "FailureEnvelope",
    "LanguageAdapter",
    "RepoSnapshot",
    "StyleLockSpec",
    "StyleIntent",
    "VerificationGateResult",
    "WriteScopePolicy",
    "build_adapter_runner",
    "build_coding_contract",
    "build_evidence_bundle",
    "build_style_intent",
    "build_style_lock_spec",
    "build_write_scope_policy",
    "detect_repo_snapshot",
    "evaluate_coding_gate_state",
    "is_contract_first_coding_candidate",
    "iter_adapters",
    "prepare_contract_first_coding",
    "run_adapter_verification_gates",
    "select_language_adapter",
]
