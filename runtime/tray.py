"""
Sistem tepsisi / menü çubuğu ikonu — daemon'un tek görünür yüzü (3 platform).

GUI yok: pystray ile macOS menü çubuğunda, Windows sistem tepsisinde ve
Linux'ta (AppIndicator/GTK/X11) küçük bir ikon durur; menüde bağlantı durumu
ve aktif görevler görünür. Veri kaynağı STATE dosyasıdır (bridge relay
thread'i görevleri oraya işler) — tray hiçbir iş mantığı taşımaz, yalnız
gösterir. Menü her açılışta taze kurulur (pystray dinamik Menu üreticisi).

pystray macOS'ta ana thread ister (AppKit run loop); daemon bunu bilerek
çağırır (runtime/daemon.py: bekçi döngüsü yan thread'e alınır).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - yalnız tip denetimi
    from runtime.daemon import ElyanDaemon

_STATUS_LABELS = {
    "ready": "Bağlı",
    "online": "Bağlı",
    "connected": "Bağlı",
    "reconnecting": "Yeniden bağlanıyor…",
    "offline": "Çevrimdışı",
    "stopped": "Durduruldu",
    "degraded": "Kısıtlı",
}

_TASK_STATUS_LABELS = {
    "queued": "sırada",
    "planning": "planlanıyor",
    "running": "çalışıyor",
    "waiting_approval": "onay bekliyor",
    "completed": "tamamlandı",
    "failed": "başarısız",
    "canceled": "iptal",
}


def _load_icon_image() -> Any:
    """Repo logosundan tepsi ikonu; bulunamazsa basit bir E rozeti çizer."""
    from PIL import Image, ImageDraw

    logo = Path(__file__).resolve().parent.parent / "logo.png"
    if logo.exists():
        try:
            image = Image.open(logo).convert("RGBA")
            image.thumbnail((64, 64), Image.LANCZOS)
            return image
        except Exception:
            pass
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 60, 60), fill=(30, 30, 28, 255))
    draw.text((22, 14), "E", fill=(242, 238, 229, 255))
    return image


def run_tray(daemon: "ElyanDaemon") -> bool:
    """Tepsi ikonunu ana thread'te çalıştırır. pystray kurulamazsa / görüntü
    sunucusu yoksa (başsız Linux) False döner — çağıran saf arka plan
    döngüsüne düşer."""
    try:
        import pystray
    except Exception:
        return False

    from runtime.daemon import runtime_status_summary

    def _summary() -> dict[str, Any]:
        try:
            return runtime_status_summary()
        except Exception:
            return {}

    def _menu_items() -> Any:
        summary = _summary()
        lifecycle = str(summary.get("lifecycleState", "") or "stopped")
        label = _STATUS_LABELS.get(lifecycle, lifecycle)
        email = str(summary.get("email", "") or "")
        status_line = f"Durum: {label}" + (f" · {email}" if email else "")
        active = summary.get("activeTasks", []) or []

        yield pystray.MenuItem(status_line, None, enabled=False)
        yield pystray.Menu.SEPARATOR
        if active:
            yield pystray.MenuItem(f"Aktif görevler ({len(active)})", None, enabled=False)
            for task in active[:8]:
                title = str(task.get("title", "") or "Görev")[:48]
                status = _TASK_STATUS_LABELS.get(
                    str(task.get("status", "")), str(task.get("status", ""))
                )
                yield pystray.MenuItem(f"  {title} — {status}", None, enabled=False)
        else:
            yield pystray.MenuItem("Aktif görev yok", None, enabled=False)
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Elyan'ı Durdur", _quit)

    def _quit(icon: Any, _item: Any = None) -> None:
        daemon.stop()
        icon.stop()

    icon = pystray.Icon(
        "elyan",
        icon=_load_icon_image(),
        title="Elyan",
        menu=pystray.Menu(_menu_items),
    )

    def _refresh_tooltip(icon_ref: Any) -> None:
        # Görev sayısını araç ipucuna yansıt (Windows'ta hover, macOS'ta
        # erişilebilirlik). Menü zaten her açılışta taze kurulur.
        summary = _summary()
        active = summary.get("activeTasks", []) or []
        icon_ref.title = "Elyan" if not active else f"Elyan — {len(active)} aktif görev"

    def _setup(icon_ref: Any) -> None:
        icon_ref.visible = True
        import threading

        def _tick() -> None:
            while icon_ref.visible and not daemon._stop.is_set():
                try:
                    _refresh_tooltip(icon_ref)
                except Exception:
                    pass
                daemon._stop.wait(5)

        threading.Thread(target=_tick, name="elyan-tray-tick", daemon=True).start()

    try:
        icon.run(setup=_setup)
    except Exception:
        # Başsız oturum (SSH / display yok) veya tepsi arka ucu kurulamadı.
        return False
    return True
