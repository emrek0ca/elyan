from __future__ import annotations

import os
import platform
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from runtime.capability_registry import SafeCapabilityError

# Commands that are never allowed regardless of context
_HARD_BLOCKED = (
    "rm -rf /",
    "rm -rf ~",
    "sudo rm -rf",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    "halt",
    "diskutil erase",
    "diskutil apfs deletecontainer",
    "format c:",
    "del /f /s /q c:\\",
)

# Prefixes that require explicit shell mode (no argv-only mode)
_ELEVATED_PREFIXES = ("sudo ", "su ", "doas ")

_MAX_OUTPUT_CHARS = 4000
_DEFAULT_TIMEOUT = 30

_READ_ONLY_COMMANDS = {
    "pwd",
    "ls",
    "dir",
    "echo",
    "cat",
    "head",
    "tail",
    "wc",
    "rg",
    "grep",
    "find",
    "git",
    "python",
    "python3",
    "node",
    "npm",
    "pnpm",
    "yarn",
}

_GIT_READ_ONLY_SUBCOMMANDS = {
    "status",
    "log",
    "diff",
    "show",
    "branch",
    "rev-parse",
    "ls-files",
    "grep",
    "describe",
}

_VERSION_FLAGS = {"--version", "-v", "-V", "version"}
_CRITICAL_PATTERNS = (
    "security find-generic-password",
    "security dump-keychain",
    "cat ~/.ssh",
    "cat ~/.aws",
    "cat ~/.config",
    "/etc/shadow",
    "id_rsa",
    "id_ed25519",
    "api_key",
    "access_token",
    "refresh_token",
)
_UPLOAD_PATTERNS = ("curl -f", "curl --form", "curl -t", "scp ", "rsync ", "sftp ", "ftp ")
_MUTATING_TOKENS = (
    " rm ",
    " mv ",
    " cp ",
    " chmod ",
    " chown ",
    " mkdir ",
    " rmdir ",
    " touch ",
    " tee ",
    " install ",
    " uninstall ",
    " add ",
    " commit ",
    " push ",
    " pull ",
    " reset ",
    " checkout ",
    " switch ",
    " merge ",
    " rebase ",
    " apply ",
    " patch ",
)


def _platform_shell() -> tuple[str, list[str]]:
    """Return (shell_name, prefix_args) for the current OS."""
    if sys.platform == "win32":
        return "powershell", ["powershell", "-NonInteractive", "-Command"]
    if sys.platform == "darwin":
        return "zsh", ["/bin/zsh", "-c"]
    return "bash", ["/bin/bash", "-c"]


def _is_hard_blocked(command: str) -> bool:
    lower = command.lower().strip()
    return any(blocked in lower for blocked in _HARD_BLOCKED)


def _is_elevated(command: str) -> bool:
    lower = command.lower().strip()
    return any(lower.startswith(p) for p in _ELEVATED_PREFIXES)


def _has_shell_metacharacters(command: str) -> bool:
    return any(op in command for op in ("&&", "||", "|", ";", ">", "<", "$(", "`"))


