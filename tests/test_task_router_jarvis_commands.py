"""Jarvis komut aileleri regresyon testi: aç / git-gir / araştır / belgele.

Swift uygulamasından gelen doğal Türkçe komutların deterministik router'da
doğru yeteneğe (ve makul argümanlara) gitmesini garanti eder.
"""
from __future__ import annotations

import pytest

from runtime.task_router import route_text_to_tool


def _folded(value: str) -> str:
    value = str(value).lower()
    for src, dst in (("ı", "i"), ("ğ", "g"), ("ü", "u"), ("ş", "s"), ("ö", "o"), ("ç", "c")):
        value = value.replace(src, dst)
    return value


CASES = [
    # --- şunu aç (uygulama) ---
    ("Safari'yi aç", "open_app", "safari"),
    ("safari aç", "open_app", "safari"),
    ("Notları açar mısın", "open_app", "not"),
    ("Spotify'ı başlat", "open_app", "spotify"),
    ("hesap makinesini aç", "open_app", "hesap"),
    ("Finder'ı öne getir", "open_app", "finder"),
    ("visual studio code aç", "open_app", "visual studio code"),
    ("whatsapp'ı aç lütfen", "open_app", "whatsapp"),
    ("sistem ayarlarını aç", "open_app", "ayarlar"),
    ("mail uygulamasını aç", "open_app", "mail"),
    ("terminali aç", "open_app", "terminal"),
    # --- şuraya git (site/url) ---
    ("youtube'a gir", "browser_control", "youtube.com"),
    ("github.com'u aç", "browser_control", "github.com"),
    ("google'a git", "browser_control", "google.com"),
    ("hurriyet.com.tr aç", "browser_control", "hurriyet.com.tr"),
    ("tarayıcıda openai sitesini aç", "browser_control", "openai.com"),
    ("şu siteye git: anthropic.com", "browser_control", "anthropic.com"),
    ("twitter'a gir", "browser_control", "x.com"),
    # --- şunu araştır ---
    ("kuantum bilgisayarları araştır", "web_research", "kuantum"),
    ("bana elektrikli araba fiyatlarını araştırır mısın", "web_research", "elektrikli"),
    ("2026 asgari ücret ne kadar araştır", "web_research", "asgari"),
    ("yapay zeka ajanları hakkında bilgi topla", "web_research", "yapay zeka"),
    ("m5 çip hakkında detaylı araştırma yap", "web_research", "m5"),
    ("bitcoin fiyatını araştır", "web_research", "bitcoin"),
    # --- şunu belgele ---
    ("toplantı notlarını belgele", "document_write", "toplanti"),
    ("bu konuşmayı word belgesi yap", "document_write", ""),
    ("kuantum araştırmasını dökümante et", "document_write", "kuantum"),
    ("proje planı için bir doküman oluştur", "document_write", "proje"),
    ("bunu bir rapora dönüştür", "document_write", ""),
    ("satış verilerinden bir word raporu hazırla", "document_write", "satis"),
    ("masaüstüne rapor.docx adında bir belge oluştur", "document_write", "rapor"),
]


@pytest.mark.parametrize("text,expected_capability,arg_hint", CASES, ids=[c[0] for c in CASES])
def test_jarvis_command_routes(text: str, expected_capability: str, arg_hint: str) -> None:
    routed = route_text_to_tool(text)
    assert routed is not None, f"{text!r} hiçbir rotaya eşleşmedi"
    assert routed.tool_name == expected_capability, (
        f"{text!r} -> {routed.tool_name} (beklenen {expected_capability}), args={routed.args}"
    )
    if arg_hint:
        assert _folded(arg_hint) in _folded(str(routed.args)), (
            f"{text!r} argümanlarında {arg_hint!r} yok: {routed.args}"
        )


def test_vague_git_falls_through_to_planner() -> None:
    # "işe git" gibi belirsiz hedefler deterministik rotaya takılmamalı;
    # None dönerse istek semantik planlayıcıya düşer.
    routed = route_text_to_tool("yarın işe git")
    assert routed is None or routed.tool_name != "browser_control"


def test_excel_report_not_hijacked_by_document_route() -> None:
    routed = route_text_to_tool("satış verilerinden excel raporu hazırla")
    assert routed is not None
    assert routed.tool_name == "spreadsheet_write"
