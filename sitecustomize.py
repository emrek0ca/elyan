from __future__ import annotations

import builtins
import importlib
import importlib.machinery
import json
import os
import shlex
import shutil
import site
import subprocess
import sys
import sysconfig
import threading
import time
import venv
from pathlib import Path
from typing import Any


_ORIGINAL_IMPORT = builtins.__import__
_LOCK = threading.Lock()
_IN_PROGRESS: set[str] = set()
_BOOTSTRAPPED = False

_DEFAULT_MANAGED_VENV_ROOT = Path.home() / ".elyan" / "venvs" / "runtime"
_DEFAULT_AUDIT_PATH = Path.home() / ".elyan" / "logs" / "dependency_runtime.jsonl"
_DEFAULT_STATE_PATH = Path.home() / ".elyan" / "logs" / "dependency_runtime_state.json"

_FALLBACK_MODULE_ALIASES: dict[str, dict[str, Any]] = {
    "aiohttp": {"package": "aiohttp", "modules": ["aiohttp"]},
    "apscheduler": {"package": "apscheduler", "modules": ["apscheduler"]},
    "bs4": {"package": "beautifulsoup4", "modules": ["bs4"]},
    "beautifulsoup4": {"package": "beautifulsoup4", "modules": ["bs4"]},
    "click": {"package": "click", "modules": ["click"]},
    "croniter": {"package": "croniter", "modules": ["croniter"]},
    "cryptography": {"package": "cryptography", "modules": ["cryptography"]},
    "discord": {"package": "discord.py", "modules": ["discord"]},
    "dotenv": {"package": "python-dotenv", "modules": ["dotenv"]},
    "docx": {"package": "python-docx", "modules": ["docx"]},
    "docxcompose": {"package": "docxcompose", "modules": ["docxcompose"]},
    "feedparser": {"package": "feedparser", "modules": ["feedparser"]},
    "faiss": {"package": "faiss-cpu", "modules": ["faiss"]},
    "fitz": {"package": "pymupdf", "modules": ["fitz"]},
    "httpx": {"package": "httpx", "modules": ["httpx"]},
    "json5": {"package": "json5", "modules": ["json5"]},
    "jsonschema": {"package": "jsonschema", "modules": ["jsonschema"]},
    "lancedb": {"package": "lancedb", "modules": ["lancedb"]},
    "markdown": {"package": "Markdown", "modules": ["markdown"]},
    "matrix-nio": {"package": "matrix-nio", "modules": ["nio"]},
    "nio": {"package": "matrix-nio", "modules": ["nio"]},
    "mss": {"package": "mss", "modules": ["mss"]},
    "matplotlib": {"package": "matplotlib", "modules": ["matplotlib"]},
    "numpy": {"package": "numpy", "modules": ["numpy"]},
    "openai": {"package": "openai", "modules": ["openai"]},
    "openpyxl": {"package": "openpyxl", "modules": ["openpyxl"]},
    "pandas": {"package": "pandas", "modules": ["pandas"]},
    "pdf2image": {"package": "pdf2image", "modules": ["pdf2image"]},
    "pdfplumber": {"package": "pdfplumber", "modules": ["pdfplumber"]},
    "playwright": {"package": "playwright", "modules": ["playwright"]},
    "pydantic": {"package": "pydantic", "modules": ["pydantic"]},
    "pydub": {"package": "pydub", "modules": ["pydub"]},
    "pyaudio": {"package": "pyaudio", "modules": ["pyaudio"]},
    "pyautogui": {"package": "pyautogui", "modules": ["pyautogui"]},
    "pil": {"package": "Pillow", "modules": ["PIL"]},
    "pillow": {"package": "Pillow", "modules": ["PIL"]},
    "pyperclip": {"package": "pyperclip", "modules": ["pyperclip"]},
    "pymupdf": {"package": "pymupdf", "modules": ["fitz"]},
    "pypdf": {"package": "pypdf", "modules": ["pypdf"]},
    "pypdf2": {"package": "PyPDF2", "modules": ["PyPDF2"]},
    "psutil": {"package": "psutil", "modules": ["psutil"]},
    "cv2": {"package": "opencv-python", "modules": ["cv2"]},
    "pyqt5": {"package": "PyQt5", "modules": ["PyQt5"]},
    "pyqt6": {"package": "PyQt6", "modules": ["PyQt6"]},
    "pyttsx3": {"package": "pyttsx3", "modules": ["pyttsx3"]},
    "pywin32": {"package": "pywin32", "modules": ["win32gui", "win32process", "win32api"]},
    "pyatspi": {"package": "pyatspi", "modules": ["pyatspi"]},
    "pyside2": {"package": "PySide2", "modules": ["PySide2"]},
    "pyside6": {"package": "PySide6", "modules": ["PySide6"]},
    "pytesseract": {"package": "pytesseract", "modules": ["pytesseract"]},
    "python-docx": {"package": "python-docx", "modules": ["docx"]},
    "speech-recognition": {"package": "SpeechRecognition", "modules": ["speech_recognition"]},
    "uiautomation": {"package": "uiautomation", "modules": ["uiautomation"]},
    "qrcode": {"package": "qrcode", "modules": ["qrcode"]},
    "reportlab": {"package": "reportlab", "modules": ["reportlab"]},
    "requests": {"package": "requests", "modules": ["requests"]},
    "rumps": {"package": "rumps", "modules": ["rumps"]},
    "schedule": {"package": "schedule", "modules": ["schedule"]},
    "sentence-transformers": {"package": "sentence-transformers", "modules": ["sentence_transformers"]},
    "sentence_transformers": {"package": "sentence-transformers", "modules": ["sentence_transformers"]},
    "slack-bolt": {"package": "slack-bolt", "modules": ["slack_bolt"]},
    "slack_bolt": {"package": "slack-bolt", "modules": ["slack_bolt"]},
    "sounddevice": {"package": "sounddevice", "modules": ["sounddevice"]},
    "SpeechRecognition": {"package": "SpeechRecognition", "modules": ["speech_recognition"]},
    "speech_recognition": {"package": "SpeechRecognition", "modules": ["speech_recognition"]},
    "tabulate": {"package": "tabulate", "modules": ["tabulate"]},
    "telegram": {"package": "python-telegram-bot", "modules": ["telegram"]},
    "torch": {"package": "torch", "modules": ["torch"]},
    "transformers": {"package": "transformers", "modules": ["transformers"]},
    "trl": {"package": "trl", "modules": ["trl"]},
    "watchdog": {"package": "watchdog", "modules": ["watchdog"]},
    "whisper": {"package": "openai-whisper", "modules": ["whisper"]},
    "openai-whisper": {"package": "openai-whisper", "modules": ["whisper"]},
    "win32api": {"package": "pywin32", "modules": ["win32gui", "win32process", "win32api"]},
    "win32gui": {"package": "pywin32", "modules": ["win32gui", "win32process", "win32api"]},
    "win32process": {"package": "pywin32", "modules": ["win32gui", "win32process", "win32api"]},
}


