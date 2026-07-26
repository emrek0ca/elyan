"""Windows takvim arka ucu — macOS EventKit helper'ının karşılığı.

NEDEN
-----
Takvim tek bir yerden besleniyordu: `helpers/elyan Calendar Helper.app`, yani
macOS EventKit'e bağlı bir Swift yardımcısı. Windows derlemesinde `helpers/`
klasörü siliniyor, dolayısıyla Windows'ta takvim hiç okunamıyordu. Bu, yalnız
"takvim sor" komutunu değil DURUMSAL BAĞLAMI da sakatlıyordu: yaklaşan toplantı
sinyali `situational_context` üzerinden belge başlığına ve canlılık ipuçlarına
kadar gidiyor (bkz. NEREDE-KALDIK §4.6).

TASARIM
-------
Resmi Windows SDK projeksiyonu (PyWinRT) üzerinden sistem
``AppointmentStore``'u okunur — Outlook/Microsoft hesabı Windows'ta
kuruluysa etkinlikler oradan gelir. Üretilen JSON, macOS helper'ının
sözleşmesiyle AYNIdır (``ok``/``events[]`` + ``start_ts``/``end_ts``), böylece
``calendar._parse_payload`` değişmeden çalışır.

KAPSAM (dürüst sınır)
---------------------
Bu arka uç **okumadır**. Windows'ta etkinlik ekleme/silme, WinRT tarafında
kullanıcı onayı isteyen bir UI akışına (``AppointmentManager.show*``) dayanır ve
başsız bir daemon'dan güvenilir biçimde sürülemez. Yazma işlemleri bu yüzden
"desteklenmiyor" diye AÇIKÇA reddedilir — sessizce başarısız olmak ya da
yapılmamış bir şeyi yapılmış göstermek yasak.

BAĞIMLILIK
----------
``winrt-Windows.ApplicationModel.Appointments`` (+ ``winrt-runtime``) yalnız
Windows'ta ve opsiyonel olarak kurulur; wheel'i vardır, derleyici istemez.
Paket yoksa katman "kullanılamıyor" der — çökmez, uydurmaz.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from typing import Any

_UNAVAILABLE_DETAIL = (
    "Windows takvim erişimi için gerekli bileşen kurulu değil. "
    "`elyan doctor` çalıştırıp eksik paketleri tamamlayabilirsin."
)
_PERMISSION_DETAIL = (
    "Windows takvim erişimine izin verilmedi. Ayarlar > Gizlilik ve güvenlik > "
    "Takvim bölümünden uygulama erişimini aç ve tekrar dene."
)


def _run_async(operation: Any) -> Any:
    """WinRT asenkron işlemini bloklayarak sonuçlandırır.

    PyWinRT işlemleri ``await`` edilebilir; daemon tarafı senkron olduğu için
    burada kısa ömürlü bir event loop ile beklenir.
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        # Zaten bir döngü içindeysek onu bloklamak yerine ayrı döngü kullanılır.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(_await(operation))).result()
    return asyncio.run(_await(operation))


async def _await(operation: Any) -> Any:
    return await operation


def _to_timestamp(value: Any) -> int:
    """WinRT DateTime/timedelta değerini POSIX saniyesine çevirir."""
    if value is None:
        return 0
    if isinstance(value, dt.datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
        return int(moment.timestamp())
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _duration_seconds(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, dt.timedelta):
        return int(value.total_seconds())
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def read_events(start: dt.datetime, end: dt.datetime) -> dict[str, Any]:
    """Verilen aralıktaki etkinlikleri macOS helper sözleşmesiyle döndürür."""
    if sys.platform != "win32":
        return {"ok": False, "detail": "Windows takvim arka ucu yalnız Windows'ta çalışır."}

    try:
        from winrt.windows.applicationmodel.appointments import (  # type: ignore[reportMissingImports]
            AppointmentManager,
            AppointmentStoreAccessType,
        )
    except Exception:
        return {"ok": False, "detail": _UNAVAILABLE_DETAIL}

    try:
        store = _run_async(
            AppointmentManager.request_store_async(
                AppointmentStoreAccessType.APPOINTMENTS_READ_WRITE
            )
        )
    except Exception:
        # İzin reddi ve "mağaza yok" durumu WinRT'de aynı istisnaya düşebilir;
        # kullanıcıya eyleme dönük olanı söyle.
        return {"ok": False, "detail": _PERMISSION_DETAIL}

    if store is None:
        return {"ok": False, "detail": _PERMISSION_DETAIL}

    span = end - start
    if span.total_seconds() <= 0:
        span = dt.timedelta(days=1)

    try:
        appointments = _run_async(
            store.find_appointments_async(
                start.astimezone(dt.timezone.utc),
                span,
            )
        )
    except Exception as exc:
        return {"ok": False, "detail": f"Takvim okunamadı: {exc}"}

    events: list[dict[str, Any]] = []
    for item in appointments or []:
        try:
            start_ts = _to_timestamp(getattr(item, "start_time", None))
            if start_ts <= 0:
                continue
            duration = _duration_seconds(getattr(item, "duration", None))
            end_ts = start_ts + (duration if duration > 0 else 3600)
            events.append(
                {
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "calendar": str(getattr(item, "calendar_id", "") or "").strip(),
                    "title": str(getattr(item, "subject", "") or "").strip(),
                    "location": str(getattr(item, "location", "") or "").strip(),
                    "all_day": bool(getattr(item, "all_day", False)),
                }
            )
        except Exception:
            # Tek bir bozuk kayıt tüm listeyi düşürmesin.
            continue

    return {"ok": True, "events": events, "detail": ""}


def read_events_raw(start: dt.datetime, end: dt.datetime) -> str:
    return json.dumps(read_events(start, end), ensure_ascii=False)


def unsupported_write_raw(action: str) -> str:
    """Yazma işlemleri için AÇIK reddetme.

    Sessiz başarısızlık ya da "eklendi" demek yasaktır: kullanıcı etkinliğin
    takvimine girdiğini sanıp toplantıyı kaçırır.
    """
    return json.dumps(
        {
            "ok": False,
            "detail": (
                f"Windows'ta takvime {action} işlemi henüz desteklenmiyor; "
                "takvim burada salt okunur çalışıyor."
            ),
        },
        ensure_ascii=False,
    )
