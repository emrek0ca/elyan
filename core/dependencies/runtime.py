from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import site
import subprocess
import sys
import sysconfig
import threading
import time
import venv
from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Iterable, Optional

from config.elyan_config import elyan_config
from utils.logger import get_logger

logger = get_logger("dependency_runtime")


TRUSTED_SOURCES = {"builtin", "marketplace", "pypi", "local"}
AUTO_INSTALL_TRUST_LEVELS = {"trusted", "curated", "builtin", "local"}
BLOCKED_SCHEMES = ("git+", "http://", "https://", "file:", "ssh://", "hg+", "svn+")

MODULE_PACKAGE_ALIASES: dict[str, dict[str, Any]] = {
    "bs4": {"package": "beautifulsoup4", "modules": ["bs4"]},
    "beautifulsoup4": {"package": "beautifulsoup4", "modules": ["bs4"]},
    "click": {"package": "click", "modules": ["click"]},
    "psutil": {"package": "psutil", "modules": ["psutil"]},
    "aiohttp": {"package": "aiohttp", "modules": ["aiohttp"]},
    "apscheduler": {"package": "apscheduler", "modules": ["apscheduler"]},
    "croniter": {"package": "croniter", "modules": ["croniter"]},
    "feedparser": {"package": "feedparser", "modules": ["feedparser"]},
    "fitz": {"package": "pymupdf", "modules": ["fitz"]},
    "pymupdf": {"package": "pymupdf", "modules": ["fitz"]},
    "pdf2image": {"package": "pdf2image", "modules": ["pdf2image"]},
    "pdfplumber": {"package": "pdfplumber", "modules": ["pdfplumber"]},
    "cryptography": {"package": "cryptography", "modules": ["cryptography"]},
    "discord": {"package": "discord.py", "modules": ["discord"]},
    "json5": {"package": "json5", "modules": ["json5"]},
    "jsonschema": {"package": "jsonschema", "modules": ["jsonschema"]},
    "markdown": {"package": "Markdown", "modules": ["markdown"]},
    "matrix-nio": {"package": "matrix-nio", "modules": ["nio"]},
    "nio": {"package": "matrix-nio", "modules": ["nio"]},
    "openai": {"package": "openai", "modules": ["openai"]},
    "requests": {"package": "requests", "modules": ["requests"]},
    "pydantic": {"package": "pydantic", "modules": ["pydantic"]},
    "pydub": {"package": "pydub", "modules": ["pydub"]},
    "pyaudio": {"package": "pyaudio", "modules": ["pyaudio"]},
    "pytesseract": {"package": "pytesseract", "modules": ["pytesseract"]},
    "qrcode": {"package": "qrcode", "modules": ["qrcode"]},
    "reportlab": {"package": "reportlab", "modules": ["reportlab"]},
    "rumps": {"package": "rumps", "modules": ["rumps"]},
    "schedule": {"package": "schedule", "modules": ["schedule"]},
    "slack-bolt": {"package": "slack-bolt", "modules": ["slack_bolt"]},
    "slack_bolt": {"package": "slack-bolt", "modules": ["slack_bolt"]},
    "speech_recognition": {"package": "SpeechRecognition", "modules": ["speech_recognition"]},
    "speech-recognition": {"package": "SpeechRecognition", "modules": ["speech_recognition"]},
    "SpeechRecognition": {"package": "SpeechRecognition", "modules": ["speech_recognition"]},
    "tabulate": {"package": "tabulate", "modules": ["tabulate"]},
    "docx": {"package": "python-docx", "modules": ["docx"]},
    "python-docx": {"package": "python-docx", "modules": ["docx"]},
    "whisper": {"package": "openai-whisper", "modules": ["whisper"]},
    "openai-whisper": {"package": "openai-whisper", "modules": ["whisper"]},
    "playwright": {"package": "playwright", "modules": ["playwright"]},
    "openpyxl": {"package": "openpyxl", "modules": ["openpyxl"]},
    "pandas": {"package": "pandas", "modules": ["pandas"]},
    "pil": {"package": "Pillow", "modules": ["PIL"]},
    "pillow": {"package": "Pillow", "modules": ["PIL"]},
    "mss": {"package": "mss", "modules": ["mss"]},
    "numpy": {"package": "numpy", "modules": ["numpy"]},
    "cv2": {"package": "opencv-python", "modules": ["cv2"]},
    "opencv-python": {"package": "opencv-python", "modules": ["cv2"]},
    "pyautogui": {"package": "pyautogui", "modules": ["pyautogui"]},
    "pyttsx3": {"package": "pyttsx3", "modules": ["pyttsx3"]},
    "sounddevice": {"package": "sounddevice", "modules": ["sounddevice"]},
    "httpx": {"package": "httpx", "modules": ["httpx"]},
    "torch": {"package": "torch", "modules": ["torch"]},
    "torchaudio": {"package": "torchaudio", "modules": ["torchaudio"]},
    "transformers": {"package": "transformers", "modules": ["transformers"]},
    "peft": {"package": "peft", "modules": ["peft"]},
    "trl": {"package": "trl", "modules": ["trl"]},
    "sentence-transformers": {"package": "sentence-transformers", "modules": ["sentence_transformers"]},
    "faiss-cpu": {"package": "faiss-cpu", "modules": ["faiss"]},
    "lancedb": {"package": "lancedb", "modules": ["lancedb"]},
    "aiohttp": {"package": "aiohttp", "modules": ["aiohttp"]},
    "pypdf": {"package": "pypdf", "modules": ["pypdf"]},
    "pypdf2": {"package": "PyPDF2", "modules": ["PyPDF2"]},
    "pypdf2": {"package": "PyPDF2", "modules": ["PyPDF2"]},
    "docxcompose": {"package": "docxcompose", "modules": ["docxcompose"]},
    "telegram": {"package": "python-telegram-bot", "modules": ["telegram"]},
    "pyqt6": {"package": "PyQt6", "modules": ["PyQt6"]},
    "pyqt5": {"package": "PyQt5", "modules": ["PyQt5"]},
    "pyside6": {"package": "PySide6", "modules": ["PySide6"]},
    "pyside2": {"package": "PySide2", "modules": ["PySide2"]},
    "googleapiclient": {"package": "google-api-python-client", "modules": ["googleapiclient"]},
    "google-api-python-client": {"package": "google-api-python-client", "modules": ["googleapiclient"]},
    "google_auth_oauthlib": {"package": "google-auth-oauthlib", "modules": ["google_auth_oauthlib"]},
    "google-auth-oauthlib": {"package": "google-auth-oauthlib", "modules": ["google_auth_oauthlib"]},
    "google-auth": {"package": "google-auth", "modules": ["google.auth"]},
    "google-api-core": {"package": "google-api-core", "modules": ["google.api_core"]},
    "google-cloud-pubsub": {"package": "google-cloud-pubsub", "modules": ["google.cloud.pubsub"]},
    "httplib2": {"package": "httplib2", "modules": ["httplib2"]},
    "oauthlib": {"package": "oauthlib", "modules": ["oauthlib"]},
    "requests-oauthlib": {"package": "requests-oauthlib", "modules": ["requests_oauthlib"]},
    "playwright-stealth": {"package": "playwright-stealth", "modules": ["playwright_stealth"]},
    "keyring": {"package": "keyring", "modules": ["keyring"]},
    "pywin32": {"package": "pywin32", "modules": ["win32gui", "win32process", "win32api"]},
    "win32gui": {"package": "pywin32", "modules": ["win32gui", "win32process", "win32api"]},
    "win32process": {"package": "pywin32", "modules": ["win32gui", "win32process", "win32api"]},
    "win32api": {"package": "pywin32", "modules": ["win32gui", "win32process", "win32api"]},
    "uiautomation": {"package": "uiautomation", "modules": ["uiautomation"]},
    "matplotlib": {"package": "matplotlib", "modules": ["matplotlib"]},
}

