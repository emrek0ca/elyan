#!/usr/bin/env python3
"""
validate_environment.py — Elyan Preflight Environment Validator
───────────────────────────────────────────────────────────────────────────────
Run this before starting Elyan to catch common setup failures early.

Usage:
    python validate_environment.py          # full check, exit 1 on any FAIL
    python validate_environment.py --warn   # only warnings, never exit 1
    python validate_environment.py --json   # machine-readable JSON output

Exit codes:
    0  — all checks passed (or --warn mode)
    1  — one or more FAIL-severity checks failed
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Literal

# ── Severity levels ───────────────────────────────────────────────────────────
Severity = Literal["FAIL", "WARN", "OK", "SKIP"]

RESET  = "\033[0m"
RED    = "\033[91m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"


@dataclass
class CheckResult:
    name: str
    severity: Severity
    message: str
    fix: str = ""


# ── Individual checks ─────────────────────────────────────────────────────────

def check_python_version() -> CheckResult:
    major, minor = sys.version_info[:2]
    if major == 3 and minor >= 11:
        return CheckResult("python_version", "OK", f"Python {major}.{minor} ✓")
    if major == 3 and minor >= 10:
        return CheckResult(
            "python_version", "WARN",
            f"Python {major}.{minor} — 3.11+ strongly recommended",
            "Use pyenv: pyenv install 3.11.9 && pyenv local 3.11.9",
        )
    return CheckResult(
        "python_version", "FAIL",
        f"Python {major}.{minor} — minimum required: 3.10",
        "Install Python 3.11+: https://python.org",
    )


def check_venv() -> CheckResult:
    in_venv = sys.prefix != sys.base_prefix or os.environ.get("VIRTUAL_ENV")
    if in_venv:
        return CheckResult("venv", "OK", f"Virtual environment active: {sys.prefix}")
    return CheckResult(
        "venv", "WARN",
        "Not running in a virtual environment — dependency isolation is absent",
        "python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt",
    )


def check_required_packages() -> list[CheckResult]:
    """Check that all critical packages importable."""
    CRITICAL = [
        ("aiohttp",      "aiohttp>=3.9.0"),
        ("pydantic",     "pydantic>=2.0.0"),
        ("click",        "click>=8.1.0"),
        ("flask",        "flask>=3.0.0"),
        ("flask_cors",   "flask-cors>=4.0.0"),
        ("socketio",     "python-socketio>=5.11.0"),
        ("psutil",       "psutil>=5.9.0"),
        ("cryptography", "cryptography>=42.0.0"),
    ]
    OPTIONAL = [
        ("telegram",     "python-telegram-bot>=22.0", "Telegram channel"),
        ("groq",         "groq>=0.11.0",              "Groq LLM"),
        ("sqlalchemy",   "sqlalchemy>=2.0.0",          "persistence layer"),
        ("sentence_transformers", "sentence-transformers>=3.0.0", "semantic memory"),
    ]

    results = []
    for pkg, spec in CRITICAL:
        if importlib.util.find_spec(pkg) is not None:
            results.append(CheckResult(f"pkg:{pkg}", "OK", f"{pkg} ✓"))
        else:
            results.append(CheckResult(
                f"pkg:{pkg}", "FAIL",
                f"{pkg} is NOT installed — required for core functionality",
                f"pip install {spec}",
            ))

    for pkg, spec, role in OPTIONAL:
        if importlib.util.find_spec(pkg) is not None:
            results.append(CheckResult(f"pkg:{pkg}", "OK", f"{pkg} ✓ ({role})"))
        else:
            results.append(CheckResult(
                f"pkg:{pkg}", "WARN",
                f"{pkg} not installed — {role} will be unavailable",
                f"pip install {spec}",
            ))

    return results


def check_env_file() -> CheckResult:
    if os.path.exists(".env"):
        return CheckResult("env_file", "OK", ".env file found")
    if os.path.exists(".env.example"):
        return CheckResult(
            "env_file", "WARN",
            ".env not found — using defaults (no API keys configured)",
            "cp .env.example .env && edit .env",
        )
    return CheckResult(
        "env_file", "WARN",
        "Neither .env nor .env.example found",
        "Create .env with at minimum: ELYAN_PORT=18789",
    )


def check_required_env_vars() -> list[CheckResult]:
    from dotenv import load_dotenv
    load_dotenv(override=False)

    REQUIRED_FOR_LLM = ["GROQ_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
    REQUIRED_FOR_CHANNEL = ["TELEGRAM_BOT_TOKEN"]

    results = []

    llm_configured = any(os.environ.get(k) for k in REQUIRED_FOR_LLM)
    if not llm_configured:
        # Check Ollama as local alternative
        try:
            import urllib.request
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
            results.append(CheckResult(
                "llm_provider", "OK",
                "Ollama running locally — no cloud LLM key required",
            ))
        except Exception:
            results.append(CheckResult(
                "llm_provider", "WARN",
                "No LLM provider configured (no cloud API key, Ollama not reachable)",
                "Set GROQ_API_KEY in .env OR start Ollama: ollama serve",
            ))
    else:
        configured = [k for k in REQUIRED_FOR_LLM if os.environ.get(k)]
        results.append(CheckResult("llm_provider", "OK", f"LLM keys: {', '.join(configured)}"))

    for var in REQUIRED_FOR_CHANNEL:
        val = os.environ.get(var)
        if val:
            results.append(CheckResult(f"env:{var}", "OK", f"{var} configured"))
        else:
            results.append(CheckResult(
                f"env:{var}", "WARN",
                f"{var} not set — channel will be unavailable",
                f"Add {var}=<token> to .env",
            ))

    return results


def check_disk_space() -> CheckResult:
    total, used, free = shutil.disk_usage("/")
    free_gb = free / (1024 ** 3)
    if free_gb >= 5:
        return CheckResult("disk_space", "OK", f"{free_gb:.1f} GB free")
    if free_gb >= 1:
        return CheckResult(
            "disk_space", "WARN", f"Only {free_gb:.1f} GB free — may cause issues",
        )
    return CheckResult(
        "disk_space", "FAIL", f"Only {free_gb:.1f} GB free — insufficient",
        "Free up disk space before running Elyan",
    )


def check_stale_build() -> CheckResult:
    if os.path.isdir("build/lib"):
        return CheckResult(
            "stale_build", "WARN",
            "build/lib/ exists — stale copy of codebase that may cause import confusion",
            "rm -rf build/",
        )
    return CheckResult("stale_build", "OK", "No stale build artifacts")


def check_ollama() -> CheckResult:
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            import json
            data = json.loads(r.read())
            models = [m["name"] for m in data.get("models", [])]
            if models:
                return CheckResult("ollama", "OK", f"Ollama running, models: {', '.join(models[:3])}")
            return CheckResult(
                "ollama", "WARN",
                "Ollama running but no models pulled",
                "ollama pull llama3.2:3b",
            )
    except Exception:
        return CheckResult(
            "ollama", "WARN",
            "Ollama not reachable — local LLM unavailable (cloud provider will be used)",
            "brew install ollama && ollama serve  (in separate terminal)",
        )


def check_macos() -> CheckResult:
    if platform.system() == "Darwin":
        ver = platform.mac_ver()[0]
        return CheckResult("platform", "OK", f"macOS {ver}")
    return CheckResult(
        "platform", "WARN",
        f"Running on {platform.system()} — Elyan is optimized for macOS",
        "Some features (voice, macOS control, Calendar, AppleScript) will not work",
    )


def check_graveyard() -> CheckResult:
    if os.path.isdir("_graveyard") and os.path.isdir("_graveyard/bot_legacy"):
        try:
            result = subprocess.run(["du", "-sh", "_graveyard"], capture_output=True, text=True)
            size = result.stdout.split()[0] if result.returncode == 0 else "?"
            return CheckResult(
                "graveyard", "WARN",
                f"_graveyard/ is {size} of legacy code on disk",
                "Consider: mv _graveyard/ ~/Desktop/elyan_graveyard_backup/ to reclaim disk",
            )
        except Exception:
            return CheckResult("graveyard", "WARN", "_graveyard/ exists with legacy code")
    return CheckResult("graveyard", "OK", "No legacy graveyard directory")


# ── Runner ────────────────────────────────────────────────────────────────────

def run_all_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []
    checks.append(check_python_version())
    checks.append(check_venv())
    checks.extend(check_required_packages())
    checks.append(check_env_file())
    try:
        checks.extend(check_required_env_vars())
    except Exception as exc:
        checks.append(CheckResult("env_vars", "WARN", f"Could not check env vars: {exc}"))
    checks.append(check_disk_space())
    checks.append(check_stale_build())
    checks.append(check_ollama())
    checks.append(check_macos())
    checks.append(check_graveyard())
    return checks


def _color(severity: Severity) -> str:
    return {
        "OK":   GREEN,
        "WARN": YELLOW,
        "FAIL": RED,
        "SKIP": BLUE,
    }.get(severity, RESET)


def print_report(results: list[CheckResult]) -> None:
    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(f"{BOLD}  Elyan — Environment Validation Report{RESET}")
    print(f"{BOLD}{'─'*60}{RESET}\n")

    for r in results:
        color = _color(r.severity)
        badge = f"{color}[{r.severity:4}]{RESET}"
        print(f"  {badge}  {r.name:<28} {r.message}")
        if r.fix and r.severity in ("FAIL", "WARN"):
            print(f"           {'':28} {YELLOW}↳ {r.fix}{RESET}")

    fails  = [r for r in results if r.severity == "FAIL"]
    warns  = [r for r in results if r.severity == "WARN"]
    oks    = [r for r in results if r.severity == "OK"]

    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(f"  {GREEN}{len(oks)} OK{RESET}  "
          f"{YELLOW}{len(warns)} WARN{RESET}  "
          f"{RED}{len(fails)} FAIL{RESET}")
    print(f"{BOLD}{'─'*60}{RESET}\n")

    if fails:
        print(f"{RED}{BOLD}  ✗ Environment is NOT ready. Fix FAIL items above.{RESET}\n")
    elif warns:
        print(f"{YELLOW}  ⚠ Environment has warnings. Elyan may start but some features will be limited.{RESET}\n")
    else:
        print(f"{GREEN}{BOLD}  ✓ Environment looks healthy. Ready to start Elyan.{RESET}\n")


if __name__ == "__main__":
    warn_only = "--warn" in sys.argv
    as_json   = "--json" in sys.argv

    results = run_all_checks()

    if as_json:
        print(json.dumps([
            {"name": r.name, "severity": r.severity, "message": r.message, "fix": r.fix}
            for r in results
        ], indent=2))
    else:
        print_report(results)

    fails = [r for r in results if r.severity == "FAIL"]
    if fails and not warn_only:
        sys.exit(1)