def _cfg_path() -> Path:
    return Path.home() / ".elyan" / "elyan.json"


def _load_dependency_policy() -> dict[str, Any]:
    policy = {
        "enabled": True,
        "auto_install": True,
        "managed_venv_root": str(_DEFAULT_MANAGED_VENV_ROOT),
        "audit_path": str(_DEFAULT_AUDIT_PATH),
        "state_path": str(_DEFAULT_STATE_PATH),
        "trusted_sources": ["builtin", "marketplace", "pypi", "local"],
        "blocked_schemes": ["git+", "http://", "https://", "file:", "ssh://", "hg+", "svn+"],
    }
    cfg_path = _cfg_path()
    if not cfg_path.exists():
        return policy
    try:
        payload = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return policy
    raw = payload.get("dependency_runtime") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return policy
    policy["enabled"] = bool(raw.get("enabled", policy["enabled"]))
    policy["auto_install"] = bool(raw.get("auto_install", policy["auto_install"]))
    policy["managed_venv_root"] = str(raw.get("managed_venv_root") or policy["managed_venv_root"]).strip() or policy["managed_venv_root"]
    policy["audit_path"] = str(raw.get("audit_path") or policy["audit_path"]).strip() or policy["audit_path"]
    policy["state_path"] = str(raw.get("state_path") or policy["state_path"]).strip() or policy["state_path"]
    trusted_sources = raw.get("trusted_sources")
    if isinstance(trusted_sources, list) and trusted_sources:
        policy["trusted_sources"] = [str(item).strip() for item in trusted_sources if str(item).strip()]
    blocked_schemes = raw.get("blocked_schemes")
    if isinstance(blocked_schemes, list) and blocked_schemes:
        policy["blocked_schemes"] = [str(item).strip() for item in blocked_schemes if str(item).strip()]
    return policy


