from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess

from core.dependencies import get_system_dependency_runtime
from utils.logger import get_logger

logger = get_logger("ollama_helper")


class OllamaHelper:
    @staticmethod
    def is_installed() -> bool:
        return shutil.which("ollama") is not None

    @staticmethod
    def ensure_installed(*, allow_install: bool = True) -> bool:
        runtime = get_system_dependency_runtime()
        record = runtime.ensure_binary(
            "ollama",
            allow_install=allow_install,
            skill_name="models",
            tool_name="ollama_helper",
        )
        return record.status in {"installed", "ready"}

    @staticmethod
    def is_running() -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("localhost", 11434)) == 0

    @staticmethod
    def _start_service() -> bool:
        if OllamaHelper.is_running():
            return True
        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            if system == "Linux":
                if shutil.which("systemctl"):
                    result = subprocess.run(["systemctl", "--user", "start", "ollama"], capture_output=True, text=True)
                    if result.returncode == 0:
                        return True
                subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            if system == "Windows":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                subprocess.Popen(["ollama", "serve"], creationflags=creationflags)
                return True
        except Exception as exc:
            logger.debug("Ollama service start skipped: %s", exc)
        return OllamaHelper.is_running()

    @staticmethod
    def ensure_available(*, allow_install: bool = True, start_service: bool = True) -> bool:
        if not OllamaHelper.ensure_installed(allow_install=allow_install):
            return False
        if start_service and not OllamaHelper.is_running():
            return OllamaHelper._start_service()
        return True

    @staticmethod
    def get_install_command() -> str:
        runtime = get_system_dependency_runtime()
        hint = runtime.get_install_hint("ollama")
        if hint:
            return hint
        system = platform.system()
        if system == "Darwin":
            return "brew install ollama"
        if system == "Linux":
            return "curl -fsSL https://ollama.com/install.sh | sh"
        if system == "Windows":
            return "winget install --id Ollama.Ollama -e"
        return "Lütfen https://ollama.com adresinden indirip kurun."

    @staticmethod
    def list_local_models() -> list[str]:
        if not OllamaHelper.ensure_available(start_service=True):
            return []
        try:
            env = os.environ.copy()
            env.setdefault("OLLAMA_HOST", "http://localhost:11434")
            res = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10, env=env)
            if res.returncode != 0:
                return []
            lines = res.stdout.strip().splitlines()[1:]
            models = []
            for line in lines:
                parts = line.split()
                if parts:
                    models.append(parts[0])
            return models
        except Exception:
            return []

    @staticmethod
    def pull_model(model_name: str) -> bool:
        if not OllamaHelper.ensure_available(start_service=True):
            return False
        logger.info("Pulling model: %s", model_name)
        subprocess.Popen(["ollama", "pull", model_name])
        return True

