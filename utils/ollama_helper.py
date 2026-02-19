import subprocess
import shutil
import os
import platform
from utils.logger import get_logger

logger = get_logger("ollama_helper")

class OllamaHelper:
    @staticmethod
    def is_installed() -> bool:
        return shutil.which("ollama") is not None

    @staticmethod
    def is_running() -> bool:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', 11434)) == 0

    @staticmethod
    def get_install_command() -> str:
        system = platform.system()
        if system == "Darwin": # macOS
            return "brew install ollama"
        elif system == "Linux":
            return "curl -fsSL https://ollama.com/install.sh | sh"
        else:
            return "Lütfen https://ollama.com adresinden indirip kurun."

    @staticmethod
    def list_local_models():
        if not OllamaHelper.is_installed(): return []
        try:
            res = subprocess.run(["ollama", "list"], capture_output=True, text=True)
            lines = res.stdout.strip().split("
")[1:]
            return [line.split()[0] for line in lines if line]
        except:
            return []

    @staticmethod
    def pull_model(model_name: str):
        logger.info(f"Pulling model: {model_name}")
        subprocess.Popen(["ollama", "pull", model_name])