def _managed_root(policy: dict[str, Any]) -> Path:
    raw = str(policy.get("managed_venv_root") or "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_MANAGED_VENV_ROOT


def _managed_venv(policy: dict[str, Any]) -> Path:
    root = _managed_root(policy)
    return root / "venv"


def _managed_python(policy: dict[str, Any]) -> Path:
    venv_path = _managed_venv(policy)
    if sys.platform == "win32":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def _site_paths(policy: dict[str, Any]) -> list[Path]:
    python_path = _managed_python(policy)
    if not python_path.exists():
        return []
    venv_path = _managed_venv(policy)
    candidates: list[Path] = []
    try:
        purelib = sysconfig.get_path("purelib", vars={"base": str(venv_path), "platbase": str(venv_path)})
        platlib = sysconfig.get_path("platlib", vars={"base": str(venv_path), "platbase": str(venv_path)})
        for raw in (purelib, platlib):
            if raw:
                path = Path(raw)
                if path not in candidates:
                    candidates.append(path)
    except Exception:
        pass
    return candidates


def _bootstrap_site_paths(policy: dict[str, Any]) -> None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    for path in _site_paths(policy):
        if path.exists():
            site.addsitedir(str(path))
    importlib.invalidate_caches()
    _BOOTSTRAPPED = True


def _module_spec_available(module_name: str) -> bool:
    if not module_name:
        return False
    try:
        return importlib.machinery.PathFinder.find_spec(module_name) is not None
    except Exception:
        return False


def _alias_for(module_name: str) -> dict[str, Any]:
    key = str(module_name or "").strip().lower().replace("_", "-")
    return dict(_FALLBACK_MODULE_ALIASES.get(key) or {})


def _normalize_install_spec(module_name: str, package_name: str | None = None) -> tuple[str, str, list[str]]:
    mapped = _alias_for(module_name)
    package = str(package_name or mapped.get("package") or module_name).strip()
    modules = [str(item).strip() for item in (mapped.get("modules") or []) if str(item).strip()]
    if not modules and package:
        modules = [package.replace("-", "_")]
    install_spec = str(mapped.get("install_spec") or package or module_name).strip()
    return package or module_name, install_spec, modules


def _is_direct_source(spec: str, policy: dict[str, Any]) -> bool:
    raw = str(spec or "").strip().lower()
    blocked = tuple(policy.get("blocked_schemes") or ())
    return any(raw.startswith(prefix) for prefix in blocked) or raw.startswith("-e ") or "://" in raw


def _write_jsonl(path: Path, record: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _update_state(path: Path, record: dict[str, Any]) -> None:
    try:
        payload: dict[str, Any] = {}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        key = str(record.get("package") or record.get("install_spec") or "").strip().lower()
        if key:
            payload[key] = record
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _installer_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PIP_NO_INPUT", "1")
    env.setdefault("PYTHONNOUSERSITE", "1")
    return env


def _ensure_venv(policy: dict[str, Any]) -> None:
    python_path = _managed_python(policy)
    if python_path.exists():
        return
    root = _managed_root(policy)
    root.mkdir(parents=True, exist_ok=True)
    builder = venv.EnvBuilder(with_pip=True, clear=False, symlinks=True, upgrade_deps=False)
    builder.create(_managed_venv(policy))


def _install_via_subprocess(module_name: str, policy: dict[str, Any]) -> dict[str, Any]:
    package, install_spec, modules = _normalize_install_spec(module_name)
    if _is_direct_source(install_spec, policy):
        return {
            "package": package,
            "modules": modules,
            "install_spec": install_spec,
            "source": "pypi",
            "trust_level": "trusted",
            "status": "blocked",
            "reason": "untrusted_or_direct_source",
            "retryable": False,
            "installed": False,
        }

    _ensure_venv(policy)
    python_path = _managed_python(policy)
    if not python_path.exists():
        return {
            "package": package,
            "modules": modules,
            "install_spec": install_spec,
            "source": "pypi",
            "trust_level": "trusted",
            "status": "failed",
            "reason": "managed_venv_unavailable",
            "retryable": True,
            "installed": False,
        }

    cmd: list[str]
    if shutil.which("uv"):
        cmd = ["uv", "pip", "install", "--python", str(python_path), install_spec]
        installer = "uv"
    else:
        cmd = [str(python_path), "-m", "pip", "install", install_spec]
        installer = "pip"

    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_managed_root(policy)),
        env=_installer_env(),
    )
    output = "\n".join(part for part in [proc.stdout, proc.stderr] if part).strip()
    status = "installed" if proc.returncode == 0 else "failed"
    record = {
        "package": package,
        "modules": modules,
        "install_spec": install_spec,
        "source": "pypi",
        "trust_level": "trusted",
        "installer": installer,
        "status": status,
        "reason": "installed" if proc.returncode == 0 else (output[:1000] or f"installer_failed:{proc.returncode}"),
        "retryable": status != "blocked",
        "installed": proc.returncode == 0,
        "started_at": "",
        "finished_at": "",
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "attempts": 1,
        "venv_path": str(_managed_venv(policy)),
        "python_path": str(python_path),
        "source_detail": "sitecustomize",
    }
    _write_jsonl(Path(str(policy.get("audit_path") or _DEFAULT_AUDIT_PATH)), record)
    _update_state(Path(str(policy.get("state_path") or _DEFAULT_STATE_PATH)), record)
    return record


