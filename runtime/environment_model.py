"""Dünya modeli — bu MAKİNENİN gerçekleri.

NEDEN
-----
Model "PDF nasıl birleştirilir"i zaten bilir; bilmediği şey *bu makinede* neyin
kurulu olduğudur. Ortam bilgisi olmadan üretilen terminal komutu tahmindir:
`apt-get` yazan bir plan macOS'ta, `brew` yazan bir plan Linux'ta çöker.

Bu modül ortamı BİR KEZ keşfeder (TTL'li cache) ve sınırlı bir gerçek kümesi
üretir: platform, kabuk, paket yöneticisi, mevcut temel araçlar, ev/masaüstü
dizinleri. Kural listesi DEĞİLDİR — model neyi nasıl yapacağına kendisi karar
verir, biz yalnız zemini veririz.

GİZLİLİK: yalnız araç VARLIĞI ve platform bilgisi taşınır; dosya içeriği,
kullanıcı adı dışındaki kimlik verisi veya dizin dökümü çıkarılmaz.
"""

from __future__ import annotations

import datetime as dt
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

ENVIRONMENT_CONTRACT = "elyan.environment.v1"

# Keşif ucuz ama bedava değil; ortam bir oturum boyunca sabittir.
ENVIRONMENT_TTL_MINUTES = 720

# Varlığı komut kurmayı gerçekten değiştiren araçlar. Liste "şu araç varsa şunu
# yap" kuralı değil; modele sunulan ORTAM GERÇEĞİDİR.
_PROBED_TOOLS = (
    "brew", "apt-get", "winget", "git", "python3", "node", "npm",
    "pytest", "docker", "rg", "curl", "ffmpeg",
)

_PACKAGE_MANAGERS = {"darwin": "brew", "linux": "apt-get", "windows": "winget"}


def _platform_key() -> str:
    if sys.platform.startswith("darwin"):
        return "darwin"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


def discover_environment() -> dict[str, Any]:
    """Ortamı canlı prob'larla keşfeder (cache'siz)."""
    key = _platform_key()
    facts: dict[str, Any] = {
        "contract": ENVIRONMENT_CONTRACT,
        "platform": key,
        "osRelease": platform.release()[:32],
        "discoveredAt": dt.datetime.now().isoformat(timespec="seconds"),
    }
    if key == "darwin":
        facts["shell"] = "zsh"
    elif key == "windows":
        facts["shell"] = "powershell"
    else:
        facts["shell"] = "bash"

    available = [tool for tool in _PROBED_TOOLS if shutil.which(tool)]
    if available:
        facts["tools"] = available
    manager = _PACKAGE_MANAGERS.get(key, "")
    if manager and manager in available:
        facts["packageManager"] = manager

    try:
        from actions._write_common import desktop_dir

        facts["desktopDir"] = str(desktop_dir())
    except Exception:
        pass
    try:
        facts["homeDir"] = str(Path.home())
    except Exception:
        pass
    return facts


def _cached(state: dict[str, Any] | None, *, now: dt.datetime) -> dict[str, Any] | None:
    runtime = (state or {}).get("runtime") if isinstance(state, dict) else None
    cached = runtime.get("environment") if isinstance(runtime, dict) else None
    if not isinstance(cached, dict) or cached.get("contract") != ENVIRONMENT_CONTRACT:
        return None
    raw = str(cached.get("discoveredAt", "") or "").strip()
    if not raw:
        return None
    try:
        discovered = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if discovered.tzinfo is not None:
            discovered = discovered.replace(tzinfo=None)
    except ValueError:
        return None
    age_minutes = (now - discovered).total_seconds() / 60
    if age_minutes < -5 or age_minutes > ENVIRONMENT_TTL_MINUTES:
        return None
    return cached


def environment_facts(
    state: dict[str, Any] | None = None,
    *,
    now: dt.datetime | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Ortam gerçeklerini döndürür; TTL içindeyse cache'ten, değilse keşfeder.

    Keşif başarısız olursa asgari platform bilgisiyle döner — çağıran hiçbir
    zaman boş/None ile uğraşmaz, ama uydurma gerçek de üretilmez."""
    moment = now or dt.datetime.now()
    cached = _cached(state, now=moment)
    if cached is not None:
        return cached
    try:
        facts = discover_environment()
    except Exception:
        return {"contract": ENVIRONMENT_CONTRACT, "platform": _platform_key()}
    if persist:
        try:
            from runtime import state_store

            state_store.update_state({"runtime": {"environment": facts}})
        except Exception:  # pragma: no cover - cache yazımı akışı düşürmesin
            pass
    return facts


def to_prompt_context(facts: dict[str, Any]) -> dict[str, Any]:
    """Modele gidecek sınırlı biçim (keşif zaman damgası taşınmaz)."""
    payload = {
        key: facts[key]
        for key in ("platform", "shell", "packageManager", "desktopDir")
        if facts.get(key)
    }
    tools = facts.get("tools")
    if isinstance(tools, list) and tools:
        payload["availableTools"] = tools[:12]
    return payload