TOOL_HINTS: dict[str, list[str]] = {
    "browser_open": ["playwright"],
    "browser_click": ["playwright"],
    "browser_type": ["playwright"],
    "browser_screenshot": ["playwright"],
    "browser_get_text": ["playwright"],
    "browser_scroll": ["playwright"],
    "browser_wait": ["playwright"],
    "browser_close": ["playwright"],
    "browser_status": ["playwright"],
    "scrape_page": ["playwright", "beautifulsoup4"],
    "scrape_links": ["playwright", "beautifulsoup4"],
    "scrape_table": ["playwright"],
    "web_search": ["aiohttp", "beautifulsoup4"],
    "fetch_page": ["aiohttp", "beautifulsoup4"],
    "extract_text": ["beautifulsoup4"],
    "read_word": ["python-docx"],
    "write_word": ["python-docx"],
    "edit_word_document": ["python-docx"],
    "merge_documents": ["python-docx", "docxcompose", "pypdf"],
    "merge_word_documents": ["python-docx", "docxcompose"],
    "merge_pdfs": ["pypdf"],
    "read_pdf": ["pypdf"],
    "get_pdf_info": ["pypdf"],
    "search_in_pdf": ["pypdf"],
    "write_excel": ["openpyxl", "pandas"],
    "read_excel": ["openpyxl", "pandas"],
    "analyze_excel_data": ["pandas", "openpyxl"],
    "analyze_image": ["Pillow"],
    "process_image_file": ["Pillow"],
    "verify_visual_quality": ["opencv-python", "numpy", "Pillow"],
    "transcribe_audio_file": ["openai-whisper"],
    "speak_text_local": ["pyttsx3"],
    "create_visual_asset_pack": ["Pillow", "mss", "numpy", "opencv-python"],
    "analyze_and_narrate_image": ["Pillow", "mss", "numpy", "opencv-python"],
    "get_multimodal_capability_report": ["openai-whisper", "pyttsx3", "Pillow", "mss", "numpy", "opencv-python"],
    "vision_automate": ["pyautogui"],
    "open_app": ["pyautogui"],
    "take_screenshot": ["pyautogui"],
    "capture_region": ["pyautogui"],
    "read_clipboard": ["pyautogui"],
    "write_clipboard": ["pyautogui"],
}

