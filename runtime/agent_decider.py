"""Ajan döngüsü için model tabanlı karar verici (``decide_next``).

``agent_loop`` saf ve test edilebilir kalsın diye model çağrısı buraya ayrılmıştır.
Taşıma katmanı da enjekte edilir: ``send_prompt(prompt) -> str`` çağrılabilirı
mevcut ``/v1/brain/desktop/plan`` yolunu (bridge'deki zarf gönderici) ya da
testlerde sahte bir üreticiyi sarabilir.

Sözleşme: model TEK bir JSON nesnesi döner —

    {"kind": "tool", "capability": "<ad>", "args": {...}, "rationale": "..."}
    {"kind": "finish", "summary": "<kullanıcıya teslim metni>"}
    {"kind": "ask", "summary": "<eksik bilgi sorusu>"}
"""

from __future__ import annotations

import json
from typing import Any, Callable

AGENT_DECISION_CONTRACT = "elyan.agent_decision.v1"

_SYSTEM_CONTRACT = (
    "Sen Elyan'ın yürütme ajanısın. Hedefe ulaşmak için ADIM ADIM ilerlersin ve "
    "her turda YALNIZ BİR eylem seçersin. Sana geçmiş adımların GERÇEK sonuçları "
    "verilir; tahmin yürütme, gözlemlere dayan.\n"
    "KURALLAR:\n"
    "1) Yalnız araç kataloğundaki adları kullan. Var olmayan araç uydurma.\n"
    "2) Bir adımın çıktısını gördükten sonra bir sonraki adımı seç.\n"
    "3) Hedef gerçekten tamamlandıysa ve kanıtı gözlemlerde varsa 'finish' de. "
    "Yapılmamış bir işi yapılmış gibi özetleme.\n"
    "4) Aynı çağrı tekrar tekrar başarısız oluyorsa stratejini değiştir.\n"
    "5) Devam için kullanıcıdan bilgi şartsa 'ask' de.\n"
    "6) TESLİMAT ODAKLI OL. Bir bilgiyi ZATEN topladıysan tekrar toplama; "
    "aynı komutu farklı biçimlerde yeniden çalıştırmak ilerleme değildir. "
    "Geçmişte yeterli veri varsa DOĞRUDAN teslimatı üret (dosyayı yaz, sonucu ver). "
    "'stepsRemaining' azaldıkça bilgi toplamayı bırak ve teslimatı tamamla — "
    "eksik ama teslim edilmiş iş, mükemmel ama yarım kalmış işten iyidir.\n"
    "7) Sıfır olmayan exit kodu (ör. pytest exit=1) bir ARAÇ HATASI DEĞİLDİR; "
    "komut çalıştı ve sana bilgi verdi. Onu veri olarak kullan, komutu tekrarlama.\n"
    "6) SADECE tek bir JSON nesnesi döndür; açıklama, markdown veya kod bloğu ekleme."
)


def build_decision_prompt(context: dict[str, Any]) -> str:
    """Karar bağlamından sınırlanmış, katı-JSON isteyen prompt üretir."""
    payload = {
        "contract": AGENT_DECISION_CONTRACT,
        "goal": context.get("goal", ""),
        "goalContext": context.get("goalContext", {}),
        "tools": context.get("tools", []),
        "history": context.get("history", []),
        "stepsRemaining": context.get("stepsRemaining", 0),
    }
    warning = str(context.get("warning", "") or "").strip()
    if warning:
        payload["warning"] = warning
    # GEÇMİŞ DENEYİM: yalnız bu turun araçlarıyla ÖRTÜŞEN dersler taşınır
    # (alaka kapısı lesson_store'da). Alakasız ders modeli dağıtır.
    lessons = context.get("lessons")
    if isinstance(lessons, list) and lessons:
        payload["lessonsFromExperience"] = lessons[:3]
    # TESLİMAT SÖZLEŞMESİ: kullanıcının elinde ne kalmalı. Döngü bunu üretmeden
    # bitiremez; model de neyi hedeflediğini her turda görür.
    deliverables = context.get("deliverables")
    if isinstance(deliverables, list) and deliverables:
        payload["mustDeliver"] = deliverables[:3]
    body = json.dumps(payload, ensure_ascii=False)
    schema = (
        '{"kind":"tool|finish|ask","capability":"<katalogdan ad>",'
        '"args":{},"rationale":"<kısa gerekçe>","summary":"<finish/ask için metin>"}'
    )
    return (
        f"{_SYSTEM_CONTRACT}\n\n"
        f"DURUM:\n{body}\n\n"
        f"ÇIKTI ŞEMASI (tek JSON nesnesi):\n{schema}"
    )


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Model çıktısındaki ilk dengeli JSON nesnesini çıkarır.

    Kod bloğu çitleri, ön/arka açıklama metni ve iç içe nesneler tolere edilir.
    Bulunamazsa None (çağıran fail-closed davranır)."""
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, ValueError):
        pass

    start = raw.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(raw)):
            char = raw[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = raw[start : index + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict):
                            return parsed
                    except (TypeError, ValueError):
                        break
        start = raw.find("{", start + 1)
    return None


def make_model_decider(
    send_prompt: Callable[[str], str],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """``agent_loop.run_agent_loop(decide_next=...)`` için karar verici üretir.

    ``send_prompt`` prompt'u modele iletip ham metni döndürmelidir. Model
    okunamaz/boş çıktı verirse 'ask' döndürülür — uydurma araç çağrısı yerine
    güvenle durmak yeğdir (fail-closed)."""

    def decide_next(context: dict[str, Any]) -> dict[str, Any]:
        prompt = build_decision_prompt(context)
        try:
            raw = send_prompt(prompt)
        except Exception:
            return {
                "kind": "ask",
                "summary": "Planlayıcıya ulaşılamadı; görev güvenle durduruldu.",
            }
        decision = extract_json_object(raw)
        if not decision:
            return {
                "kind": "ask",
                "summary": "Planlayıcı geçerli bir karar üretmedi.",
            }
        return decision

    return decide_next


def make_backend_send_prompt(
    invoke_plan: Callable[[str], dict[str, Any] | None],
) -> Callable[[str], str]:
    """Bridge'in ``/v1/brain/desktop/plan`` zarf göndericisini metin taşımasına
    çevirir. ``invoke_plan(prompt)`` {"ok": True, "content": "<metin>"} döner."""

    def send_prompt(prompt: str) -> str:
        result = invoke_plan(prompt)
        if not isinstance(result, dict) or not result.get("ok"):
            raise RuntimeError("agent_decider_transport_unavailable")
        return str(result.get("content", "") or "")

    return send_prompt
