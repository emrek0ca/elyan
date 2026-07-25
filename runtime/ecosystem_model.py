"""Ekosistem modeli — Elyan'ın kendi organizmasını tanıması.

NEDEN
-----
Elyan tek bir program değil, **üç yüzeyli tek bir organizmadır**: mobil (yüz),
backend (paylaşılan beyin), masaüstü (eller). Model bugüne kadar bunu
bilmiyordu; sonuç: mobilden gelen bir isteğe "terminali açtım" diyebiliyor
(eller bağlı değilken), ya da masaüstünde yapılabilecek bir işi "yapamam" diye
reddedebiliyordu. Yani sınırını da gücünü de yanlış biliyordu.

Bu modül üç şeyi verir:
  1. **Topoloji** — hangi yüzey neyi yapar (mimari bilgi; kelime deseni değil)
  2. **Canlı durum** — o yüzey ŞU AN erişilebilir mi (eşleşme, backend, izin)
  3. **Teslimat sonucu** — istenen iş için gereken yüzey yoksa NE SÖYLENECEĞİ

DEĞİŞMEZ
--------
Durum alanları CANLI sinyallerden okunur; "bağlı" iddiası asla varsayılmaz.
Yüzey erişilemezse model bunu bilir ve **yapabilirmiş gibi konuşmaz** — bu,
uydurma teslimatın (P0 hata sınıfı) kökündeki bilgi eksikliğidir.
"""

from __future__ import annotations

from typing import Any

ECOSYSTEM_CONTRACT = "elyan.ecosystem.v1"

# Topoloji: mimari gerçek. Her yüzeyin SORUMLULUK alanı — bu bir "şu kelime
# geçerse şuraya git" tablosu değildir; organizmanın anatomisidir. Model işin
# doğasını kendi çözer, buradan yalnız NEREDE yapılabileceğini öğrenir.
SURFACES: dict[str, dict[str, Any]] = {
    "mobile": {
        "role": "yüz",
        "does": "kullanıcıyla konuşur, istek başlatır, sonucu gösterir",
        "cannot": "işletim sistemine dokunamaz",
    },
    "backend": {
        "role": "paylaşılan beyin",
        "does": (
            "anlama/planlama üretir, hafıza ve arama tutar, bağlayıcılarla "
            "(Gmail/Takvim/Drive) çalışır, işi masaüstüne dağıtır"
        ),
        "cannot": "kullanıcının makinesindeki dosya/uygulamalara doğrudan erişemez",
    },
    "desktop": {
        "role": "eller",
        "does": (
            "dosya/klasör, uygulama, terminal, ekran ve yerel araçlar — "
            "gerçek dünyadaki değişiklikler burada olur"
        ),
        "cannot": "kullanıcı orada değilken/eşleşme yokken çalışamaz",
    },
}


def _bool(value: Any) -> bool:
    return value is True


def assess(state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ekosistemin ŞU ANKİ hâli — her alan canlı sinyalden okunur."""
    state = state if isinstance(state, dict) else {}
    runtime = state.get("runtime") if isinstance(state.get("runtime"), dict) else {}
    pairing = state.get("pairing") if isinstance(state.get("pairing"), dict) else {}

    desktop_ready = _bool(runtime.get("ready")) or str(
        runtime.get("lifecycleState", "") or ""
    ).strip().lower() in {"online", "ready", "running"}
    connected_devices = pairing.get("connectedDevices")
    mobile_linked = isinstance(connected_devices, list) and len(connected_devices) > 0
    backend_reachable = bool(str(runtime.get("runtimeToken", "") or "").strip()) or _bool(
        runtime.get("websocketConnected")
    )

    surfaces: dict[str, Any] = {}
    for name, spec in SURFACES.items():
        available = {
            "mobile": mobile_linked,
            "backend": backend_reachable,
            "desktop": desktop_ready,
        }[name]
        entry = {"role": spec["role"], "does": spec["does"], "available": available}
        if not available:
            # Neden erişilemediği, ne söyleneceğini belirler: "yapamam" değil,
            # "şu an eller bağlı değil" dürüst cümlesi kurulabilsin.
            entry["unavailableMeans"] = spec["cannot"]
        surfaces[name] = entry

    return {
        "contract": ECOSYSTEM_CONTRACT,
        "surfaces": surfaces,
        "handsAvailable": desktop_ready,
        "brainAvailable": backend_reachable,
    }


def delivery_outlook(
    assessment: dict[str, Any],
    *,
    needs_desktop: bool = False,
    needs_backend: bool = False,
) -> dict[str, Any]:
    """İstenen iş TESLİM EDİLEBİLİR mi — ve edilemezse dürüst gerekçe.

    Bu, "uydurma teslimat" hata sınıfının panzehiridir: model işin hangi
    yüzeyi gerektirdiğini kendi çözer, buradan yalnız o yüzeyin AÇIK olup
    olmadığını ve kapalıysa ne söylemesi gerektiğini öğrenir."""
    surfaces = assessment.get("surfaces", {}) if isinstance(assessment, dict) else {}
    blocked: list[str] = []
    if needs_desktop and not (surfaces.get("desktop", {}) or {}).get("available"):
        blocked.append("desktop")
    if needs_backend and not (surfaces.get("backend", {}) or {}).get("available"):
        blocked.append("backend")
    if not blocked:
        return {"deliverable": True}
    return {
        "deliverable": False,
        "blockedSurfaces": blocked,
        # Model bunu kendi cümlesiyle söyler; hazır metin dayatmıyoruz.
        "honestyDirective": (
            "Gereken yüzey şu an bağlı değil: "
            + ", ".join(blocked)
            + ". Yaptığını SÖYLEME; ne yapılamadığını ve neyin gerektiğini söyle."
        ),
    }


def to_prompt_context(assessment: dict[str, Any]) -> dict[str, Any]:
    """Modele gidecek sınırlı biçim: rol + erişilebilirlik + kapalıysa anlamı."""
    surfaces = assessment.get("surfaces", {}) if isinstance(assessment, dict) else {}
    payload: dict[str, Any] = {}
    for name, entry in surfaces.items():
        if not isinstance(entry, dict):
            continue
        item = {"role": entry.get("role"), "available": entry.get("available")}
        if entry.get("unavailableMeans"):
            item["ifUnavailable"] = entry["unavailableMeans"]
        payload[name] = item
    return payload