MODULE_RELOAD_HINTS: dict[str, list[str]] = {
    "beautifulsoup4": [
        "tools.browser_automation",
        "tools.web_tools.search_engine",
        "tools.web_tools.smart_fetch",
        "tools.web_tools.web_scraper",
    ],
    "python-docx": [
        "tools.document_tools.word_editor",
        "tools.document_tools.document_merger",
        "tools.document_generator.professional_document",
        "tools.research_tools.advanced_report",
    ],
    "playwright": [
        "tools.browser.manager",
        "tools.browser",
        "core.capabilities.browser.services",
        "core.capabilities.browser.runtime",
    ],
    "openpyxl": [
        "tools.office_tools.excel_tools",
    ],
    "pandas": [
        "tools.office_tools.excel_tools",
        "tools.data_tools",
    ],
    "openai-whisper": [
        "core.voice.speech_to_text",
        "tools.voice.whisper_stt",
        "tools.multimodal_tools",
    ],
    "pyttsx3": [
        "core.voice.text_to_speech",
        "tools.voice.local_tts",
        "tools.multimodal_tools",
    ],
    "Pillow": [
        "tools.vision_tools",
        "core.vision_dom.vision_browser",
    ],
    "pyautogui": [
        "core.vision_dom.coordinate_mapper",
        "core.vision_automation",
        "tools.system_tools",
    ],
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_text(value: str) -> str:
    return str(value or "").strip()


def _package_base_from_spec(spec: str) -> str:
    raw = str(spec or "").strip()
    if not raw:
        return ""
    if raw.startswith(BLOCKED_SCHEMES) or raw.startswith("-e ") or "://" in raw:
        return raw
    base = re.split(r"[<>=!~\[]", raw, maxsplit=1)[0].strip()
    return base


def _alias_for(identifier: str) -> dict[str, Any]:
    key = str(identifier or "").strip().lower().replace("_", "-")
    return dict(MODULE_PACKAGE_ALIASES.get(key) or {})


def _module_available(module_name: str) -> bool:
    if not module_name:
        return False
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


@dataclass
class DependencySpec:
    package: str
    modules: list[str] = field(default_factory=list)
    install_spec: str = ""
    source: str = "pypi"
    trust_level: str = "trusted"
    hashes: dict[str, str] = field(default_factory=dict)
    post_install: list[str] = field(default_factory=list)
    skill_name: str = ""
    tool_name: str = ""

    @classmethod
    def from_value(
        cls,
        value: Any,
        *,
        source: str = "pypi",
        trust_level: str = "trusted",
        hashes: dict[str, str] | None = None,
        post_install: Iterable[str] | None = None,
        skill_name: str = "",
        tool_name: str = "",
    ) -> "DependencySpec":
        if isinstance(value, DependencySpec):
            spec = value
            if source and spec.source == "pypi":
                spec.source = source
            if trust_level and spec.trust_level == "trusted":
                spec.trust_level = trust_level
            if hashes and not spec.hashes:
                spec.hashes = dict(hashes)
            if post_install and not spec.post_install:
                spec.post_install = [str(item).strip() for item in post_install if str(item).strip()]
            if skill_name and not spec.skill_name:
                spec.skill_name = skill_name
            if tool_name and not spec.tool_name:
                spec.tool_name = tool_name
            return spec

        if isinstance(value, dict):
            raw = dict(value)
            identifier = str(
                raw.get("package")
                or raw.get("name")
                or raw.get("module")
                or raw.get("install_spec")
                or ""
            ).strip()
            mapped = _alias_for(identifier)
            package = str(raw.get("package") or mapped.get("package") or identifier).strip()
            modules = [str(x).strip() for x in (raw.get("modules") or raw.get("module_names") or mapped.get("modules") or []) if str(x).strip()]
            if not modules and package:
                base = _package_base_from_spec(package)
                if base:
                    modules.append(base.replace("-", "_"))
            return cls(
                package=package or identifier,
                modules=modules,
                install_spec=str(raw.get("install_spec") or package or identifier).strip(),
                source=str(raw.get("source") or source or "pypi").strip().lower() or "pypi",
                trust_level=str(raw.get("trust_level") or trust_level or "trusted").strip().lower() or "trusted",
                hashes=dict(raw.get("hashes") or hashes or {}),
                post_install=[str(item).strip() for item in list(raw.get("post_install") or post_install or []) if str(item).strip()],
                skill_name=str(raw.get("skill_name") or skill_name or ""),
                tool_name=str(raw.get("tool_name") or tool_name or ""),
            )

        identifier = _normalize_text(value)
        mapped = _alias_for(identifier)
        package = str(mapped.get("package") or identifier).strip()
        modules = [str(x).strip() for x in (mapped.get("modules") or []) if str(x).strip()]
        if not modules and package:
            base = _package_base_from_spec(package)
            if base:
                modules.append(base.replace("-", "_"))
        install_spec = str(mapped.get("install_spec") or package or identifier).strip()
        return cls(
            package=package or identifier,
            modules=modules,
            install_spec=install_spec,
            source=str(source or "pypi").strip().lower() or "pypi",
            trust_level=str(trust_level or "trusted").strip().lower() or "trusted",
            hashes=dict(hashes or {}),
            post_install=[str(item).strip() for item in list(post_install or []) if str(item).strip()],
            skill_name=str(skill_name or ""),
            tool_name=str(tool_name or ""),
        )

    @property
    def key(self) -> str:
        return (self.package or self.install_spec or ",".join(self.modules)).strip().lower()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DependencyInstallRecord:
    package: str
    modules: list[str] = field(default_factory=list)
    install_spec: str = ""
    source: str = "pypi"
    trust_level: str = "trusted"
    hashes: dict[str, str] = field(default_factory=dict)
    post_install: list[str] = field(default_factory=list)
    skill_name: str = ""
    tool_name: str = ""
    installer: str = ""
    status: str = "missing"
    reason: str = ""
    retryable: bool = False
    installed: bool = False
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    attempts: int = 0
    venv_path: str = ""
    python_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PackageRuntimeResolver:
    def __init__(self) -> None:
        cfg_root = str(elyan_config.get("dependency_runtime.managed_venv_root", "") or "").strip()
        self.runtime_root = Path(cfg_root).expanduser() if cfg_root else (Path.home() / ".elyan" / "venvs" / "runtime")
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.managed_venv = self.runtime_root / "venv"
        audit_path = str(elyan_config.get("dependency_runtime.audit_path", "") or "").strip()
        self.audit_path = Path(audit_path).expanduser() if audit_path else (Path.home() / ".elyan" / "logs" / "dependency_runtime.jsonl")
        if not str(self.audit_path).strip():
            self.audit_path = Path.home() / ".elyan" / "logs" / "dependency_runtime.jsonl"
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        state_path = str(elyan_config.get("dependency_runtime.state_path", "") or "").strip()
        self.state_path = Path(state_path).expanduser() if state_path else self.audit_path.with_name("dependency_runtime_state.json")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_map: dict[str, threading.Lock] = {}
        self._lock_guard = threading.Lock()
        self._state: dict[str, DependencyInstallRecord] = {}
        self._installer = "uv" if shutil.which("uv") else "pip"
        self._site_paths_added = False
        self._load_persisted_state()

    # ── Paths ──────────────────────────────────────────────────────────────

    @property
    def managed_python(self) -> Path:
        if sys.platform == "win32":
            return self.managed_venv / "Scripts" / "python.exe"
        return self.managed_venv / "bin" / "python"

    def _site_packages_paths(self) -> list[Path]:
        if not self.managed_python.exists():
            return []
        paths: list[Path] = []
        try:
            purelib = sysconfig.get_path("purelib", vars={"base": str(self.managed_venv), "platbase": str(self.managed_venv)})
            platlib = sysconfig.get_path("platlib", vars={"base": str(self.managed_venv), "platbase": str(self.managed_venv)})
            for raw in (purelib, platlib):
                if raw:
                    path = Path(raw)
                    if path not in paths:
                        paths.append(path)
        except Exception:
            pass
        return paths

    def _ensure_site_paths(self) -> None:
        if self._site_paths_added:
            return
        for path in self._site_packages_paths():
            if path.exists():
                site.addsitedir(str(path))
        importlib.invalidate_caches()
        self._site_paths_added = True

    def _ensure_managed_venv(self) -> None:
        if self.managed_python.exists():
            self._ensure_site_paths()
            return
        logger.info(f"Creating managed dependency venv: {self.managed_venv}")
        builder = venv.EnvBuilder(with_pip=True, clear=False, symlinks=True, upgrade_deps=False)
        builder.create(self.managed_venv)
        self._ensure_site_paths()

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _lock_key(spec: DependencySpec) -> str:
        return spec.key or ",".join(spec.modules) or spec.install_spec or spec.package

    def _get_lock(self, key: str) -> threading.Lock:
        with self._lock_guard:
            lock = self._lock_map.get(key)
            if lock is None:
                lock = threading.Lock()
                self._lock_map[key] = lock
            return lock

    def _is_module_available(self, module_name: str) -> bool:
        try:
            return importlib.util.find_spec(module_name) is not None
        except Exception:
            return False

    def _is_spec_available(self, spec: DependencySpec) -> bool:
        candidates = list(spec.modules)
        if spec.package:
            candidates.append(spec.package)
            candidates.append(spec.package.replace("-", "_"))
        for module_name in candidates:
            if self._is_module_available(module_name):
                return True
        return False

    @staticmethod
    def _is_direct_source(spec: DependencySpec) -> bool:
        text = (spec.install_spec or spec.package or "").strip().lower()
        return any(text.startswith(prefix) for prefix in BLOCKED_SCHEMES) or text.startswith("-e ") or "://" in text

    def _is_trusted(self, spec: DependencySpec) -> bool:
        source = str(spec.source or "pypi").strip().lower() or "pypi"
        trust = str(spec.trust_level or "trusted").strip().lower() or "trusted"
        if source not in TRUSTED_SOURCES:
            return False
        if trust not in AUTO_INSTALL_TRUST_LEVELS:
            return False
        if self._is_direct_source(spec):
            return False
        return True

    def _write_audit(self, record: DependencyInstallRecord) -> None:
        try:
            row = dict(record.to_dict())
            row["recorded_at"] = _now_iso()
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.debug(f"Dependency audit write failed: {exc}")

    def _load_persisted_state(self) -> None:
        loaded: dict[str, DependencyInstallRecord] = {}
        try:
            if self.state_path.exists():
                payload = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    for key, raw in payload.items():
                        if not isinstance(raw, dict):
                            continue
                        try:
                            record = DependencyInstallRecord(**raw)
                            loaded[str(key).strip().lower()] = record
                        except Exception:
                            continue
        except Exception as exc:
            logger.debug(f"Dependency state load failed: {exc}")

        if not loaded and self.audit_path.exists():
            try:
                latest: dict[str, DependencyInstallRecord] = {}
                for line in self.audit_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(raw, dict):
                        continue
                    package = str(raw.get("package") or raw.get("install_spec") or "").strip().lower()
                    if not package:
                        continue
                    try:
                        latest[package] = DependencyInstallRecord(**{k: v for k, v in raw.items() if k in DependencyInstallRecord.__dataclass_fields__})
                    except Exception:
                        continue
                loaded.update(latest)
            except Exception as exc:
                logger.debug(f"Dependency audit replay skipped: {exc}")

        if loaded:
            self._state.update(loaded)
            self._save_persisted_state()

    def _save_persisted_state(self) -> None:
        try:
            payload = {key: record.to_dict() for key, record in self._state.items()}
            self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug(f"Dependency state write failed: {exc}")

    def _update_state(self, record: DependencyInstallRecord) -> None:
        key = str(record.package or record.install_spec or ",".join(record.modules)).strip().lower()
        if key:
            self._state[key] = record
            self._save_persisted_state()

    def _reload_modules(self, spec: DependencySpec) -> None:
        package_names = set()
        if spec.package:
            package_names.add(spec.package)
            package_names.add(spec.package.replace("-", "_"))
        for module_name in spec.modules:
            package_names.add(module_name)
        targets = set()
        for name in package_names:
            hint = MODULE_RELOAD_HINTS.get(str(name or "").strip().lower())
            if hint:
                targets.update(hint)
        for module_name in sorted(targets):
            try:
                if module_name in sys.modules:
                    importlib.reload(sys.modules[module_name])
            except Exception as exc:
                logger.debug(f"Module reload skipped for {module_name}: {exc}")

    def _run_installer(self, spec: DependencySpec) -> tuple[bool, str, str]:
        self._ensure_managed_venv()
        python = str(self.managed_python)
        if not self.managed_python.exists():
            return False, "managed_venv_unavailable", ""
        install_spec = str(spec.install_spec or spec.package or "").strip()
        if not install_spec:
            return False, "empty_install_spec", self._installer

        if self._installer == "uv":
            cmd = ["uv", "pip", "install", "--python", python, install_spec]
        else:
            cmd = [python, "-m", "pip", "install", install_spec]

        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
        env.setdefault("PIP_NO_INPUT", "1")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            cwd=str(self.runtime_root),
            env=env,
        )
        output = "\n".join(part for part in [proc.stdout, proc.stderr] if part).strip()
        if proc.returncode != 0:
            return False, output or f"installer_failed:{proc.returncode}", self._installer

        return True, output, self._installer

    def _run_post_install(self, spec: DependencySpec) -> tuple[bool, str]:
        if not spec.post_install:
            return True, ""
        if not self._is_trusted(spec):
            return False, "post_install_blocked_untrusted"
        for entry in spec.post_install:
            cmd = self._build_post_install_command(entry)
            if not cmd:
                continue
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
            env.setdefault("PIP_NO_INPUT", "1")
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=str(self.runtime_root),
                env=env,
            )
            output = "\n".join(part for part in [proc.stdout, proc.stderr] if part).strip()
            if proc.returncode != 0:
                return False, output or f"post_install_failed:{proc.returncode}"
        return True, ""

    def _build_post_install_command(self, entry: str) -> list[str]:
        raw = str(entry or "").strip()
        if not raw:
            return []
        parts = shlex.split(raw)
        if not parts:
            return []
        python = str(self.managed_python)
        if parts[0] in {"python", sys.executable, "python3"}:
            parts[0] = python
            return parts
        if parts[0] in {"playwright", "pip", "uv"}:
            return [python, "-m", *parts]
        if raw.startswith("python -m "):
            tokens = shlex.split(raw)
            if tokens:
                tokens[0] = python
                return tokens
        return parts

    def _inspect_spec(self, spec: DependencySpec) -> dict[str, Any]:
        return {
            "available": self._is_spec_available(spec),
            "package": spec.package,
            "modules": list(spec.modules),
            "install_spec": spec.install_spec or spec.package,
            "source": spec.source,
            "trust_level": spec.trust_level,
            "blocked": not self._is_trusted(spec),
            "blocked_reason": "untrusted_or_direct_source" if not self._is_trusted(spec) else "",
        }

    def _normalize_result(self, spec: DependencySpec, status: str, reason: str = "", *, installed: bool = False, attempts: int = 0) -> DependencyInstallRecord:
        return DependencyInstallRecord(
            package=spec.package,
            modules=list(spec.modules),
            install_spec=spec.install_spec or spec.package,
            source=spec.source,
            trust_level=spec.trust_level,
            hashes=dict(spec.hashes),
            post_install=list(spec.post_install),
            skill_name=spec.skill_name,
            tool_name=spec.tool_name,
            installer=self._installer,
            status=status,
            reason=reason,
            retryable=status in {"missing", "failed"},
            installed=installed,
            started_at=_now_iso(),
            finished_at=_now_iso(),
            duration_ms=0,
            attempts=attempts,
            venv_path=str(self.managed_venv),
            python_path=str(self.managed_python),
        )

    def _build_spec(
        self,
        module_or_package: str,
        *,
        install_spec: str = "",
        source: str = "pypi",
        trust_level: str = "trusted",
        hashes: dict[str, str] | None = None,
        post_install: Iterable[str] | None = None,
        skill_name: str = "",
        tool_name: str = "",
    ) -> DependencySpec:
        raw = _normalize_text(module_or_package)
        if not raw and install_spec:
            raw = _package_base_from_spec(install_spec)
        mapped = _alias_for(raw or install_spec)
        package = str(mapped.get("package") or _package_base_from_spec(install_spec) or raw).strip()
        modules = [str(x).strip() for x in (mapped.get("modules") or []) if str(x).strip()]
        if not modules and package:
            modules = [package.replace("-", "_")]
        final_install_spec = str(install_spec or mapped.get("install_spec") or package or raw).strip()
        if not final_install_spec:
            final_install_spec = package or raw
        return DependencySpec(
            package=package or raw,
            modules=modules,
            install_spec=final_install_spec,
            source=str(source or "pypi").strip().lower() or "pypi",
            trust_level=str(trust_level or "trusted").strip().lower() or "trusted",
            hashes=dict(hashes or {}),
            post_install=[str(item).strip() for item in list(post_install or []) if str(item).strip()],
            skill_name=str(skill_name or ""),
            tool_name=str(tool_name or ""),
        )

    # ── Public inspection helpers ──────────────────────────────────────────

    def inspect_dependency(self, module_or_package: str, *, install_spec: str = "", source: str = "pypi", trust_level: str = "trusted", hashes: dict[str, str] | None = None, post_install: Iterable[str] | None = None, skill_name: str = "", tool_name: str = "") -> dict[str, Any]:
        spec = self._build_spec(
            module_or_package,
            install_spec=install_spec,
            source=source,
            trust_level=trust_level,
            hashes=hashes,
            post_install=post_install,
            skill_name=skill_name,
            tool_name=tool_name,
        )
        return self._inspect_spec(spec)

    def resolve_skill_dependencies(self, skill_name: str, skill_manifest: dict[str, Any] | None = None) -> list[DependencySpec]:
        manifest = dict(skill_manifest or {})
        python_dependencies = list(manifest.get("python_dependencies") or [])
        if not python_dependencies and manifest.get("dependencies"):
            python_dependencies = list(manifest.get("dependencies") or [])
        post_install = list(manifest.get("post_install") or [])
        source = str(manifest.get("source") or "builtin").strip().lower() or "builtin"
        trust_level = str(manifest.get("trust_level") or ("trusted" if source in {"builtin", "curated", "marketplace"} else "local")).strip().lower() or "trusted"
        hashes = dict(manifest.get("hashes") or {}) if isinstance(manifest.get("hashes"), dict) else {}
        specs: list[DependencySpec] = []
        for item in python_dependencies:
            spec = DependencySpec.from_value(
                item,
                source=source,
                trust_level=trust_level,
                hashes=hashes,
                post_install=post_install,
                skill_name=skill_name,
            )
            specs.append(spec)
        return specs

    def resolve_tool_dependencies(self, tool_name: str, *, skill_name: str = "") -> list[DependencySpec]:
        specs = []
        for item in TOOL_HINTS.get(str(tool_name or "").strip(), []):
            spec = DependencySpec.from_value(item, skill_name=skill_name, tool_name=tool_name)
            specs.append(spec)
        return specs

    def detect_missing_from_error(self, error_text: str) -> list[str]:
        text = str(error_text or "").strip().lower()
        if not text:
            return []
        hits: list[str] = []
        patterns = {
            r"no module named ['\"]?bs4['\"]?": "bs4",
            r"beautifulsoup4": "beautifulsoup4",
            r"no module named ['\"]?docx['\"]?": "docx",
            r"python-docx": "python-docx",
            r"no module named ['\"]?whisper['\"]?": "whisper",
            r"openai-whisper": "openai-whisper",
            r"no module named ['\"]?pyttsx3['\"]?": "pyttsx3",
            r"playwright": "playwright",
            r"no module named ['\"]?openpyxl['\"]?": "openpyxl",
            r"no module named ['\"]?pandas['\"]?": "pandas",
            r"no module named ['\"]?pillow['\"]?": "pillow",
            r"no module named ['\"]?pil['\"]?": "pillow",
            r"no module named ['\"]?pyautogui['\"]?": "pyautogui",
            r"no module named ['\"]?mss['\"]?": "mss",
            r"no module named ['\"]?cv2['\"]?": "opencv-python",
            r"no module named ['\"]?numpy['\"]?": "numpy",
            r"no module named ['\"]?aiohttp['\"]?": "aiohttp",
            r"no module named ['\"]?httpx['\"]?": "httpx",
            r"no module named ['\"]?torch['\"]?": "torch",
            r"no module named ['\"]?torchaudio['\"]?": "torchaudio",
            r"no module named ['\"]?transformers['\"]?": "transformers",
            r"no module named ['\"]?peft['\"]?": "peft",
            r"no module named ['\"]?trl['\"]?": "trl",
            r"no module named ['\"]?pypdf['\"]?": "pypdf",
            r"no module named ['\"]?pypdf2['\"]?": "PyPDF2",
            r"no module named ['\"]?sounddevice['\"]?": "sounddevice",
            r"no module named ['\"]?telegram['\"]?": "python-telegram-bot",
        }
        for pattern, package in patterns.items():
            if re.search(pattern, text):
                hits.append(package)
        if "whisper not available" in text:
            hits.append("openai-whisper")
        if "pyttsx3 not installed" in text or "tts service ready değil" in text:
            hits.append("pyttsx3")
        if "pillow kurulu degil" in text or "pillow not installed" in text:
            hits.append("Pillow")
        if "openpyxl kurulu degil" in text:
            hits.append("openpyxl")
        if "torch" in text and "whisper" in text:
            hits.append("torch")
        return list(dict.fromkeys(hits))

    # ── Installation API ──────────────────────────────────────────────────

    def ensure_module(
        self,
        module_or_package: str,
        *,
        install_spec: str = "",
        source: str = "pypi",
        trust_level: str = "trusted",
        hashes: dict[str, str] | None = None,
        post_install: Iterable[str] | None = None,
        skill_name: str = "",
        tool_name: str = "",
        allow_install: bool = True,
    ) -> DependencyInstallRecord:
        spec = self._build_spec(
            module_or_package,
            install_spec=install_spec,
            source=source,
            trust_level=trust_level,
            hashes=hashes,
            post_install=post_install,
            skill_name=skill_name,
            tool_name=tool_name,
        )
        start = time.perf_counter()
        started_at = _now_iso()
        if self._is_spec_available(spec):
            record = DependencyInstallRecord(
                package=spec.package,
                modules=list(spec.modules),
                install_spec=spec.install_spec,
                source=spec.source,
                trust_level=spec.trust_level,
                hashes=dict(spec.hashes),
                post_install=list(spec.post_install),
                skill_name=spec.skill_name,
                tool_name=spec.tool_name,
                installer=self._installer,
                status="ready",
                reason="already_available",
                retryable=False,
                installed=False,
                started_at=started_at,
                finished_at=_now_iso(),
                duration_ms=int((time.perf_counter() - start) * 1000),
                attempts=0,
                venv_path=str(self.managed_venv),
                python_path=str(self.managed_python),
            )
            self._update_state(record)
            self._write_audit(record)
            return record

        lock = self._get_lock(self._lock_key(spec))
        with lock:
            if self._is_spec_available(spec):
                record = DependencyInstallRecord(
                    package=spec.package,
                    modules=list(spec.modules),
                    install_spec=spec.install_spec,
                    source=spec.source,
                    trust_level=spec.trust_level,
                    hashes=dict(spec.hashes),
                    post_install=list(spec.post_install),
                    skill_name=spec.skill_name,
                    tool_name=spec.tool_name,
                    installer=self._installer,
                    status="ready",
                    reason="already_available",
                    retryable=False,
                    installed=False,
                    started_at=started_at,
                    finished_at=_now_iso(),
                    duration_ms=int((time.perf_counter() - start) * 1000),
                    attempts=0,
                    venv_path=str(self.managed_venv),
                    python_path=str(self.managed_python),
                )
                self._update_state(record)
                self._write_audit(record)
                return record

            if not allow_install:
                record = DependencyInstallRecord(
                    package=spec.package,
                    modules=list(spec.modules),
                    install_spec=spec.install_spec,
                    source=spec.source,
                    trust_level=spec.trust_level,
                    hashes=dict(spec.hashes),
                    post_install=list(spec.post_install),
                    skill_name=spec.skill_name,
                    tool_name=spec.tool_name,
                    installer=self._installer,
                    status="missing",
                    reason="install_not_allowed",
                    retryable=True,
                    installed=False,
                    started_at=started_at,
                    finished_at=_now_iso(),
                    duration_ms=int((time.perf_counter() - start) * 1000),
                    attempts=0,
                    venv_path=str(self.managed_venv),
                    python_path=str(self.managed_python),
                )
                self._update_state(record)
                self._write_audit(record)
                return record

            if not self._is_trusted(spec):
                record = DependencyInstallRecord(
                    package=spec.package,
                    modules=list(spec.modules),
                    install_spec=spec.install_spec,
                    source=spec.source,
                    trust_level=spec.trust_level,
                    hashes=dict(spec.hashes),
                    post_install=list(spec.post_install),
                    skill_name=spec.skill_name,
                    tool_name=spec.tool_name,
                    installer=self._installer,
                    status="blocked",
                    reason="untrusted_or_direct_source",
                    retryable=False,
                    installed=False,
                    started_at=started_at,
                    finished_at=_now_iso(),
                    duration_ms=int((time.perf_counter() - start) * 1000),
                    attempts=0,
                    venv_path=str(self.managed_venv),
                    python_path=str(self.managed_python),
                )
                self._update_state(record)
                self._write_audit(record)
                return record

            self._ensure_managed_venv()
            installing_record = DependencyInstallRecord(
                package=spec.package,
                modules=list(spec.modules),
                install_spec=spec.install_spec,
                source=spec.source,
                trust_level=spec.trust_level,
                hashes=dict(spec.hashes),
                post_install=list(spec.post_install),
                skill_name=spec.skill_name,
                tool_name=spec.tool_name,
                installer=self._installer,
                status="installing",
                reason="install_started",
                retryable=True,
                installed=False,
                started_at=started_at,
                finished_at="",
                duration_ms=0,
                attempts=1,
                venv_path=str(self.managed_venv),
                python_path=str(self.managed_python),
            )
            self._update_state(installing_record)
            self._write_audit(installing_record)
            install_ok, install_output, installer = self._run_installer(spec)
            attempts = 1
            if not install_ok:
                record = DependencyInstallRecord(
                    package=spec.package,
                    modules=list(spec.modules),
                    install_spec=spec.install_spec,
                    source=spec.source,
                    trust_level=spec.trust_level,
                    hashes=dict(spec.hashes),
                    post_install=list(spec.post_install),
                    skill_name=spec.skill_name,
                    tool_name=spec.tool_name,
                    installer=installer,
                    status="failed",
                    reason=install_output[:1000] or "install_failed",
                    retryable=True,
                    installed=False,
                    started_at=started_at,
                    finished_at=_now_iso(),
                    duration_ms=int((time.perf_counter() - start) * 1000),
                    attempts=attempts,
                    venv_path=str(self.managed_venv),
                    python_path=str(self.managed_python),
                )
                self._update_state(record)
                self._write_audit(record)
                return record

            post_ok, post_output = self._run_post_install(spec)
            reason = "installed"
            status = "installed"
            if not post_ok:
                status = "failed"
                reason = post_output[:1000] or "post_install_failed"
            self._ensure_site_paths()
            importlib.invalidate_caches()
            self._reload_modules(spec)

            available_after = self._is_spec_available(spec)
            if not available_after and status == "installed":
                status = "failed"
                reason = "module_still_unavailable_after_install"

            record = DependencyInstallRecord(
                package=spec.package,
                modules=list(spec.modules),
                install_spec=spec.install_spec,
                source=spec.source,
                trust_level=spec.trust_level,
                hashes=dict(spec.hashes),
                post_install=list(spec.post_install),
                skill_name=spec.skill_name,
                tool_name=spec.tool_name,
                installer=installer,
                status=status,
                reason=reason if status != "installed" else "installed",
                retryable=status != "blocked",
                installed=status == "installed",
                started_at=started_at,
                finished_at=_now_iso(),
                duration_ms=int((time.perf_counter() - start) * 1000),
                attempts=attempts,
                venv_path=str(self.managed_venv),
                python_path=str(self.managed_python),
            )
            self._update_state(record)
            self._write_audit(record)
            return record

    async def ensure_module_async(self, *args, **kwargs) -> DependencyInstallRecord:
        return await asyncio.to_thread(self.ensure_module, *args, **kwargs)

    def ensure_specs(
        self,
        specs: Iterable[DependencySpec | dict[str, Any] | str],
        *,
        allow_install: bool = True,
    ) -> list[DependencyInstallRecord]:
        records: list[DependencyInstallRecord] = []
        for item in list(specs or []):
            spec = DependencySpec.from_value(item)
            records.append(
                self.ensure_module(
                    spec.package or ",".join(spec.modules) or spec.install_spec,
                    install_spec=spec.install_spec,
                    source=spec.source,
                    trust_level=spec.trust_level,
                    hashes=spec.hashes,
                    post_install=spec.post_install,
                    skill_name=spec.skill_name,
                    tool_name=spec.tool_name,
                    allow_install=allow_install,
                )
            )
        return records

    async def ensure_specs_async(
        self,
        specs: Iterable[DependencySpec | dict[str, Any] | str],
        *,
        allow_install: bool = True,
    ) -> list[DependencyInstallRecord]:
        return await asyncio.to_thread(self.ensure_specs, specs, allow_install=allow_install)

    def ensure_skill(
        self,
        skill_name: str,
        skill_manifest: dict[str, Any] | None = None,
        *,
        allow_install: bool = True,
    ) -> list[DependencyInstallRecord]:
        records: list[DependencyInstallRecord] = []
        for spec in self.resolve_skill_dependencies(skill_name, skill_manifest):
            records.append(
                self.ensure_module(
                    spec.package,
                    install_spec=spec.install_spec,
                    source=spec.source,
                    trust_level=spec.trust_level,
                    hashes=spec.hashes,
                    post_install=spec.post_install,
                    skill_name=skill_name or spec.skill_name,
                    tool_name=spec.tool_name,
                    allow_install=allow_install,
                )
            )
        return records

    async def ensure_skill_async(
        self,
        skill_name: str,
        skill_manifest: dict[str, Any] | None = None,
        *,
        allow_install: bool = True,
    ) -> list[DependencyInstallRecord]:
        return await asyncio.to_thread(self.ensure_skill, skill_name, skill_manifest, allow_install=allow_install)

    def ensure_tool(
        self,
        tool_name: str,
        *,
        skill_name: str = "",
        allow_install: bool = True,
    ) -> list[DependencyInstallRecord]:
        records: list[DependencyInstallRecord] = []
        for spec in self.resolve_tool_dependencies(tool_name, skill_name=skill_name):
            records.append(
                self.ensure_module(
                    spec.package,
                    install_spec=spec.install_spec,
                    source=spec.source,
                    trust_level=spec.trust_level,
                    hashes=spec.hashes,
                    post_install=spec.post_install,
                    skill_name=skill_name or spec.skill_name,
                    tool_name=tool_name,
                    allow_install=allow_install,
                )
            )
        return records

    async def ensure_tool_async(
        self,
        tool_name: str,
        *,
        skill_name: str = "",
        allow_install: bool = True,
    ) -> list[DependencyInstallRecord]:
        return await asyncio.to_thread(self.ensure_tool, tool_name, skill_name=skill_name, allow_install=allow_install)

    def ensure_from_error(
        self,
        error_text: str,
        *,
        skill_name: str = "",
        tool_name: str = "",
        allow_install: bool = True,
    ) -> list[DependencyInstallRecord]:
        records: list[DependencyInstallRecord] = []
        for package_name in self.detect_missing_from_error(error_text):
            records.append(
                self.ensure_module(
                    package_name,
                    source="pypi",
                    trust_level="trusted",
                    skill_name=skill_name,
                    tool_name=tool_name,
                    allow_install=allow_install,
                )
            )
        return records

    async def ensure_from_error_async(
        self,
        error_text: str,
        *,
        skill_name: str = "",
        tool_name: str = "",
        allow_install: bool = True,
    ) -> list[DependencyInstallRecord]:
        return await asyncio.to_thread(
            self.ensure_from_error,
            error_text,
            skill_name=skill_name,
            tool_name=tool_name,
            allow_install=allow_install,
        )

    # ── Status ─────────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        self._load_persisted_state()
        rows = [record.to_dict() for record in self._state.values()]
        rows.sort(key=lambda item: (str(item.get("status") or ""), str(item.get("package") or "")))
        counts: dict[str, int] = {}
        for row in rows:
            status = str(row.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        return {
            "enabled": bool(elyan_config.get("dependency_runtime.enabled", True)),
            "mode": str(elyan_config.get("dependency_runtime.mode", "managed_venv") or "managed_venv"),
            "source_policy": {
                "trusted_sources": list(elyan_config.get("dependency_runtime.trusted_sources", ["pypi", "marketplace"]) or ["pypi", "marketplace"]),
                "blocked_schemes": list(elyan_config.get("dependency_runtime.blocked_schemes", list(BLOCKED_SCHEMES)) or list(BLOCKED_SCHEMES)),
            },
            "managed_venv": str(self.managed_venv),
            "python": str(self.managed_python),
            "installer": self._installer,
            "state_path": str(self.state_path),
            "status_counts": counts,
            "installing_packages": [row for row in rows if row.get("status") == "installing"],
            "installed_packages": [row for row in rows if row.get("status") == "installed"],
            "ready_packages": [row for row in rows if row.get("status") == "ready"],
            "blocked_packages": [row for row in rows if row.get("status") == "blocked"],
            "failed_packages": [row for row in rows if row.get("status") == "failed"],
            "recent_records": rows[-20:],
            "audit_path": str(self.audit_path),
        }


_resolver_singleton: PackageRuntimeResolver | None = None


def get_dependency_runtime() -> PackageRuntimeResolver:
    global _resolver_singleton
    if _resolver_singleton is None:
        _resolver_singleton = PackageRuntimeResolver()
    return _resolver_singleton
