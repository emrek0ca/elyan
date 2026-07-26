"""Windows ekran yakalama arka ucu — macOS Swift helper'ının karşılığı.

NEDEN
-----
Ekran okuma tek bir yerden besleniyordu: `helpers/elyan Screen Helper.app`,
yani macOS'a özel bir Swift yardımcısı. Windows derlemesinde `helpers/` klasörü
zaten siliniyor (bkz. `scripts/build_desktop_installers.py::copy_sources`), bu
yüzden Windows'ta ekran okuma hiç çalışmıyordu.

TASARIM
-------
Bu modül aynı SÖZLEŞMEYİ üretir: `screen_vision._parse_capture_payload`'un
beklediği JSON gövdesi (`ok/image_path/owner_name/window_title/bounds`).
Böylece üst katmanların (desktop_operator, screen_vision) hiçbir dalı platforma
göre yeniden yazılmaz — yalnız yakalama arka ucu değişir.

BAĞIMLILIK YOK
--------------
Yalnız stdlib `ctypes` (user32/shcore) ve Pillow kullanılır; Pillow zaten
çekirdek bağımlılıktır. Böylece Windows kullanıcısından ek kurulum, derleyici
ya da ayrı bir yardımcı uygulama istenmez.

DPI
---
Windows'ta ölçeklenmiş ekranlarda (125%/150%) süreç DPI-farkında değilse
`GetWindowRect` sanal (ölçeklenmiş) koordinat döndürür ve kırpma kayar —
görüntü yanlış yeri gösterir. Bu yüzden yakalamadan önce süreç per-monitor
DPI-farkında yapılır.
"""

from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

_DPI_READY = False


def _make_dpi_aware() -> None:
    """Süreci per-monitor DPI-farkında yapar (bir kez).

    Başarısız olursa sessiz geçilir: DPI farkındalığı olmadan da görüntü
    alınır, yalnız ölçeklenmiş ekranlarda kırpma kayabilir.
    """
    global _DPI_READY
    if _DPI_READY:
        return
    import ctypes

    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2 (Windows 8.1+)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except Exception:
            pass
    _DPI_READY = True


def _foreground_window_rect() -> tuple[Any, tuple[int, int, int, int] | None]:
    """Ön plandaki pencerenin tutamacı ve ekran koordinatlarındaki dikdörtgeni.

    Görünür çerçeve için önce DWM'e sorulur: `GetWindowRect` Windows 10/11'de
    pencerenin görünmez gölge kenarlarını da içerir ve kırpma fazla geniş çıkar.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, None

    rect = wintypes.RECT()
    # DWMWA_EXTENDED_FRAME_BOUNDS = 9 — gerçek görünür çerçeve.
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(  # type: ignore[attr-defined]
            wintypes.HWND(hwnd),
            ctypes.c_uint(9),
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if rect.right <= rect.left or rect.bottom <= rect.top:
            raise ValueError("empty frame bounds")
    except Exception:
        rect = wintypes.RECT()
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return hwnd, None
    return hwnd, (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))


def _active_window_identity() -> tuple[str, str]:
    """Aktif pencerenin uygulama adı ve başlığı.

    `desktop_os` bu bilgiyi Windows'ta ZATEN üretiyor (ctypes + psutil); burada
    yeniden yazmak yerine o tek kaynak kullanılır.
    """
    try:
        from actions import desktop_os

        payload = desktop_os.desktop_os_active_window().get("result", {})
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("available"):
            return (
                str(payload.get("appName", "") or "").strip(),
                str(payload.get("windowTitle", "") or "").strip(),
            )
    except Exception:
        pass
    return "", ""


def capture_active_window_payload() -> dict[str, Any]:
    """macOS helper'ıyla AYNI sözleşmeyi üreten Windows yakalaması."""
    if sys.platform != "win32":
        return {"ok": False, "detail": "Windows yakalama arka ucu yalnız Windows'ta çalışır."}

    try:
        from PIL import ImageGrab  # type: ignore[reportMissingImports]
    except Exception:
        return {"ok": False, "detail": "Pillow bu kurulumda hazır değil."}

    _make_dpi_aware()
    _hwnd, rect = _foreground_window_rect()
    owner_name, window_title = _active_window_identity()

    try:
        # Pencere dikdörtgeni bilinmiyorsa tüm masaüstü alınır — boş dönmektense
        # daha geniş bir görüntü vermek gözlemi mümkün kılar.
        image = (
            ImageGrab.grab(bbox=rect, all_screens=True)
            if rect
            else ImageGrab.grab(all_screens=True)
        )
    except Exception as exc:
        return {"ok": False, "detail": f"Ekran görüntüsü alınamadı: {exc}"}

    try:
        target = Path(tempfile.gettempdir()) / f"elyan-screen-{uuid.uuid4().hex[:10]}.png"
        image.save(str(target), format="PNG")
    except Exception as exc:
        return {"ok": False, "detail": f"Ekran görüntüsü kaydedilemedi: {exc}"}

    bounds: dict[str, int] = {}
    if rect:
        left, top, right, bottom = rect
        bounds = {"x": left, "y": top, "width": right - left, "height": bottom - top}

    return {
        "ok": True,
        "image_path": str(target),
        "owner_name": owner_name,
        "window_title": window_title,
        "bounds": bounds,
        "detail": "",
    }


def capture_active_window_raw() -> str:
    """Yakalamayı helper'ın döndürdüğü ham JSON biçiminde verir."""
    return json.dumps(capture_active_window_payload(), ensure_ascii=False)
