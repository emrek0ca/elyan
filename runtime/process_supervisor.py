"""P0 — İşbirliği yapmayan işler için kill edilebilir worker süreçleri.

Uzun/kilitlenebilir dış işler (subprocess tabanlı yetenekler) kendi process
group'unda başlatılır; timeout/iptalde önce nazik (SIGTERM), cevap yoksa sert
(SIGKILL) olarak TÜM süreç ağacı sonlandırılır. psutil varsa ağaç psutil ile,
yoksa process-group sinyaliyle kapatılır.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from typing import Any, Sequence

from runtime.cancellation import CancellationToken, CancelledError, current_token

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency fallback
    psutil = None  # type: ignore[assignment]

_TERM_GRACE_SECONDS = 2.0


def terminate_process_tree(pid: int, *, grace_seconds: float = _TERM_GRACE_SECONDS) -> dict[str, Any]:
    """PID + tüm alt süreçlerini sonlandırır (terminate → kill).

    Dönen özet: {"terminated": n, "killed": n, "alive": n}.
    """
    summary = {"terminated": 0, "killed": 0, "alive": 0}
    if pid <= 0:
        return summary
    if psutil is not None:
        try:
            root = psutil.Process(pid)
        except Exception:
            return summary
        procs = [root]
        try:
            procs.extend(root.children(recursive=True))
        except Exception:
            pass
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                continue
        try:
            gone, alive = psutil.wait_procs(procs, timeout=max(0.1, grace_seconds))
        except Exception:
            gone, alive = [], procs
        summary["terminated"] = len(gone)
        for proc in alive:
            try:
                proc.kill()
                summary["killed"] += 1
            except Exception:
                summary["alive"] += 1
        return summary
    # psutil yoksa: süreç kendi group'unda başlatıldıysa group sinyali yeter.
    try:
        os.killpg(pid, signal.SIGTERM)
        summary["terminated"] += 1
    except Exception:
        pass
    time.sleep(min(grace_seconds, 1.0))
    try:
        os.killpg(pid, signal.SIGKILL)
        summary["killed"] += 1
    except Exception:
        pass
    return summary


def run_killable_subprocess(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    token: CancellationToken | None = None,
    capture_output: bool = True,
    text: bool = True,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Subprocess'i kendi session/process-group'unda koşar; timeout veya token
    iptalinde süreç AĞACINI gerçekten öldürür (zombie/yetim bırakmaz).

    Timeout/iptalde CancelledError fırlatır — çağıran katman bunu güvenli
    hata sonucuna çevirir; geç kalan çıktı asla başarı sayılmaz.
    """
    active_token = token or current_token()
    process = subprocess.Popen(
        list(command),
        stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture_output else subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        text=text,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )
    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    while True:
        if active_token is not None and active_token.cancelled():
            terminate_process_tree(process.pid)
            process.wait(timeout=5)
            raise CancelledError(active_token.cancellation_reason())
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            terminate_process_tree(process.pid)
            process.wait(timeout=5)
            raise CancelledError("deadline_exceeded")
        try:
            stdout, stderr = process.communicate(timeout=min(0.2, remaining))
            return subprocess.CompletedProcess(list(command), process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            continue
