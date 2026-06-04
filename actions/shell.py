from __future__ import annotations

import os
import shlex
import subprocess

from runtime.capability_registry import SafeCapabilityError

_BLOCKED_SNIPPETS = (
    "rm -rf /",
    "sudo rm -rf",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    "shutdown",
    "reboot",
    "halt",
    "diskutil erase",
    "diskutil apfs deletecontainer",
)
_BLOCKED_PREFIXES = (
    "rm ",
    "mv ",
    "cp ",
    "chmod ",
    "chown ",
    "sudo ",
    "del ",
    "erase ",
    "copy ",
    "move ",
)
_METACHAR_SNIPPETS = ("&&", "||", "|", ";", "`", "$(", ">", "<", "\n", "\r", "&")


def _parse_command(command: str) -> list[str]:
    stripped = str(command or "").strip()
    if not stripped:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Komut belirtilmedi.")

    lowered = stripped.lower()
    if any(lowered.startswith(prefix) for prefix in _BLOCKED_PREFIXES):
        raise SafeCapabilityError(
            "INVALID_ARGUMENT",
            "Dosya veya yetki değiştiren komutlar doğrudan çalıştırılmıyor.",
        )
    if any(snippet in lowered for snippet in _BLOCKED_SNIPPETS):
        raise SafeCapabilityError("INVALID_ARGUMENT", "Bu komut güvenlik nedeniyle engellendi.")
    if any(snippet in stripped for snippet in _METACHAR_SNIPPETS):
        raise SafeCapabilityError(
            "INVALID_ARGUMENT",
            "Shell operatörleri desteklenmiyor. Basit argv komutu kullan.",
        )

    try:
        argv = shlex.split(stripped, posix=os.name != "nt")
    except ValueError as exc:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Komut güvenli şekilde ayrıştırılamadı.") from exc
    if not argv:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Komut belirtilmedi.")
    return argv


def shell_run(command: str, timeout: int = 30) -> str:
    argv = _parse_command(command)
    try:
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SafeCapabilityError("TIMEOUT", f"Komut zaman aşımına uğradı ({timeout}s).") from exc
    except FileNotFoundError as exc:
        raise SafeCapabilityError("INVALID_ARGUMENT", f"Komut bulunamadı: {argv[0]}") from exc
    except Exception as exc:
        raise SafeCapabilityError("TOOL_EXECUTION_FAILED", "Komut güvenli şekilde çalıştırılamadı.") from exc

    output = (result.stdout + result.stderr).strip()
    if not output:
        return "Komut başarıyla çalıştı (çıktı yok)."
    if len(output) > 800:
        output = output[:800] + "\n... (çıktı kısaltıldı)"
    return output