def _attempt_auto_install(module_name: str) -> None:
    policy = _load_dependency_policy()
    if not policy.get("enabled", True) or not policy.get("auto_install", True):
        return

    package_key = str(module_name or "").strip()
    if not package_key:
        return

    if _module_spec_available(package_key):
        _bootstrap_site_paths(policy)
        return

    with _LOCK:
        if package_key in _IN_PROGRESS:
            return
        _IN_PROGRESS.add(package_key)
    try:
        _bootstrap_site_paths(policy)
        record = _install_via_subprocess(package_key, policy)
        if str(record.get("status") or "").strip().lower() in {"installed", "ready"}:
            importlib.invalidate_caches()
            _bootstrap_site_paths(policy)
    finally:
        with _LOCK:
            _IN_PROGRESS.discard(package_key)


def _import_hook(name: str, globals=None, locals=None, fromlist=(), level=0):
    try:
        return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    except ModuleNotFoundError as exc:
        missing = str(getattr(exc, "name", "") or name or "").strip()
        if level != 0:
            raise
        module_name = missing.split(".")[0] if missing else str(name or "").split(".")[0]
        if not module_name:
            raise
        if not _alias_for(module_name):
            raise
        _attempt_auto_install(module_name)
        return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)


_bootstrap_site_paths(_load_dependency_policy())
builtins.__import__ = _import_hook
