"""Zekâ eval seti — anlama katmanının UÇTAN UCA sınavı.

NEDEN
-----
Bugüne kadar hiçbir "anlama" iyileştirmesi uçtan uca ölçülmedi; her oturum
"düzelttim sanıyorum" ile kapandı. Bu set, gerçek kullanıcı cümleleriyle
CANLI modeli sınar ve geçti/kaldı tablosu üretir. Desen eklemek YASAK olduğu
için iyileştirme aracı tektir: prompt/bağlam mühendisliği — ve o da ancak bu
setle kanıtlanırsa "iyileştirme" sayılır.

TASARIM
-------
- Her senaryo bir SÖZLEŞME iddiasıdır: mesaj + (varsa) durumsal bağlam →
  anlama zarfında beklenen alanlar. Kelime değil DAVRANIŞ ölçülür.
- Model erişilemezse senaryo `degraded_skip` olur — sahte geçti üretilmez,
  sahte kaldı da üretilmez (dürüst rapor).
- Senaryolar ham kullanıcı verisi içermez; hepsi sentetik ama canlıda görülen
  hata sınıflarından türetilmiştir ("yaz" mevsim/fiil çakışması, uydurma
  kaynak, bayat gönderme…).

KULLANIM
--------
    PYTHONPATH=. python scripts/run_intelligence_eval.py           # canlı model
    PYTHONPATH=. python scripts/run_intelligence_eval.py --json    # makine çıktısı
"""

from __future__ import annotations

from typing import Any, Callable

from runtime import understanding

EVAL_CONTRACT = "elyan.intelligence_eval.v1"

# Senaryo şeması:
#   id          — benzersiz kısa ad
#   message     — kullanıcının cümlesi (gerçekçi, sentetik)
#   situational — anlamaya verilecek durumsal bağlam (None = bağlam yok)
#   expect      — zarf üzerinde doğrulanacak iddialar (aşağıdaki anahtarlar)
#
# expect anahtarları:
#   intents            — kabul edilebilir niyet kümesi (listede olmalı)
#   resolvedPath       — resolvedTarget.path tam bu olmalı
#   resolvedSource     — resolvedTarget.source bu olmalı
#   unresolvedReference— resolvedTarget {"status":"unresolved"} olmalı
#   sourceKind         — zarfın sourceKind alanı bu olmalı
#   noMissingInfo      — missingInformation BOŞ olmalı (bariz şey sorulmamalı)
#   missingInfo        — missingInformation DOLU olmalı (eksik gerçekten eksik)
SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "chat_selamlasma",
        "message": "selam, nasılsın bugün?",
        "situational": None,
        "expect": {"intents": ["chat"]},
    },
    {
        "id": "chat_bilgi_sorusu",
        "message": "Python'da bir listeyi tarihe göre nasıl sıralarım?",
        "situational": None,
        "expect": {"intents": ["chat"]},
    },
    {
        # Tarihî hata sınıfı: "yaz" kelimesi regex döneminde görev sanılıyordu.
        "id": "chat_yaz_mevsim_tuzagi",
        "message": "bu yaz tatilde nereye gitsem güzel olur?",
        "situational": None,
        "expect": {"intents": ["chat"]},
    },
    {
        # Tarihî hata sınıfı: "ara" fiil/edat çakışması.
        "id": "chat_ara_tuzagi",
        "message": "arada bir spor yapmak istiyorum ama motivasyonum yok, ne önerirsin?",
        "situational": None,
        "expect": {"intents": ["chat"]},
    },
    {
        "id": "task_klasor_olustur",
        "message": "masaüstüne Faturalar diye bir klasör oluştur",
        "situational": None,
        "expect": {"intents": ["task"], "noMissingInfo": True},
    },
    {
        "id": "task_terminal_testleri",
        "message": "projedeki testleri çalıştır, kaç tanesi kırık bana söyle",
        "situational": None,
        "expect": {"intents": ["task"]},
    },
    {
        # Durum verildiğinde bariz olan SORULMAMALI (sözleşme kuralı 6).
        "id": "task_toplanti_notu_baglamdan",
        "message": "toplantı için kısa bir hazırlık notu oluştur",
        "situational": {
            "partOfDay": "sabah",
            "weekday": "Cuma",
            "nextEvent": {"title": "Yatırımcı Sunumu", "inMinutes": 45},
        },
        "expect": {"intents": ["task"], "noMissingInfo": True},
    },
    {
        # Gönderme + kayıtlı çıktı → hedef listedeki TAM yolla çözülmeli.
        "id": "gonderme_cozulur",
        "message": "o klasörü sil",
        "situational": {
            "recentOutputs": [
                {
                    "name": "Yeni Klasör",
                    "path": "/Users/emrekoca/Desktop/Yeni Klasör",
                    "kind": "folder",
                }
            ]
        },
        "expect": {
            "intents": ["task"],
            "resolvedPath": "/Users/emrekoca/Desktop/Yeni Klasör",
            "resolvedSource": "recent_output",
        },
    },
    {
        # Gönderme var, kayıt yok → görev ÇALIŞMAMALI; tek soru sorulmalı.
        "id": "gonderme_cozulmez_soru",
        "message": "onu sil",
        "situational": None,
        "expect": {"intents": ["clarify"], "missingInfo": True},
    },
    {
        # Kullanıcı yolu açıkça verdi → gönderme kaydı olmasa da görev yürür.
        "id": "acik_yol_kabul",
        "message": "/tmp/elyan-deneme/notlar.txt dosyasını sil",
        "situational": None,
        "expect": {"intents": ["task"]},
    },
    {
        # Kullanıcının ÖZEL içeriği elimizde yok → uydurma yerine SOR.
        "id": "ozel_kaynak_sorulur",
        "message": "sana attığım raporu özetleyip masaüstüne kaydet",
        "situational": None,
        "expect": {
            "intents": ["clarify"],
            "sourceKind": "user_private",
            "missingInfo": True,
        },
    },
    {
        # Kamuya açık bilgi → SORMA, araştırma adımı kaynağı sağlar.
        "id": "kamu_kaynak_sorulmaz",
        "message": "2026 asgari ücret ve vergi dilimlerini bir tabloya derle",
        "situational": None,
        "expect": {"intents": ["task"], "sourceKind": "public_external"},
    },
    {
        # Kendi durumu: görev yürürken "ne durumda" görev kontrolüdür.
        "id": "oz_durum_ne_durumda",
        "message": "ne durumda, bitti mi?",
        "situational": {"selfState": {"taskRunning": True}},
        "expect": {"intents": ["task_control"]},
    },
    {
        # Kendi durumu: son görev başarısızsa "neden olmadı" yeni görev DEĞİLDİR.
        "id": "oz_durum_neden_olmadi",
        "message": "neden olmadı? bir sorun mu çıktı?",
        "situational": {
            "selfState": {
                "lastTask": {"ok": False, "minutesAgo": 3, "detail": "izin reddedildi"}
            }
        },
        "expect": {"intents": ["chat", "task_control"]},
    },
]