def _truncate_output(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return "Komut başarıyla tamamlandı (çıktı yok)."
    if len(raw) > _MAX_OUTPUT_CHARS:
        return raw[:_MAX_OUTPUT_CHARS] + f"\n… (çıktı {len(raw)} karakter, kısaltıldı)"
    return raw


def _redact_output(raw: str) -> str:
    redacted_lines: list[str] = []
    for line in str(raw or "").splitlines():
        lowered = line.lower()
        if any(token in lowered for token in ("password", "secret", "token", "api_key", "apikey", "private key")):
            redacted_lines.append("[redacted sensitive output]")
        else:
            redacted_lines.append(line)
    return "\n".join(redacted_lines)


def _parse_argv(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=(os.name != "nt"))
    except ValueError as exc:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Komut ayrıştırılamadı.") from exc


def classify_command(command: str, *, use_shell: bool = False) -> dict[str, Any]:
    stripped = str(command or "").strip()
    lowered = f" {stripped.lower()} "
    if not stripped:
        return {"risk": "invalid", "readOnly": False, "critical": False, "reason": "missing_command"}
    if _is_hard_blocked(stripped):
        return {"risk": "blocked", "readOnly": False, "critical": True, "reason": "hard_blocked"}
    if _is_elevated(stripped):
        return {"risk": "critical", "readOnly": False, "critical": True, "reason": "elevated"}
    if any(pattern in lowered for pattern in _CRITICAL_PATTERNS):
        return {"risk": "critical", "readOnly": False, "critical": True, "reason": "credential_access"}
    if any(pattern in lowered for pattern in _UPLOAD_PATTERNS):
        return {"risk": "critical", "readOnly": False, "critical": True, "reason": "external_upload"}
    if _has_shell_metacharacters(stripped) or use_shell:
        return {"risk": "mutating", "readOnly": False, "critical": False, "reason": "shell_operators"}
    argv = _parse_argv(stripped)
    executable = Path(argv[0]).name.lower() if argv else ""
    if executable not in _READ_ONLY_COMMANDS:
        return {"risk": "mutating", "readOnly": False, "critical": False, "reason": "not_read_only_allowlist"}
    if executable == "git":
        subcommand = next((item for item in argv[1:] if not str(item).startswith("-")), "")
        if not subcommand or subcommand in _GIT_READ_ONLY_SUBCOMMANDS:
            return {"risk": "read_only", "readOnly": True, "critical": False, "reason": "git_read_only"}
        return {"risk": "mutating", "readOnly": False, "critical": False, "reason": "git_mutating"}
    if executable in {"python", "python3", "node", "npm", "pnpm", "yarn"}:
        if len(argv) >= 2 and argv[1] in _VERSION_FLAGS:
            return {"risk": "read_only", "readOnly": True, "critical": False, "reason": "version_check"}
        if executable in {"npm", "pnpm", "yarn"} and len(argv) >= 2 and argv[1] in {"test", "run", "exec"}:
            return {"risk": "mutating", "readOnly": False, "critical": False, "reason": "project_command"}
        return {"risk": "mutating", "readOnly": False, "critical": False, "reason": "code_execution"}
    if executable == "find" and any(item in {"-delete", "-exec", "-execdir"} for item in argv[1:]):
        return {"risk": "mutating", "readOnly": False, "critical": False, "reason": "find_mutating"}
    if any(token in lowered for token in _MUTATING_TOKENS):
        return {"risk": "mutating", "readOnly": False, "critical": False, "reason": "mutating_token"}
    return {"risk": "read_only", "readOnly": True, "critical": False, "reason": "allowlist"}


def shell_run(
    command: str,
    timeout: int = _DEFAULT_TIMEOUT,
    *,
    use_shell: bool = False,
    working_dir: str = "",
    mode: str = "confirmed",
) -> dict[str, Any]:
    """Execute a shell command and return combined stdout+stderr.

    By default runs argv-parsed (safe). Set use_shell=True for piped/complex commands.
    """
    stripped = str(command or "").strip()
    if not stripped:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Komut belirtilmedi.")

    classified = classify_command(stripped, use_shell=use_shell)
    if classified["risk"] == "blocked" or _is_hard_blocked(stripped):
        raise SafeCapabilityError("INVALID_ARGUMENT", "Bu komut güvenlik nedeniyle engellenmiştir.")

    if _is_elevated(stripped) or classified.get("critical") is True:
        raise SafeCapabilityError(
            "INVALID_ARGUMENT",
            "Bu komut credential, upload veya yükseltilmiş yetki riski nedeniyle engellendi.",
        )
    normalized_mode = str(mode or "confirmed").strip().lower()
    if normalized_mode == "read_only" and classified.get("readOnly") is not True:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Read-only mod yalnız güvenli tanılama komutlarını çalıştırır.")

    cwd: str | None = None
    if working_dir:
        wd = Path(working_dir).expanduser()
        if wd.is_dir():
            cwd = str(wd)

    try:
        # Use platform shell for complex commands (pipes, redirects, etc.)
        shell_name, prefix = _platform_shell()
        has_shell_metacharacters = _has_shell_metacharacters(stripped)
        if has_shell_metacharacters and not use_shell:
            raise SafeCapabilityError(
                "INVALID_ARGUMENT",
                "Shell operatörleri için açık use_shell izni gerekiyor.",
            )
        if use_shell:
            if sys.platform == "win32":
                argv = prefix + [stripped]
            else:
                argv = prefix + [stripped]
        else:
            argv = _parse_argv(stripped)

        run_kwargs = {
            "shell": False,
            "capture_output": True,
            "text": True,
            "timeout": timeout,
        }
        if cwd:
            run_kwargs["cwd"] = cwd
        if use_shell:
            run_kwargs["env"] = {**os.environ, "TERM": "dumb"}
        started = time.perf_counter()
        result = subprocess.run(argv, **run_kwargs)
        duration_ms = int((time.perf_counter() - started) * 1000)
    except subprocess.TimeoutExpired as exc:
        raise SafeCapabilityError("TIMEOUT", f"Komut zaman aşımına uğradı ({timeout}s).") from exc
    except FileNotFoundError as exc:
        first_word = stripped.split()[0] if stripped else "komut"
        raise SafeCapabilityError("INVALID_ARGUMENT", f"Komut bulunamadı: {first_word}") from exc
    except SafeCapabilityError:
        raise
    except Exception as exc:
        raise SafeCapabilityError("TOOL_EXECUTION_FAILED", f"Komut çalıştırılamadı: {exc}") from exc

    stdout = _redact_output(result.stdout or "")
    stderr = _redact_output(result.stderr or "")
    combined = stdout + stderr
    output = _truncate_output(combined)

    return_code = int(getattr(result, "returncode", 0) or 0)
    if return_code != 0 and not result.stdout.strip():
        exit_note = f"[çıkış kodu: {return_code}]"
        output = f"{output}\n{exit_note}" if output else exit_note

    return {
        "text": output,
        "result": {
            "kind": "shell_run",
            "command": stripped,
            "argv": argv,
            "cwd": cwd or str(Path.cwd()),
            "exitCode": return_code,
            "stdoutPreview": _truncate_output(stdout),
            "stderrPreview": _truncate_output(stderr),
            "timedOut": False,
            "durationMs": duration_ms,
            "classifiedRisk": classified.get("risk", "mutating"),
            "readOnly": bool(classified.get("readOnly", False)),
            "mode": normalized_mode,
        },
        "artifacts": [],
    }


def shell_run_piped(command: str, timeout: int = _DEFAULT_TIMEOUT, working_dir: str = "") -> dict[str, Any]:
    """Convenience wrapper that always uses shell mode for piped commands."""
    return shell_run(command, timeout=timeout, use_shell=True, working_dir=working_dir)
