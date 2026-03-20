from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from config.elyan_config import elyan_config
from utils.logger import get_logger

logger = get_logger("system_dependency_runtime")


SYSTEM_TRUST_LEVELS = {"trusted", "curated", "builtin", "local"}
SYSTEM_BLOCKED_SCHEMES = ("git+", "http://", "https://", "file:", "ssh://", "hg+", "svn+")
ROOT_REQUIRED_MANAGERS = {"apt", "apt-get", "dnf", "yum", "pacman", "zypper", "apk"}
PACKAGE_MANAGER_ORDER = {
    "Darwin": ["brew"],
    "Linux": ["apt-get", "dnf", "yum", "pacman", "zypper", "apk"],
    "Windows": ["winget", "choco"],
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _config_get(key: str, default: Any) -> Any:
    try:
        return elyan_config.get(key, default)
    except Exception:
        return default


def _normalize(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _path_home(*parts: str) -> Path:
    return Path.home().joinpath(*parts)


def _system_name() -> str:
    return platform.system() or "Unknown"


def _is_root() -> bool:
    if os.name == "nt":
        return True
    geteuid = getattr(os, "geteuid", None)
    try:
        return bool(callable(geteuid) and int(geteuid()) == 0)
    except Exception:
        return False


def _sudo_prefix() -> list[str]:
    if os.name == "nt" or _is_root():
        return []
    sudo = shutil.which("sudo")
    if sudo:
        return [sudo, "-n"]
    return []


def _manager_cmd(manager: str, package: str) -> list[list[str]]:
    manager = _normalize(manager)
    package = str(package or "").strip()
    if not package:
        return []
    if manager == "brew":
        return [["brew", "install", package]]
    if manager in {"apt", "apt-get"}:
        return [["apt-get", "update"], ["apt-get", "install", "-y", package]]
    if manager in {"dnf", "yum"}:
        return [[manager, "install", "-y", package]]
    if manager == "pacman":
        return [["pacman", "-Sy", "--noconfirm", package]]
    if manager == "zypper":
        return [["zypper", "--non-interactive", "install", "--auto-agree-with-licenses", package]]
    if manager == "apk":
        return [["apk", "add", package]]
    if manager == "winget":
        return [["winget", "install", "--id", package, "-e", "--accept-package-agreements", "--accept-source-agreements"]]
    if manager == "choco":
        return [["choco", "install", package, "-y", "--no-progress"]]
    return []


@dataclass(frozen=True)
class SystemBinarySpec:
    binary: str
    aliases: list[str] = field(default_factory=list)
    package_candidates: dict[str, list[str]] = field(default_factory=dict)
    install_commands: dict[str, list[list[str]]] = field(default_factory=dict)
    trust_level: str = "trusted"
    source: str = "system"
    notes: str = ""

    @property
    def binary_names(self) -> list[str]:
        return [name for name in [self.binary, *self.aliases] if str(name or "").strip()]


@dataclass
class SystemDependencyInstallRecord:
    binary: str
    aliases: list[str] = field(default_factory=list)
    package: str = ""
    manager: str = ""
    install_command: str = ""
    source: str = "system"
    trust_level: str = "trusted"
    status: str = "missing"
    reason: str = ""
    retryable: bool = False
    installed: bool = False
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    attempts: int = 0
    output: str = ""
    platform: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SYSTEM_BINARY_CATALOG: dict[str, SystemBinarySpec] = {
    "ffmpeg": SystemBinarySpec(
        binary="ffmpeg",
        aliases=["ffprobe"],
        package_candidates={
            "brew": ["ffmpeg"],
            "apt-get": ["ffmpeg"],
            "dnf": ["ffmpeg"],
            "yum": ["ffmpeg"],
            "pacman": ["ffmpeg"],
            "zypper": ["ffmpeg"],
            "apk": ["ffmpeg"],
            "winget": ["Gyan.FFmpeg", "BtbN.FFmpeg"],
            "choco": ["ffmpeg"],
        },
        notes="Audio/video processing binary pack.",
    ),
    "tesseract": SystemBinarySpec(
        binary="tesseract",
        package_candidates={
            "brew": ["tesseract"],
            "apt-get": ["tesseract-ocr"],
            "dnf": ["tesseract"],
            "yum": ["tesseract"],
            "pacman": ["tesseract"],
            "zypper": ["tesseract"],
            "winget": ["UB-Mannheim.TesseractOCR"],
            "choco": ["tesseract"],
        },
        notes="OCR engine used for screenshot and PDF extraction.",
    ),
    "ollama": SystemBinarySpec(
        binary="ollama",
        package_candidates={
            "brew": ["ollama"],
            "winget": ["Ollama.Ollama"],
            "choco": ["ollama"],
        },
        install_commands={
            "Linux": [["bash", "-lc", "curl -fsSL https://ollama.com/install.sh | sh"]],
        },
        notes="Local LLM runtime.",
    ),
    "xdotool": SystemBinarySpec(
        binary="xdotool",
        package_candidates={
            "brew": ["xdotool"],
            "apt-get": ["xdotool"],
            "dnf": ["xdotool"],
            "yum": ["xdotool"],
            "pacman": ["xdotool"],
            "zypper": ["xdotool"],
            "apk": ["xdotool"],
        },
        notes="X11 window query helper.",
    ),
    "xprop": SystemBinarySpec(
        binary="xprop",
        package_candidates={
            "brew": ["xprop"],
            "apt-get": ["x11-utils"],
            "dnf": ["xorg-x11-utils", "xorg-x11-apps", "xprop"],
            "yum": ["xorg-x11-utils", "xorg-x11-apps", "xprop"],
            "pacman": ["xorg-xprop", "xorg-x11-utils"],
            "zypper": ["xorg-xprop", "xorg-x11-utils"],
            "apk": ["xprop"],
        },
        notes="X11 root window property helper.",
    ),
    "wmctrl": SystemBinarySpec(
        binary="wmctrl",
        package_candidates={
            "brew": ["wmctrl"],
            "apt-get": ["wmctrl"],
            "dnf": ["wmctrl"],
            "yum": ["wmctrl"],
            "pacman": ["wmctrl"],
            "zypper": ["wmctrl"],
            "apk": ["wmctrl"],
        },
        notes="X11 window manager helper.",
    ),
    "xdg-open": SystemBinarySpec(
        binary="xdg-open",
        aliases=["gio"],
        package_candidates={
            "brew": ["xdg-utils"],
            "apt-get": ["xdg-utils"],
            "dnf": ["xdg-utils"],
            "yum": ["xdg-utils"],
            "pacman": ["xdg-utils"],
            "zypper": ["xdg-utils"],
            "apk": ["xdg-utils"],
        },
        notes="Desktop file opener / browser launcher.",
    ),
    "xclip": SystemBinarySpec(
        binary="xclip",
        package_candidates={
            "brew": ["xclip"],
            "apt-get": ["xclip"],
            "dnf": ["xclip"],
            "yum": ["xclip"],
            "pacman": ["xclip"],
            "zypper": ["xclip"],
            "apk": ["xclip"],
        },
        notes="X11 clipboard helper.",
    ),
    "xsel": SystemBinarySpec(
        binary="xsel",
        package_candidates={
            "brew": ["xsel"],
            "apt-get": ["xsel"],
            "dnf": ["xsel"],
            "yum": ["xsel"],
            "pacman": ["xsel"],
            "zypper": ["xsel"],
            "apk": ["xsel"],
        },
        notes="X11 clipboard helper.",
    ),
    "scrot": SystemBinarySpec(
        binary="scrot",
        package_candidates={
            "brew": ["scrot"],
            "apt-get": ["scrot"],
            "dnf": ["scrot"],
            "yum": ["scrot"],
            "pacman": ["scrot"],
            "zypper": ["scrot"],
            "apk": ["scrot"],
        },
        notes="Linux screenshot helper.",
    ),
    "gnome-screenshot": SystemBinarySpec(
        binary="gnome-screenshot",
        package_candidates={
            "brew": ["gnome-screenshot"],
            "apt-get": ["gnome-screenshot"],
            "dnf": ["gnome-screenshot"],
            "yum": ["gnome-screenshot"],
            "pacman": ["gnome-screenshot"],
            "zypper": ["gnome-screenshot"],
        },
        notes="GNOME screenshot helper.",
    ),
    "cliclick": SystemBinarySpec(
        binary="cliclick",
        package_candidates={
            "brew": ["cliclick"],
        },
        notes="macOS mouse/keyboard helper.",
    ),
}

SYSTEM_BINARY_ALIASES: dict[str, str] = {
    "ffprobe": "ffmpeg",
    "ffplay": "ffmpeg",
    "open": "xdg-open",
}


class SystemPackageRuntimeResolver:
    def __init__(self) -> None:
        self.enabled = bool(_config_get("dependency_runtime.system.enabled", True))
        self.auto_install = bool(_config_get("dependency_runtime.system.auto_install", True))
        self.audit_path = Path(
            str(_config_get("dependency_runtime.system.audit_path", str(_path_home(".elyan", "logs", "system_dependency_runtime.jsonl"))) or "")
        ).expanduser()
        self.state_path = Path(
            str(_config_get("dependency_runtime.system.state_path", str(_path_home(".elyan", "logs", "system_dependency_runtime_state.json"))) or "")
        ).expanduser()
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state: dict[str, SystemDependencyInstallRecord] = {}
        self._lock_guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._load_state()

    @staticmethod
    def _lock_key(binary: str) -> str:
        return _normalize(binary)

    def _get_lock(self, key: str) -> threading.Lock:
        with self._lock_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def _catalog_key(self, binary: str) -> str:
        key = _normalize(binary)
        return SYSTEM_BINARY_ALIASES.get(key, key)

    def resolve_spec(self, binary: str) -> SystemBinarySpec | None:
        key = self._catalog_key(binary)
        spec = SYSTEM_BINARY_CATALOG.get(key)
        if spec is not None:
            return spec
        for item in SYSTEM_BINARY_CATALOG.values():
            if key in {_normalize(name) for name in item.binary_names}:
                return item
        return None

    def _is_available(self, spec: SystemBinarySpec) -> bool:
        for name in spec.binary_names:
            if shutil.which(name):
                return True
        return False

    def _is_trusted(self, spec: SystemBinarySpec) -> bool:
        source = _normalize(spec.source)
        trust = _normalize(spec.trust_level)
        if source and source not in {"system", "builtin", "local", "marketplace"}:
            return False
        return trust in SYSTEM_TRUST_LEVELS

    def _record(self, record: SystemDependencyInstallRecord) -> None:
        key = _normalize(record.binary or record.package or record.install_command)
        if not key:
            return
        self._state[key] = record
        self._save_state()
        try:
            row = dict(record.to_dict())
            row["recorded_at"] = _now_iso()
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.debug("System dependency audit write failed: %s", exc)

    def _load_state(self) -> None:
        loaded: dict[str, SystemDependencyInstallRecord] = {}
        try:
            if self.state_path.exists():
                payload = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    for key, raw in payload.items():
                        if not isinstance(raw, dict):
                            continue
                        try:
                            loaded[_normalize(str(key))] = SystemDependencyInstallRecord(**raw)
                        except Exception:
                            continue
        except Exception as exc:
            logger.debug("System dependency state load failed: %s", exc)
        if loaded:
            self._state.update(loaded)

    def _save_state(self) -> None:
        try:
            payload = {key: record.to_dict() for key, record in self._state.items()}
            self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("System dependency state write failed: %s", exc)

    def _manager_order(self) -> list[str]:
        system = _system_name()
        order = list(PACKAGE_MANAGER_ORDER.get(system, []))
        return [name for name in order if shutil.which(name)]

    def _build_install_plans(self, spec: SystemBinarySpec) -> list[tuple[str, list[str]]]:
        plans: list[tuple[str, list[str]]] = []
        system = _system_name()

        for command in spec.install_commands.get(system, []):
            if command:
                plans.append(("command", [str(part) for part in command if str(part).strip()]))

        managers = self._manager_order()
        for manager in managers:
            candidates = spec.package_candidates.get(manager, [])
            for package in candidates:
                cmd_plan = _manager_cmd(manager, package)
                for cmd in cmd_plan:
                    if cmd:
                        plans.append((manager, [str(part) for part in cmd if str(part).strip()]))
        return plans

    def _maybe_prefix(self, manager: str, cmd: list[str]) -> list[str]:
        if os.name == "nt":
            return list(cmd)
        manager = _normalize(manager)
        if manager in ROOT_REQUIRED_MANAGERS and not _is_root():
            prefix = _sudo_prefix()
            if prefix:
                return [*prefix, *cmd]
            return []
        return list(cmd)

    def _run_command(self, cmd: list[str]) -> tuple[bool, str]:
        if not cmd:
            return False, "empty_command"
        env = os.environ.copy()
        env.setdefault("DEBIAN_FRONTEND", "noninteractive")
        env.setdefault("PIP_NO_INPUT", "1")
        env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            cwd=str(Path.home()),
            env=env,
        )
        output = "\n".join(part for part in [proc.stdout, proc.stderr] if part).strip()
        if proc.returncode != 0:
            return False, output or f"installer_failed:{proc.returncode}"
        return True, output

    def inspect_binary(self, binary: str, *, allow_install: bool = False) -> dict[str, Any]:
        spec = self.resolve_spec(binary)
        available = bool(spec and self._is_available(spec))
        if not spec:
            return {
                "available": available,
                "installable": False,
                "binary": binary,
                "platform": _system_name(),
                "blocked": True,
                "blocked_reason": "unsupported_binary",
                "install_hint": "",
                "manager_candidates": [],
                "package_candidates": {},
                "service_hint": "",
            }
        managers = self._manager_order()
        installable = bool(managers or spec.install_commands.get(_system_name()))
        return {
            "available": available,
            "installable": installable,
            "binary": spec.binary,
            "aliases": list(spec.aliases),
            "platform": _system_name(),
            "blocked": False,
            "blocked_reason": "" if installable else "no_supported_installer",
            "install_hint": self.get_install_hint(binary),
            "manager_candidates": managers,
            "package_candidates": dict(spec.package_candidates),
            "service_hint": "",
        }

    def get_install_hint(self, binary: str) -> str:
        spec = self.resolve_spec(binary)
        if not spec:
            return f"{binary} için bilinen otomatik kurulum yok."
        system = _system_name()
        commands = spec.install_commands.get(system, [])
        if commands:
            return " veya ".join(" ".join(shlex.quote(part) for part in command) for command in commands)
        hints: list[str] = []
        for manager, candidates in spec.package_candidates.items():
            if not candidates:
                continue
            hint = f"{manager}: {candidates[0]}"
            hints.append(hint)
        return " | ".join(hints)

    def _build_install_record(
        self,
        spec: SystemBinarySpec,
        *,
        status: str,
        reason: str,
        manager: str = "",
        package: str = "",
        command_used: str = "",
        installed: bool = False,
        attempts: int = 0,
        output: str = "",
        started_at: str = "",
    ) -> SystemDependencyInstallRecord:
        return SystemDependencyInstallRecord(
            binary=spec.binary,
            aliases=list(spec.aliases),
            package=package,
            manager=manager,
            install_command=command_used,
            source=spec.source,
            trust_level=spec.trust_level,
            status=status,
            reason=reason,
            retryable=status in {"missing", "failed", "needs_input"},
            installed=installed,
            started_at=started_at or _now_iso(),
            finished_at=_now_iso(),
            duration_ms=0,
            attempts=attempts,
            output=output[:4000],
            platform=_system_name(),
            notes=spec.notes,
        )

    def ensure_binary(
        self,
        binary: str,
        *,
        allow_install: bool = True,
        skill_name: str = "",
        tool_name: str = "",
        source: str = "system",
        trust_level: str = "trusted",
    ) -> SystemDependencyInstallRecord:
        del skill_name, tool_name  # compatibility arguments
        start = time.perf_counter()
        started_at = _now_iso()
        spec = self.resolve_spec(binary)
        if not self.enabled:
            record = SystemDependencyInstallRecord(
                binary=binary,
                status="blocked",
                reason="system_dependency_runtime_disabled",
                retryable=False,
                installed=False,
                started_at=started_at,
                finished_at=_now_iso(),
                duration_ms=int((time.perf_counter() - start) * 1000),
                attempts=0,
                platform=_system_name(),
            )
            self._record(record)
            return record

        if spec is None:
            record = SystemDependencyInstallRecord(
                binary=binary,
                status="blocked",
                reason="unsupported_binary",
                retryable=False,
                installed=False,
                started_at=started_at,
                finished_at=_now_iso(),
                duration_ms=int((time.perf_counter() - start) * 1000),
                attempts=0,
                platform=_system_name(),
            )
            self._record(record)
            return record

        if self._is_available(spec):
            record = self._build_install_record(
                spec,
                status="ready",
                reason="already_available",
                installed=False,
                started_at=started_at,
            )
            record.duration_ms = int((time.perf_counter() - start) * 1000)
            self._record(record)
            return record

        if not allow_install or not self.auto_install:
            record = self._build_install_record(
                spec,
                status="missing",
                reason="install_not_allowed",
                started_at=started_at,
            )
            record.duration_ms = int((time.perf_counter() - start) * 1000)
            self._record(record)
            return record

        if not self._is_trusted(spec):
            record = self._build_install_record(
                spec,
                status="blocked",
                reason="untrusted_or_direct_source",
                started_at=started_at,
            )
            record.duration_ms = int((time.perf_counter() - start) * 1000)
            self._record(record)
            return record

        plans = self._build_install_plans(spec)
        if not plans:
            record = self._build_install_record(
                spec,
                status="blocked",
                reason="no_supported_installer",
                started_at=started_at,
            )
            record.duration_ms = int((time.perf_counter() - start) * 1000)
            self._record(record)
            return record

        install_reason = "install_started"
        last_output = ""
        attempts = 0
        for manager, raw_cmd in plans:
            attempts += 1
            cmd = self._maybe_prefix(manager, raw_cmd)
            if not cmd:
                last_output = "sudo_required"
                continue
            installing_record = self._build_install_record(
                spec,
                status="installing",
                reason=install_reason,
                manager=manager,
                package=cmd[-1] if cmd else "",
                command_used=" ".join(shlex.quote(part) for part in cmd),
                started_at=started_at,
                attempts=attempts,
            )
            installing_record.duration_ms = int((time.perf_counter() - start) * 1000)
            self._record(installing_record)
            ok, output = self._run_command(cmd)
            last_output = output
            if not ok:
                continue
            if self._is_available(spec):
                record = self._build_install_record(
                    spec,
                    status="installed",
                    reason="installed",
                    manager=manager,
                    package=cmd[-1] if cmd else "",
                    command_used=" ".join(shlex.quote(part) for part in cmd),
                    installed=True,
                    started_at=started_at,
                    attempts=attempts,
                    output=output,
                )
                record.duration_ms = int((time.perf_counter() - start) * 1000)
                self._record(record)
                return record
            last_output = output or "binary_still_missing_after_install"

        if last_output == "sudo_required":
            record = self._build_install_record(
                spec,
                status="needs_input",
                reason="admin_required_for_system_install",
                started_at=started_at,
                attempts=attempts,
            )
        else:
            record = self._build_install_record(
                spec,
                status="failed",
                reason=(last_output or "install_failed")[:1000],
                started_at=started_at,
                attempts=attempts,
                output=last_output,
            )
        record.duration_ms = int((time.perf_counter() - start) * 1000)
        self._record(record)
        return record

    async def ensure_binary_async(self, *args, **kwargs) -> SystemDependencyInstallRecord:
        import asyncio

        return await asyncio.to_thread(self.ensure_binary, *args, **kwargs)

    def ensure_binaries(self, binaries: Iterable[str], *, allow_install: bool = True) -> list[SystemDependencyInstallRecord]:
        records: list[SystemDependencyInstallRecord] = []
        for item in list(binaries or []):
            records.append(self.ensure_binary(item, allow_install=allow_install))
        return records

    async def ensure_binaries_async(self, binaries: Iterable[str], *, allow_install: bool = True) -> list[SystemDependencyInstallRecord]:
        import asyncio

        return await asyncio.to_thread(self.ensure_binaries, binaries, allow_install=allow_install)

    def detect_missing_from_error(self, error_text: str) -> list[str]:
        text = str(error_text or "").strip().lower()
        if not text:
            return []
        hits: list[str] = []
        patterns = {
            "ffmpeg": [r"\bffmpeg\b", r"\bffprobe\b", r"ffmpeg not found", r"command not found: ffmpeg"],
            "tesseract": [r"\btesseract\b", r"ocr_unavailable", r"tesseract not found"],
            "ollama": [r"\bollama\b", r"ollama not found", r"command not found: ollama"],
            "xdotool": [r"\bxdotool\b", r"command not found: xdotool"],
            "xprop": [r"\bxprop\b", r"command not found: xprop"],
            "wmctrl": [r"\bwmctrl\b", r"command not found: wmctrl"],
            "xdg-open": [r"\bxdg-open\b", r"command not found: xdg-open", r"\bxdg-utils\b"],
            "xclip": [r"\bxclip\b", r"command not found: xclip"],
            "xsel": [r"\bxsel\b", r"command not found: xsel"],
            "scrot": [r"\bscrot\b", r"command not found: scrot"],
            "gnome-screenshot": [r"\bgnome-screenshot\b", r"command not found: gnome-screenshot"],
            "cliclick": [r"\bcliclick\b", r"command not found: cliclick"],
        }
        for binary, items in patterns.items():
            if any(re.search(pattern, text) for pattern in items):
                hits.append(binary)
        return list(dict.fromkeys(hits))

    def ensure_from_error(self, error_text: str, *, allow_install: bool = True) -> list[SystemDependencyInstallRecord]:
        records: list[SystemDependencyInstallRecord] = []
        for binary in self.detect_missing_from_error(error_text):
            records.append(self.ensure_binary(binary, allow_install=allow_install))
        return records

    async def ensure_from_error_async(self, error_text: str, *, allow_install: bool = True) -> list[SystemDependencyInstallRecord]:
        import asyncio

        return await asyncio.to_thread(self.ensure_from_error, error_text, allow_install=allow_install)

    def snapshot(self) -> dict[str, Any]:
        rows = [record.to_dict() for record in self._state.values()]
        rows.sort(key=lambda item: (str(item.get("status") or ""), str(item.get("binary") or "")))
        counts: dict[str, int] = {}
        for row in rows:
            status = str(row.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        return {
            "enabled": bool(self.enabled),
            "auto_install": bool(self.auto_install),
            "platform": _system_name(),
            "status_counts": counts,
            "ready_binaries": [row for row in rows if row.get("status") == "ready"],
            "installing_binaries": [row for row in rows if row.get("status") == "installing"],
            "installed_binaries": [row for row in rows if row.get("status") == "installed"],
            "blocked_binaries": [row for row in rows if row.get("status") == "blocked"],
            "failed_binaries": [row for row in rows if row.get("status") == "failed"],
            "missing_binaries": [row for row in rows if row.get("status") == "missing"],
            "recent_records": rows[-20:],
            "audit_path": str(self.audit_path),
            "state_path": str(self.state_path),
        }


_system_runtime_singleton: SystemPackageRuntimeResolver | None = None


def get_system_dependency_runtime() -> SystemPackageRuntimeResolver:
    global _system_runtime_singleton
    if _system_runtime_singleton is None:
        _system_runtime_singleton = SystemPackageRuntimeResolver()
    return _system_runtime_singleton