def evaluate_envelope(
    envelope: understanding.SemanticUnderstanding,
    expect: dict[str, Any],
) -> list[str]:
    """Zarfı senaryonun iddialarına karşı denetler; ihlal listesi döner."""
    failures: list[str] = []
    intents = expect.get("intents")
    if intents and envelope.intent not in intents:
        failures.append(f"intent={envelope.intent}, beklenen: {'/'.join(intents)}")
    resolved = envelope.resolved_target
    expected_path = expect.get("resolvedPath")
    if expected_path is not None:
        actual = (resolved or {}).get("path")
        if actual != expected_path:
            failures.append(f"resolvedTarget.path={actual!r}, beklenen: {expected_path!r}")
    expected_source = expect.get("resolvedSource")
    if expected_source is not None:
        actual = (resolved or {}).get("source")
        if actual != expected_source:
            failures.append(f"resolvedTarget.source={actual!r}, beklenen: {expected_source!r}")
    if expect.get("unresolvedReference") and (resolved or {}).get("status") != "unresolved":
        failures.append(f"resolvedTarget={resolved!r}, beklenen: unresolved")
    expected_kind = expect.get("sourceKind")
    if expected_kind is not None and envelope.source_kind != expected_kind:
        failures.append(f"sourceKind={envelope.source_kind}, beklenen: {expected_kind}")
    if expect.get("noMissingInfo") and envelope.missing_information:
        failures.append(f"missingInformation dolu: {envelope.missing_information!r}")
    if expect.get("missingInfo") and not envelope.missing_information:
        failures.append("missingInformation boş; eksik bilginin sorulması bekleniyordu")
    return failures


def run_intelligence_eval(
    send_prompt: Callable[[str], str] | None = None,
    *,
    send_prompt_factory: Callable[[str], Callable[[str], str]] | None = None,
    only: list[str] | None = None,
) -> dict[str, Any]:
    """Senaryoları canlı taşıma ile koşturur.

    ``send_prompt_factory`` verilirse her senaryo için mesaja özel taşıma
    kurulur (backend güvenlik kapıları userText'i denetleyebilsin diye).
    Model erişilemeyen turlar `degraded_skip` olarak raporlanır — eval asla
    "model yoktu ama geçti/kaldı" yalanı üretmez."""
    cases: list[dict[str, Any]] = []
    passed = failed = skipped = 0
    for scenario in SCENARIOS:
        if only and scenario["id"] not in only:
            continue
        transport = (
            send_prompt_factory(scenario["message"])
            if send_prompt_factory is not None
            else send_prompt
        )
        envelope = understanding.analyze(
            scenario["message"],
            send_prompt=transport,
            situational_context=scenario.get("situational"),
        )
        if envelope.degraded:
            skipped += 1
            cases.append(
                {"id": scenario["id"], "status": "degraded_skip", "failures": []}
            )
            continue
        failures = evaluate_envelope(envelope, scenario.get("expect", {}))
        if failures:
            failed += 1
            status = "failed"
        else:
            passed += 1
            status = "passed"
        cases.append(
            {
                "id": scenario["id"],
                "status": status,
                "failures": failures,
                "intent": envelope.intent,
                "confidence": round(envelope.confidence, 2),
            }
        )
    return {
        "contract": EVAL_CONTRACT,
        "total": len(cases),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "cases": cases,
    }


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"Zekâ eval — {report['passed']} geçti / {report['failed']} kaldı"
        f" / {report['skipped']} atlandı (toplam {report['total']})",
        "",
    ]
    for case in report["cases"]:
        mark = {"passed": "✓", "failed": "✗", "degraded_skip": "○"}[case["status"]]
        line = f"  {mark} {case['id']}"
        if case.get("intent"):
            line += f"  [{case['intent']}]"
        lines.append(line)
        for failure in case["failures"]:
            lines.append(f"      → {failure}")
    return "\n".join(lines)
