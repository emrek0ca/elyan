"""Eval motorunun sözleşmesi: motor GERÇEKTEN ölçüyor mu?

Üç değişmez:
  1. İdeal cevaplar geçer (motor yanlış alarm üretmez).
  2. Yanlış cevaplar yakalanır (motor sahte geçti üretmez).
  3. Model erişilemeyen tur `degraded_skip` olur — asla geçti/kaldı sayılmaz.
"""

from __future__ import annotations

import json

from runtime import intelligence_eval, understanding


def _ideal_payload(scenario: dict) -> dict:
    """Senaryonun beklentisini karşılayan asgari model cevabını üretir."""
    expect = scenario.get("expect", {})
    intent = (expect.get("intents") or ["chat"])[0]
    payload: dict = {"intent": intent, "confidence": 0.9, "taskType": "eval"}
    if expect.get("sourceKind"):
        payload["sourceKind"] = expect["sourceKind"]
    if expect.get("missingInfo"):
        payload["missingInformation"] = ["hangi dosya olduğu belirsiz"]
    if expect.get("resolvedPath"):
        payload["resolvedTarget"] = {"path": expect["resolvedPath"], "kind": "folder"}
    if expect.get("unresolvedReference"):
        payload["resolvedTarget"] = {"status": "unresolved"}
    return payload


def test_ideal_answers_pass_every_scenario() -> None:
    # Eşleşme anahtarı MESAJ ÇİTİdir: sözleşme metni örnek olarak "onu sil"
    # gibi kısa cümleler içerdiğinden ham substring eşleşmesi yanlış senaryonun
    # cevabını döndürür. Çit, analiz edilen mesajı tam sınırıyla verir.
    answers = {
        understanding.fence_message(scenario["message"]): _ideal_payload(scenario)
        for scenario in intelligence_eval.SCENARIOS
    }

    def send_prompt(prompt: str) -> str:
        for needle, payload in answers.items():
            if needle in prompt:
                return json.dumps(payload, ensure_ascii=False)
        raise AssertionError("senaryo mesajı promptta bulunamadı")

    report = intelligence_eval.run_intelligence_eval(send_prompt)
    assert report["failed"] == 0
    assert report["skipped"] == 0
    assert report["passed"] == len(intelligence_eval.SCENARIOS)


def test_analyzed_message_is_fenced_outside_the_context_envelope() -> None:
    """ÖZNE AYRIMI değişmezi.

    Mesaj, çevresel bağlam JSON'unun İÇİNE gömülmemelidir. Gömüldüğünde model
    özneyi karıştırıp kendi iş ürününü ("şema uyumlu JSON üret") kullanıcının
    teslimatı sayıyor ve düşük sinyalli sohbeti göreve çeviriyordu — ölçüldü:
    "selam, nasılsın bugün?" 5 koşunun 4'ünde `task`. Çit kaldırılırsa bu
    testin düşmesi gerekir.
    """
    prompt = understanding.build_understanding_prompt(
        "selam, nasılsın bugün?",
        situational_context={"partOfDay": "sabah"},
        recent_turns=["kullanıcı: pomodoro tekniği nasıl çalışıyor?"],
    )
    fence = understanding.fence_message("selam, nasılsın bugün?")
    assert fence in prompt
    # Mesaj, arka plan JSON'unun İÇİNDE geçmemeli.
    background = prompt.split("ARKA PLAN", 1)[1].split("ŞİMDİ SINIFLA", 1)[0]
    assert "selam, nasılsın bugün?" not in background
    # Şema, sınıflandırılan teslimat DEĞİLDİR — bu ayrım prompt'ta yazılı kalmalı.
    assert "iş ürünün" in prompt


def test_background_precedes_the_classified_message() -> None:
    """SIRA değişmezi: arka plan ÖNCE, sınıflanacak mesaj SONRA.

    Mesaj arka plandan önce konduğunda bağlamdaki metinler (önceki turlar, konu
    başlığı) daha yakın konumda kalıp özneyi çalıyordu — ölçüldü: "bunu belge
    yap" isteği 5/5 `chat` çıktı ve gerekçede önceki turun SORUSU sınıflanmıştı.
    Sıra bozulursa bu test düşmeli.
    """
    prompt = understanding.build_understanding_prompt(
        "bunu belge yap",
        recent_turns=["kullanıcı: pomodoro tekniği nasıl çalışıyor?"],
    )
    assert prompt.index("ARKA PLAN") < prompt.index(
        understanding.fence_message("bunu belge yap")
    )
    # Sınıflanacak metin, çıktı şemasının hemen öncesinde durmalı.
    assert prompt.index(understanding.fence_message("bunu belge yap")) < prompt.index(
        "ÇIKTI ŞEMASI"
    )


def test_wrong_intent_is_caught() -> None:
    def send_prompt(_prompt: str) -> str:
        return json.dumps({"intent": "task", "confidence": 0.9})

    report = intelligence_eval.run_intelligence_eval(
        send_prompt, only=["chat_selamlasma"]
    )
    assert report["failed"] == 1
    assert "intent=task" in report["cases"][0]["failures"][0]


def test_fabricated_reference_path_is_caught_by_grounding() -> None:
    # Model listede olmayan bir yol uydurursa kanıt kapısı unresolved'a düşürür
    # → beklenen yol bulunamaz → senaryo KALIR. Eval + grounding birlikte çalışır.
    def send_prompt(_prompt: str) -> str:
        return json.dumps(
            {
                "intent": "task",
                "confidence": 0.9,
                "resolvedTarget": {"path": "/tmp/uydurma"},
            }
        )

    report = intelligence_eval.run_intelligence_eval(send_prompt, only=["gonderme_cozulur"])
    assert report["failed"] == 1


def test_unreachable_model_yields_degraded_skip_not_verdict() -> None:
    def send_prompt(_prompt: str) -> str:
        raise RuntimeError("agent_decider_transport_unavailable")

    report = intelligence_eval.run_intelligence_eval(send_prompt, only=["chat_selamlasma"])
    assert report["skipped"] == 1
    assert report["failed"] == 0 and report["passed"] == 0
    assert report["cases"][0]["status"] == "degraded_skip"


def test_scenario_ids_are_unique_and_messages_nonempty() -> None:
    ids = [scenario["id"] for scenario in intelligence_eval.SCENARIOS]
    assert len(ids) == len(set(ids))
    assert all(str(scenario["message"]).strip() for scenario in intelligence_eval.SCENARIOS)
    assert len(ids) >= 10


def test_evaluate_envelope_checks_source_field() -> None:
    envelope = understanding.SemanticUnderstanding(
        intent="task",
        confidence=0.9,
        source="model",
        resolved_target={"path": "/a", "source": "user_message"},
    )
    failures = intelligence_eval.evaluate_envelope(
        envelope, {"resolvedSource": "recent_output"}
    )
    assert failures and "recent_output" in failures[0]
