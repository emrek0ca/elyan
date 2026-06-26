from __future__ import annotations

import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path

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


def shell_run(
    command: str,
    timeout: int = _DEFAULT_TIMEOUT,
    *,
    use_shell: bool = False,
    working_dir: str = "",
) -> str:
    """Execute a shell command and return combined stdout+stderr.

    By default runs argv-parsed (safe). Set use_shell=True for piped/complex commands.
    """
    stripped = str(command or "").strip()
    if not stripped:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Komut belirtilmedi.")

    if _is_hard_blocked(stripped):
        raise SafeCapabilityError("INVALID_ARGUMENT", "Bu komut güvenlik nedeniyle engellenmiştir.")

    if _is_elevated(stripped):
        raise SafeCapabilityError(
            "INVALID_ARGUMENT",
            "Yükseltilmiş yetkili komutlar (sudo/su) doğrudan çalıştırılamaz.",
        )

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
            try:
                argv = shlex.split(stripped, posix=(os.name != "nt"))
            except ValueError as exc:
                raise SafeCapabilityError("INVALID_ARGUMENT", "Komut ayrıştırılamadı.") from exc

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
        result = subprocess.run(argv, **run_kwargs)
    except subprocess.TimeoutExpired as exc:
        raise SafeCapabilityError("TIMEOUT", f"Komut zaman aşımına uğradı ({timeout}s).") from exc
    except FileNotFoundError as exc:
        first_word = stripped.split()[0] if stripped else "komut"
        raise SafeCapabilityError("INVALID_ARGUMENT", f"Komut bulunamadı: {first_word}") from exc
    except SafeCapabilityError:
        raise
    except Exception as exc:
        raise SafeCapabilityError("TOOL_EXECUTION_FAILED", f"Komut çalıştırılamadı: {exc}") from exc

    combined = (result.stdout or "") + (result.stderr or "")
    output = _truncate_output(combined)

    return_code = int(getattr(result, "returncode", 0) or 0)
    if return_code != 0 and not result.stdout.strip():
        exit_note = f"[çıkış kodu: {return_code}]"
        return f"{output}\n{exit_note}" if output else exit_note

    return output


def shell_run_piped(command: str, timeout: int = _DEFAULT_TIMEOUT, working_dir: str = "") -> str:
    """Convenience wrapper that always uses shell mode for piped commands."""
    return shell_run(command, timeout=timeout, use_shell=True, working_dir=working_dir)
