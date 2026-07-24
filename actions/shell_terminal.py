"""Kalıcı terminal oturumu yetenekleri (P1).

``shell_run`` tek atışlıktır: her çağrıda cwd/env sıfırlanır. Bu modül oturum
durumunu koruyan yetenekleri sunar; böylece ajan döngüsü şu halkayı kurabilir:

    cd repo → testi çalıştır → çıktıyı oku → düzelt → testi TEKRAR çalıştır

Yetki bu katmanda verilmez: ``shell_session_run`` yan etkili sayılır ve onay
kapısından geçer (bkz. capability_registry ``_SIDE_EFFECT_CAPABILITIES``).
"""

from __future__ import annotations

from typing import Any

from runtime.capability_registry import SafeCapabilityError
from runtime.shell_session import (
    DEFAULT_COMMAND_TIMEOUT,
    SESSIONS,
    ShellSessionError,
)


def _fail(exc: ShellSessionError) -> "SafeCapabilityError":
    return SafeCapabilityError(exc.code, exc.message)


def shell_session_open(
    working_dir: str = "",
    root: str = "",
    session_id: str = "",
    **_kwargs: Any,
) -> dict[str, Any]:
    """Kalıcı bir terminal oturumu açar (cwd + ortam korunur)."""
    try:
        session = SESSIONS.open(cwd=working_dir, root=root, session_id=session_id)
    except ShellSessionError as exc:
        raise _fail(exc) from exc
    snapshot = session.snapshot()
    return {
        "text": f"Terminal oturumu açıldı: {session.cwd}",
        "result": {"kind": "shell_session", **snapshot},
        "artifacts": [],
    }


def shell_session_run(
    command: str = "",
    session_id: str = "",
    timeout: int = DEFAULT_COMMAND_TIMEOUT,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Açık oturumda komut çalıştırır; cwd ve ortam çağrılar arası korunur."""
    if not str(session_id or "").strip():
        raise SafeCapabilityError(
            "INVALID_ARGUMENT",
            "Önce shell_session_open ile bir oturum aç ve sessionId'yi ver.",
        )
    try:
        outcome = SESSIONS.run(session_id, command, timeout=int(timeout or DEFAULT_COMMAND_TIMEOUT))
    except ShellSessionError as exc:
        raise _fail(exc) from exc

    stdout = str(outcome.get("stdout", "") or "")
    stderr = str(outcome.get("stderr", "") or "")
    # Model için tek gövdede birleşik, sınırlı çıktı: exit kodu + akışlar.
    body = stdout if stdout.strip() else ""
    if stderr.strip():
        body = f"{body}\n[stderr]\n{stderr}" if body else f"[stderr]\n{stderr}"
    summary = body.strip() or f"(çıktı yok, exit={outcome.get('exitCode')})"

    # Zaman aşımı GERÇEK bir arızadır: komut tamamlanmadı, çıktı güvenilmez.
    if outcome.get("timedOut"):
        raise SafeCapabilityError(
            "TIMEOUT",
            f"Komut zaman aşımına uğradı · {summary[:800]}",
        )

    # SIFIR OLMAYAN EXIT KODU ARIZA DEĞİLDİR.
    # `pytest`/`tsc`/`grep` gibi araçlar başarısızlığı exit≠0 ile bildirir; bu
    # ajan için BİLGİDİR ("2 test kırık"), araç hatası değil. Hataya çevirirsek
    # "testi çalıştır → çıktıyı oku → düzelt → tekrar" döngüsü imkânsızlaşır:
    # ajan gerçek işi yapmak yerine aracı yeniden denemekle uğraşır.
    exit_code = int(outcome.get("exitCode", 0) or 0)
    header = f"exit={exit_code}" + (" (komut başarısız bildirdi)" if exit_code else "")
    return {
        "text": f"{header}\n{summary}"[:4000],
        "result": {
            "kind": "shell_session_run",
            **outcome,
            # Model bunu açıkça görsün: komut çalıştı ama başarısız bildirdi.
            "commandFailed": exit_code != 0,
        },
        "artifacts": [],
    }


def shell_session_close(session_id: str = "", **_kwargs: Any) -> dict[str, Any]:
    """Oturumu kapatır ve durumunu serbest bırakır."""
    closed = SESSIONS.close(session_id)
    return {
        "text": "Terminal oturumu kapatıldı." if closed else "Oturum zaten kapalı.",
        "result": {"kind": "shell_session_close", "closed": bool(closed)},
        "artifacts": [],
    }
