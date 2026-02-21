"""
Startup Health Check System
Comprehensive validation before launching Elyan
"""

import os
import sys
import subprocess
import importlib.util
from pathlib import Path
from typing import Tuple, List, Dict, Any
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger("startup_checker")


@dataclass
class HealthCheckResult:
    """Health check result"""
    passed: bool
    message: str
    severity: str  # "error", "warning", "info"
    fix_suggestion: str = ""


class StartupChecker:
    """
    Validates system readiness before launching Elyan
    - Checks configuration files
    - Validates LLM provider setup
    - Verifies dependencies
    - Tests connectivity
    """

    def __init__(self):
        self.root_dir = Path(__file__).parent.parent
        self.env_path = self.root_dir / ".env"
        self.checks: List[HealthCheckResult] = []
        self.settings = self._load_settings()

    def _load_settings(self):
        """Load settings manager safely (startup checker should not hard-fail)."""
        try:
            from config.settings_manager import SettingsPanel
            return SettingsPanel()
        except Exception:
            return None

    def _provider_from_settings_or_env(self) -> str:
        """Resolve active provider from settings first, then legacy env."""
        provider = ""
        if self.settings:
            provider = str(self.settings.get("llm_provider", "")).strip().lower()
            if provider == "api":
                provider = "gemini"
        if not provider:
            provider = str(os.getenv("LLM_TYPE", "")).strip().lower()
            if provider == "api":
                provider = "gemini"
        return provider

    def _provider_key_from_settings_or_env(self, provider: str) -> str:
        """Resolve provider credential from settings or env."""
        provider = (provider or "").lower()
        settings_key = ""
        if self.settings:
            settings_provider = str(self.settings.get("llm_provider", "")).strip().lower()
            settings_api = str(self.settings.get("api_key", "")).strip()
            if settings_provider in {provider, "api"} and settings_api:
                settings_key = settings_api
        if settings_key:
            return settings_key
        if provider == "groq":
            return os.getenv("GROQ_API_KEY", "")
        if provider == "gemini":
            return os.getenv("GOOGLE_API_KEY", "")
        if provider == "openai":
            return os.getenv("OPENAI_API_KEY", "")
        return ""

    def run_all_checks(self) -> Tuple[bool, List[HealthCheckResult]]:
        """
        Run all health checks
        Returns: (all_passed, list_of_results)
        """
        logger.info("Running startup health checks...")

        self.checks = []

        # Critical checks (must pass)
        self._check_python_version()
        self._check_env_file()
        self._check_llm_configuration()
        self._check_required_packages()
        self._check_file_permissions()

        # Optional checks (warnings only)
        self._check_telegram_config()
        self._check_disk_space()

        # Count errors
        errors = [c for c in self.checks if c.severity == "error" and not c.passed]
        warnings = [c for c in self.checks if c.severity == "warning" and not c.passed]

        all_passed = len(errors) == 0

        logger.info(f"Health check complete: {len(errors)} errors, {len(warnings)} warnings")

        return all_passed, self.checks

    def _check_python_version(self):
        """Check Python version"""
        version = sys.version_info
        required = (3, 10)

        if version >= required:
            self.checks.append(HealthCheckResult(
                passed=True,
                message=f"Python {version.major}.{version.minor} (OK)",
                severity="info"
            ))
        else:
            self.checks.append(HealthCheckResult(
                passed=False,
                message=f"Python {version.major}.{version.minor} is too old",
                severity="error",
                fix_suggestion=f"Please upgrade to Python {required[0]}.{required[1]} or higher"
            ))

    def _check_env_file(self):
        """Check if .env exists (optional if settings-based config is valid)."""
        provider = self._provider_from_settings_or_env()
        provider_ok = provider == "ollama" or bool(self._provider_key_from_settings_or_env(provider))

        if not self.env_path.exists():
            if provider_ok:
                self.checks.append(HealthCheckResult(
                    passed=False,
                    message=".env file not found (settings.json ile devam ediliyor)",
                    severity="warning",
                    fix_suggestion="Opsiyonel: .env oluşturarak taşınabilirlik artırılabilir"
                ))
                return
            self.checks.append(HealthCheckResult(
                passed=False,
                message=".env file not found",
                severity="error",
                fix_suggestion="Run setup wizard: python main.py"
            ))
            return

        if not os.access(self.env_path, os.R_OK):
            self.checks.append(HealthCheckResult(
                passed=False,
                message=".env file is not readable",
                severity="error",
                fix_suggestion=f"Check file permissions: chmod 644 {self.env_path}"
            ))
            return

        self.checks.append(HealthCheckResult(
            passed=True,
            message=".env file found and readable",
            severity="info"
        ))

    def _check_llm_configuration(self):
        """Check if LLM provider is properly configured"""
        llm_type = self._provider_from_settings_or_env()

        if not llm_type:
            self.checks.append(HealthCheckResult(
                passed=False,
                message="LLM_TYPE not set",
                severity="error",
                fix_suggestion="Run setup wizard to configure AI provider"
            ))
            return

        # Check provider-specific requirements
        if llm_type == "groq":
            api_key = self._provider_key_from_settings_or_env("groq")
            if api_key:
                self.checks.append(HealthCheckResult(
                    passed=True,
                    message="Groq API configured",
                    severity="info"
                ))
            else:
                self.checks.append(HealthCheckResult(
                    passed=False,
                    message="Groq API key missing",
                    severity="error",
                    fix_suggestion="Get free API key: https://console.groq.com/keys"
                ))

        elif llm_type == "gemini":
            api_key = self._provider_key_from_settings_or_env("gemini")
            if api_key:
                self.checks.append(HealthCheckResult(
                    passed=True,
                    message="Gemini API configured",
                    severity="info"
                ))
            else:
                self.checks.append(HealthCheckResult(
                    passed=False,
                    message="Gemini API key missing",
                    severity="error",
                    fix_suggestion="Get free API key: https://makersuite.google.com/app/apikey"
                ))

        elif llm_type == "openai":
            api_key = self._provider_key_from_settings_or_env("openai")
            if api_key:
                self.checks.append(HealthCheckResult(
                    passed=True,
                    message="OpenAI API configured",
                    severity="info"
                ))
            else:
                self.checks.append(HealthCheckResult(
                    passed=False,
                    message="OpenAI API key missing",
                    severity="error",
                    fix_suggestion="Get API key: https://platform.openai.com/api-keys"
                ))

        elif llm_type == "ollama":
            # Check if Ollama is installed and running
            try:
                result = subprocess.run(
                    ["ollama", "list"],
                    capture_output=True,
                    text=True,
                    timeout=3
                )
                if result.returncode == 0:
                    models = [line.split()[0] for line in result.stdout.strip().splitlines()[1:] if line.split()]
                    if models:
                        self.checks.append(HealthCheckResult(
                            passed=True,
                            message=f"Ollama configured ({len(models)} models)",
                            severity="info"
                        ))
                    else:
                        self.checks.append(HealthCheckResult(
                            passed=False,
                            message="Ollama installed but no models found",
                            severity="error",
                            fix_suggestion="Install a model: ollama pull llama3.2:3b"
                        ))
                else:
                    self.checks.append(HealthCheckResult(
                        passed=False,
                        message="Ollama not responding",
                        severity="error",
                        fix_suggestion="Start Ollama service"
                    ))
            except FileNotFoundError:
                self.checks.append(HealthCheckResult(
                    passed=False,
                    message="Ollama not installed",
                    severity="error",
                    fix_suggestion="Install Ollama: https://ollama.com/download"
                ))
            except subprocess.TimeoutExpired:
                self.checks.append(HealthCheckResult(
                    passed=False,
                    message="Ollama service timeout",
                    severity="error",
                    fix_suggestion="Check if Ollama is running"
                ))

        else:
            self.checks.append(HealthCheckResult(
                passed=False,
                message=f"Unknown LLM type: {llm_type}",
                severity="error",
                fix_suggestion="Valid types: groq, gemini, openai, ollama"
            ))

    def _check_required_packages(self):
        """Check if required Python packages are installed"""
        # (distribution_name, import_module_name)
        required = [
            ("PyQt6", "PyQt6"),
            ("httpx", "httpx"),
            ("python-telegram-bot", "telegram"),
            ("python-dotenv", "dotenv"),
        ]

        missing = []
        for dist_name, import_name in required:
            if importlib.util.find_spec(import_name) is None:
                missing.append(dist_name)

        if missing:
            self.checks.append(HealthCheckResult(
                passed=False,
                message=f"Missing packages: {', '.join(missing)}",
                severity="error",
                fix_suggestion=f"Install: pip install {' '.join(missing)}"
            ))
        else:
            self.checks.append(HealthCheckResult(
                passed=True,
                message="All required packages installed",
                severity="info"
            ))

    def _check_file_permissions(self):
        """Check if necessary directories are writable"""
        logs_dir = self.root_dir / "logs"
        if self._is_dir_writable(logs_dir):
            self.checks.append(HealthCheckResult(
                passed=True,
                message=f"Directory writable: {logs_dir.name}",
                severity="info"
            ))
        else:
            self.checks.append(HealthCheckResult(
                passed=False,
                message=f"Directory not writable: {logs_dir}",
                severity="error",
                fix_suggestion=f"Fix permissions: chmod 755 {logs_dir}"
            ))

        home_config_dir = Path.home() / ".elyan"
        local_fallback_dir = self.root_dir / ".elyan"

        if self._is_dir_writable(home_config_dir):
            self.checks.append(HealthCheckResult(
                passed=True,
                message="Directory writable: .elyan",
                severity="info"
            ))
            return

        if self._is_dir_writable(local_fallback_dir):
            self.checks.append(HealthCheckResult(
                passed=False,
                message=f"Home config dir not writable, using fallback: {local_fallback_dir}",
                severity="warning",
                fix_suggestion=f"Optional fix: chmod 755 {home_config_dir}"
            ))
            return

        self.checks.append(HealthCheckResult(
            passed=False,
            message=f"Config directories not writable: {home_config_dir} and {local_fallback_dir}",
            severity="error",
            fix_suggestion=f"Fix permissions: chmod 755 {home_config_dir}"
        ))

    def _is_dir_writable(self, directory: Path) -> bool:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".elyan_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def _check_telegram_config(self):
        """Check Telegram configuration (optional)"""
        token = ""
        user_ids = ""
        if self.settings:
            token = str(self.settings.get("telegram_token", "")).strip()
            allowed = self.settings.get("allowed_user_ids", [])
            if isinstance(allowed, list) and allowed:
                user_ids = ",".join(str(x) for x in allowed if str(x).strip())
        if not token:
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not user_ids:
            user_ids = os.getenv("ALLOWED_USER_IDS", "")

        if token and user_ids:
            self.checks.append(HealthCheckResult(
                passed=True,
                message="Telegram bot configured",
                severity="info"
            ))
        else:
            self.checks.append(HealthCheckResult(
                passed=False,
                message="Telegram bot not configured",
                severity="warning",
                fix_suggestion="Configure in settings for mobile access"
            ))

    def _check_disk_space(self):
        """Check available disk space"""
        try:
            import shutil
            total, used, free = shutil.disk_usage(self.root_dir)
            free_gb = free // (2**30)

            if free_gb < 1:
                self.checks.append(HealthCheckResult(
                    passed=False,
                    message=f"Low disk space: {free_gb}GB free",
                    severity="warning",
                    fix_suggestion="Free up disk space"
                ))
            else:
                self.checks.append(HealthCheckResult(
                    passed=True,
                    message=f"Disk space OK: {free_gb}GB free",
                    severity="info"
                ))
        except Exception as e:
            logger.debug(f"Disk space check failed: {e}")

    def get_summary(self) -> str:
        """Get human-readable summary"""
        errors = [c for c in self.checks if c.severity == "error" and not c.passed]
        warnings = [c for c in self.checks if c.severity == "warning" and not c.passed]
        passed = [c for c in self.checks if c.passed]

        summary = f"""
╔══════════════════════════════════════════════════════╗
║          ELYAN STARTUP HEALTH CHECK                   ║
╚══════════════════════════════════════════════════════╝

✓ Passed: {len(passed)}
⚠ Warnings: {len(warnings)}
✗ Errors: {len(errors)}

"""
        if errors:
            summary += "ERRORS (must fix):\n"
            for err in errors:
                summary += f"  ✗ {err.message}\n"
                if err.fix_suggestion:
                    summary += f"    → {err.fix_suggestion}\n"
            summary += "\n"

        if warnings:
            summary += "WARNINGS (optional):\n"
            for warn in warnings:
                summary += f"  ⚠ {warn.message}\n"
                if warn.fix_suggestion:
                    summary += f"    → {warn.fix_suggestion}\n"
            summary += "\n"

        return summary


def run_startup_checks() -> bool:
    """
    Run all startup checks and print summary
    Returns: True if all critical checks passed
    """
    checker = StartupChecker()
    all_passed, results = checker.run_all_checks()

    summary = checker.get_summary()
    print(summary)
    logger.info(summary)

    return all_passed


if __name__ == "__main__":
    passed = run_startup_checks()
    sys.exit(0 if passed else 1)
