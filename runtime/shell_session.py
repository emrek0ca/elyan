"""Kalıcı terminal oturumu (P1).

NEDEN VAR
---------
``actions/shell.py`` her çağrıda ``subprocess.run`` yapar: çalışma dizini, ortam
değişkenleri ve kabuk durumu çağrılar arasında KAYBOLUR. Bu yüzden "gerçek
yazılım görevi" (SWE-bench sınıfı) imkânsızdı — çünkü o işler şunu gerektirir:

    cd repo → testi çalıştır → çıktıyı oku → dosyayı düzelt → testi TEKRAR çalıştır

Bu modül oturum durumunu (cwd + env) kalıcı tutar ve ajan döngüsüne
"çalıştır → gözlemle → düzelt" halkasını kazandırır.

GÜVENLİK
--------
* Oturum başına komut sayısı ve toplam süre sınırlıdır.
* Her komut kendi zaman aşımına sahiptir; asılı komut oturumu kilitlemez.
* Çıktı kırpılır (bağlam şişmesi + sızıntı koruması).
* ``cd`` deterministik olarak yorumlanır; kök dışına çıkış engellenebilir.
* Bu modül İZİN VERMEZ — çağıran taraf (safety_policy / onay kapısı) yetkiyi
  zaten doğrulamış olmalıdır. Burada yalnız durum yönetimi vardır.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SHELL_SESSION_CONTRACT = "elyan.shell_session.v1"

DEFAULT_COMMAND_TIMEOUT = 120
MAX_COMMAND_TIMEOUT = 600
MAX_OUTPUT_CHARS = 16_000
MAX_COMMANDS_PER_SESSION = 200
SESSION_IDLE_TIMEOUT_SECONDS = 3_600.0

# Oturum durumunu kalıcı olarak bozacak / etkileşim bekleyen komutlar.
_INTERACTIVE_BLOCKLIST = (
    "vim", "vi", "nano", "emacs", "less", "more", "top", "htop",
    "ssh", "telnet", "ftp", "python -i", "node -i", "irb",
)


def _clip_output(value: str, limit: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    text = str(value or "")
    if len(text) <= limit:
        return text, False
    half = limit // 2
    return (
        text[:half] + "\n…[çıktı kırpıldı]…\n" + text[-half:],
        True,
    )


@dataclass(slots=True)
class ShellSession:
    """Tek bir kalıcı kabuk oturumu (cwd + env taşır)."""

    session_id: str
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    root: Path | None = None
    created_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)
    command_count: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    def touch(self) -> None:
        self.last_used_at = time.monotonic()

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_used_at

    def snapshot(self) -> dict[str, Any]:
        return {
            "contract": SHELL_SESSION_CONTRACT,
            "sessionId": self.session_id,
            "cwd": str(self.cwd),
            "commandCount": self.command_count,
            "idleSeconds": round(self.idle_seconds, 1),
            "recentCommands": [item.get("command", "") for item in self.history[-8:]],
        }


class ShellSessionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ShellSessionManager:
    """Oturumları kimliğe göre saklar; boşta kalanları temizler."""

    def __init__(self) -> None:
        self._sessions: dict[str, ShellSession] = {}

    def open(
        self,
        *,
        cwd: str = "",
        root: str = "",
        env: dict[str, str] | None = None,
        session_id: str = "",
    ) -> ShellSession:
        self.sweep()
        resolved_cwd = Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()
        if not resolved_cwd.is_dir():
            raise ShellSessionError(
                "INVALID_ARGUMENT", f"Çalışma dizini bulunamadı: {resolved_cwd}"
            )
        resolved_root = Path(root).expanduser().resolve() if root else None
        if resolved_root is not None and not _is_within(resolved_cwd, resolved_root):
            raise ShellSessionError(
                "ACCESS_DENIED", "Çalışma dizini izin verilen kökün dışında."
            )
        base_env = dict(os.environ)
        if env:
            base_env.update({str(k): str(v) for k, v in env.items()})
        # Etkileşimsiz, öngörülebilir çıktı için.
        base_env.setdefault("CI", "1")
        base_env.setdefault("TERM", "dumb")
        base_env.setdefault("PAGER", "cat")
        base_env.setdefault("GIT_PAGER", "cat")

        identifier = str(session_id or "").strip() or f"sh_{uuid.uuid4().hex[:12]}"
        session = ShellSession(
            session_id=identifier,
            cwd=resolved_cwd,
            env=base_env,
            root=resolved_root,
        )
        self._sessions[identifier] = session
        return session

    def get(self, session_id: str) -> ShellSession:
        session = self._sessions.get(str(session_id or "").strip())
        if session is None:
            raise ShellSessionError("NOT_FOUND", "Terminal oturumu bulunamadı veya süresi doldu.")
        return session

    def close(self, session_id: str) -> bool:
        return self._sessions.pop(str(session_id or "").strip(), None) is not None

    def sweep(self) -> int:
        stale = [
            key
            for key, session in self._sessions.items()
            if session.idle_seconds > SESSION_IDLE_TIMEOUT_SECONDS
        ]
        for key in stale:
            self._sessions.pop(key, None)
        return len(stale)

    def list_sessions(self) -> list[dict[str, Any]]:
        return [session.snapshot() for session in self._sessions.values()]

    # ── Yürütme ────────────────────────────────────────────────────────────
    def run(
        self,
        session_id: str,
        command: str,
        *,
        timeout: int = DEFAULT_COMMAND_TIMEOUT,
    ) -> dict[str, Any]:
        session = self.get(session_id)
        raw = str(command or "").strip()
        if not raw:
            raise ShellSessionError("INVALID_ARGUMENT", "Komut boş olamaz.")
        if session.command_count >= MAX_COMMANDS_PER_SESSION:
            raise ShellSessionError(
                "LIMIT_EXCEEDED", "Oturum komut sınırına ulaştı; yeni oturum aç."
            )
        lowered = raw.lower()
        for blocked in _INTERACTIVE_BLOCKLIST:
            if lowered == blocked or lowered.startswith(f"{blocked} "):
                raise ShellSessionError(
                    "INTERACTIVE_COMMAND_BLOCKED",
                    f"Etkileşimli komut desteklenmiyor: {blocked}. Etkileşimsiz bir eşdeğerini kullan.",
                )

        bounded_timeout = max(1, min(int(timeout or DEFAULT_COMMAND_TIMEOUT), MAX_COMMAND_TIMEOUT))

        # `cd` kabuk durumu değiştirir → deterministik olarak biz yorumlarız.
        directive = _parse_cd(raw)
        if directive is not None:
            return self._change_directory(session, directive)

        started = time.monotonic()
        try:
            completed = subprocess.run(  # noqa: S602 - kasıtlı kabuk; yetki üst katmanda
                raw,
                shell=True,
                cwd=str(session.cwd),
                env=session.env,
                capture_output=True,
                text=True,
                timeout=bounded_timeout,
            )
            stdout, truncated_out = _clip_output(completed.stdout)
            stderr, truncated_err = _clip_output(completed.stderr)
            exit_code = int(completed.returncode)
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            stdout, truncated_out = _clip_output(exc.stdout or "")
            stderr, truncated_err = _clip_output(exc.stderr or "")
            exit_code = 124
            timed_out = True

        duration_ms = int((time.monotonic() - started) * 1000)
        session.command_count += 1
        session.touch()
        record = {
            "command": raw[:400],
            "exitCode": exit_code,
            "durationMs": duration_ms,
            "timedOut": timed_out,
        }
        session.history.append(record)

        return {
            "ok": exit_code == 0 and not timed_out,
            "sessionId": session.session_id,
            "command": raw,
            "cwd": str(session.cwd),
            "exitCode": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "timedOut": timed_out,
            "truncated": bool(truncated_out or truncated_err),
            "durationMs": duration_ms,
            "commandCount": session.command_count,
        }

    def _change_directory(self, session: ShellSession, target: str) -> dict[str, Any]:
        candidate = Path(target).expanduser()
        if not candidate.is_absolute():
            candidate = session.cwd / candidate
        resolved = candidate.resolve()
        if not resolved.is_dir():
            return {
                "ok": False,
                "sessionId": session.session_id,
                "command": f"cd {target}",
                "cwd": str(session.cwd),
                "exitCode": 1,
                "stdout": "",
                "stderr": f"cd: dizin yok: {target}",
                "timedOut": False,
                "truncated": False,
                "durationMs": 0,
                "commandCount": session.command_count,
            }
        if session.root is not None and not _is_within(resolved, session.root):
            raise ShellSessionError(
                "ACCESS_DENIED", "Bu dizin izin verilen kökün dışında."
            )
        session.cwd = resolved
        session.command_count += 1
        session.touch()
        session.history.append({"command": f"cd {target}", "exitCode": 0, "durationMs": 0})
        return {
            "ok": True,
            "sessionId": session.session_id,
            "command": f"cd {target}",
            "cwd": str(resolved),
            "exitCode": 0,
            "stdout": str(resolved),
            "stderr": "",
            "timedOut": False,
            "truncated": False,
            "durationMs": 0,
            "commandCount": session.command_count,
        }


def _parse_cd(command: str) -> str | None:
    """Salt ``cd <dizin>`` ise hedefi döndürür; değilse None.

    Zincirli komutlar (``cd x && make``) kabuğa bırakılır — onların cwd etkisi
    zaten tek komut ömrüyle sınırlıdır ve oturum dizinini değiştirmemelidir."""
    stripped = command.strip()
    if not stripped.startswith("cd"):
        return None
    if any(token in stripped for token in ("&&", "||", ";", "|")):
        return None
    try:
        parts = shlex.split(stripped)
    except ValueError:
        return None
    if not parts or parts[0] != "cd":
        return None
    if len(parts) == 1:
        return str(Path.home())
    if len(parts) != 2:
        return None
    return parts[1]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


# Süreç ömrü boyunca paylaşılan yönetici.
SESSIONS = ShellSessionManager()
