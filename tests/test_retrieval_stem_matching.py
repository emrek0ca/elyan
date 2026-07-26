"""Getirme katmanının eklemeli dil sözleşmesi.

Ölçülen canlı zaaf: kapsama ve yeniden sıralama BİREBİR sözcük eşleşmesine
dayanıyordu. Türkçe eklemeli olduğu için soruyu gerçekten cevaplayan belge
elde dururken kapsama 0.0 çıkıyor, sistem gereksiz ikinci tur arama yapıyor
ya da "kanıtım yok" sanıp kaynaksız kalıyordu.

Düzeltme bir EK LİSTESİ değildir (o, projenin kök hatasının tekrarı olurdu):
ortak kök uzunluğu + kısa terime oranı ölçütü kullanılır.
"""

from __future__ import annotations

from runtime.retrieval_orchestrator import (
    RetrievedItem,
    assess_sufficiency,
    decompose_query,
    rerank,
)


def test_suffixed_forms_count_as_covered() -> None:
    """"enflasyon" ile "enflasyonun", "oranı" ile "oranları" aynı köktendir."""
    items = [
        RetrievedItem(
            text="Enflasyonun son açıklanan oranları merkez bankası tarafından paylaşıldı.",
            score=0.9,
        )
    ]
    coverage, unmet = assess_sufficiency(["enflasyon oranı kaç"], items)
    # Eklemeli biçimler karşılanmış sayılır: birebir eşleşmede kapsama 0.0'dı.
    assert "enflasyon" not in unmet
    assert "oranı" not in unmet
    assert coverage > 0.6


def test_english_inflections_are_covered_by_the_same_rule() -> None:
    items = [RetrievedItem(text="Quarterly reporting guidelines were published.", score=0.5)]
    coverage, unmet = assess_sufficiency(["reports guideline"], items)
    assert unmet == []
    assert coverage == 1.0


def test_unrelated_documents_stay_uncovered() -> None:
    """Ölçüt gevşek değil: alakasız belge kapsama üretmez."""
    items = [RetrievedItem(text="Mahkeme kararı bugün açıklandı.", score=0.5)]
    coverage, unmet = assess_sufficiency(["kar payı dağıtımı"], items)
    assert coverage == 0.0
    # Karşılanmayanlar TERİM düzeyinde döner; ikinci turun hedefi bunlardır.
    assert unmet == ["dağıtımı", "kar", "payı"]


def test_multi_topic_query_is_measured_without_any_conjunction_list() -> None:
    """Çok konulu sorguda eksik konu MASKELENMEZ — bağlaç yazılmasa bile.

    Eskiden bileşik sorgu bir bağlaç listesiyle (`ve|ayrıca|bir de`) bölünüyordu:
    kelime deseniydi ve kullanıcı bağlacı yazmayınca çökerdi. Ölçüm artık terim
    düzeyinde, dolayısıyla iki yazım da aynı sonucu verir.
    """
    items = [
        RetrievedItem(text="Merkez bankası faiz kararını açıkladı.", score=0.8)
    ]
    with_conjunction = assess_sufficiency(
        decompose_query("faiz kararı ve enflasyon oranı"), items
    )
    without_conjunction = assess_sufficiency(
        decompose_query("faiz kararı enflasyon oranı"), items
    )
    assert with_conjunction == without_conjunction
    coverage, unmet = with_conjunction
    assert coverage < 0.6  # ikinci tur tetiklenir
    assert "enflasyon" in unmet


def test_no_evidence_is_never_treated_as_sufficient() -> None:
    """Değişmez: kanıt yoksa kapsama SIFIRDIR — uydurmanın önündeki kapı."""
    coverage, unmet = assess_sufficiency(["enflasyon oranı"], [])
    assert coverage == 0.0
    assert unmet == ["enflasyon oranı"]


def test_rerank_promotes_the_morphologically_matching_document() -> None:
    """Eklemeli biçim yüzünden ilgili belge geride kalmamalı."""
    items = [
        RetrievedItem(text="Tamamen alakasız bir metin parçası burada duruyor.", score=0.8),
        RetrievedItem(text="Enflasyonun oranları ve etkileri değerlendirildi.", score=0.2),
    ]
    ranked = rerank(items, "enflasyon oranı", limit=2)
    assert "Enflasyonun" in ranked[0].text


def test_rerank_drops_duplicates() -> None:
    text = "Aynı içerik iki kez getirildi ve tekrar etmemeli."
    ranked = rerank(
        [RetrievedItem(text=text, score=0.9), RetrievedItem(text=text, score=0.4)],
        "içerik",
        limit=5,
    )
    assert len(ranked) == 1
