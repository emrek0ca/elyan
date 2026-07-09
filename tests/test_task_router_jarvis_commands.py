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


def test_clipboard_read_commands_route_to_clipboard_read() -> None:
    for text in ["panoda ne var", "panodakini özetle", "panoyu oku", "kopyalanan metni göster"]:
        routed = route_text_to_tool(text)
        assert routed is not None, text
        assert routed.tool_name == "clipboard_read", f"{text!r} -> {routed.tool_name}"


def test_clipboard_write_commands_extract_text() -> None:
    cases = {
        "şunu panoya kopyala: merhaba dünya": "merhaba dünya",
        "elyan raporu panoya kopyala": "elyan raporu",
        "panoya kopyala https://elyan.dev": "https://elyan.dev",
    }
    for text, expected in cases.items():
        routed = route_text_to_tool(text)
        assert routed is not None, text
        assert routed.tool_name == "clipboard_write", f"{text!r} -> {routed.tool_name}"
        assert routed.args.get("text") == expected, f"{text!r} -> {routed.args}"


def test_file_copy_not_shadowed_by_clipboard_route() -> None:
    # "masaüstüne kopyala" hâlâ dosya kopyalama (shell) rotasına gitmeli.
    routed = route_text_to_tool("rapor.pdf dosyasını masaüstüne kopyala")
    assert routed is not None
    assert routed.tool_name == "shell_run"


def test_sys_info_matches_suffixed_turkish_forms() -> None:
    # Jarvis'in en sık kaçırdığı aile: ekli/çekimli sistem sorguları.
    cases = {
        "pilim ne durumda": "battery",
        "şarjım kaçta biter": "battery",
        "diskte ne kadar yer var": "disk",
        "bellek kullanımı nedir": "ram",
        "işlemci yükü ne": "cpu",
        "saat kaç": "time",
        "bugün hangi gündeyiz": "date",
    }
    from runtime.task_router import _sys_info_query

    for text, expected in cases.items():
        assert _sys_info_query(text) == expected, f"{text!r} -> {_sys_info_query(text)}"


def test_sys_info_does_not_false_positive_on_generic_islem() -> None:
    # "işlem" içeren alakasız komut CPU'ya kaçmamalı.
    routed = route_text_to_tool("bu işlemi tamamla")
    assert routed is None or routed.tool_name != "sys_info"


def test_new_tab_phrase_not_misrouted_to_open_app() -> None:
    # "yeni sekme aç" bir uygulama değil; open_app'e ya da uydurma URL'ye gitmemeli.
    routed = route_text_to_tool("yeni sekme aç")
    assert routed is None or routed.tool_name not in {"open_app"}
    from runtime.task_router import _site_target_to_url
    assert _site_target_to_url("yeni sekme") is None  # yenisekme.com üretmemeli
    assert _site_target_to_url("spotify") == "https://spotify.com"  # marka çalışır


def test_open_and_close_app_still_route() -> None:
    for text, cap in [("safari aç", "open_app"), ("safari kapat", "close_app"), ("chrome aç", "open_app")]:
        routed = route_text_to_tool(text)
        assert routed is not None and routed.tool_name == cap, f"{text!r} -> {routed}"


def test_gui_actions_route_to_desktop_operator() -> None:
    for text in [
        "ekranda gönder butonuna tıkla",
        "sayfayı aşağı kaydır",
        "arama kutusuna yaz",
    ]:
        routed = route_text_to_tool(text)
        assert routed is not None and routed.tool_name == "desktop_operator.run", f"{text!r} -> {routed}"
        assert routed.args.get("goal") == text


def test_image_find_routes_to_reliable_browser_search() -> None:
    # Kaydetme niyeti OLMAYAN "X resmi bul/göster" kırılgan operatör yerine
    # güvenilir Google Görseller aramasına gider.
    for text, subject in [
        ("kedi resmi bul", "kedi"),
        ("araba görseli göster", "araba"),
    ]:
        routed = route_text_to_tool(text)
        assert routed is not None and routed.tool_name == "browser_control", f"{text!r} -> {routed}"
        assert subject in routed.args.get("url", "")
    # "çiz" ÜRETME komutu bu route'a takılmaz (image_generate'e gider).
    drawn = route_text_to_tool("kedi resmi çiz")
    assert drawn is None or drawn.tool_name != "browser_control"


def test_image_save_routes_to_reliable_download() -> None:
    # "bul/indir + kaydet" niyeti görseli GERÇEKTEN indirip diske yazan
    # image_fetch'e gider (pikselli GUI değil; doğrudan HTTP indirme).
    # Not: subject, _normalise ile aksansızlaştırılır (mevcut arama yoluyla tutarlı).
    for text, subject, destination in [
        ("safariden kedi resmi bul ve masaüstüne kaydet", "kedi", "~/Desktop"),
        ("köpek resmini indir", "kopek", "~/Desktop"),
        ("internetten aslan görseli indirilenlere kaydet", "aslan", "~/Downloads"),
    ]:
        routed = route_text_to_tool(text)
        assert routed is not None and routed.tool_name == "image_fetch", f"{text!r} -> {routed}"
        assert routed.args.get("query") == subject
        assert routed.args.get("destination") == destination
    # "çiz + kaydet" bir ÜRETME komutudur; image_fetch'i gölgelememeli.
    drawn = route_text_to_tool("kedi resmi çiz ve kaydet")
    assert drawn is None or drawn.tool_name != "image_fetch"


def test_developer_tools_route_to_read_side_capabilities() -> None:
    # Yüksek-sinyalli kod-ajanı komutları okuma-tarafı dev tool'larına gider.
    expectations = {
        "git durumu": "git_status",
        "git status": "git_status",
        "git diff": "git_diff",
        "git farkları göster": "git_diff",
        "proje yapısı": "directory_tree",
        "klasör ağacı": "directory_tree",
        "kodda RuntimeBridge ara": "file_search",
        "projede image_fetch bul": "file_search",
    }
    for text, expected in expectations.items():
        routed = route_text_to_tool(text)
        assert routed is not None and routed.tool_name == expected, f"{text!r} -> {routed}"


def test_git_status_diff_do_not_swallow_other_git_commands() -> None:
    # Yalnız status/diff/commit/branch yakalanır; git log/push ham shell'e kalmalı.
    for text in ["git log", "git push", "git stash"]:
        routed = route_text_to_tool(text)
        assert routed is not None and routed.tool_name == "shell_run", f"{text!r} -> {routed}"


def test_write_side_git_commands_route_with_confirmation() -> None:
    # Mutasyon komutları (commit/branch) onay bayrağıyla dev tool'lara gider.
    commit = route_text_to_tool("değişiklikleri commit'le 'ilk sürüm'")
    assert commit is not None and commit.tool_name == "git_commit"
    assert commit.requires_confirmation is True
    assert commit.args.get("message") == "ilk sürüm"

    bare = route_text_to_tool("commit yap")
    assert bare is not None and bare.tool_name == "git_commit" and bare.requires_confirmation is True

    for text, expected_name in [
        ("yeni branch feature-x oluştur", "feature-x"),
        ("branch oluştur bugfix/login", "bugfix/login"),
    ]:
        routed = route_text_to_tool(text)
        assert routed is not None and routed.tool_name == "git_branch", f"{text!r} -> {routed}"
        assert routed.requires_confirmation is True
        assert routed.args.get("name") == expected_name


def test_operator_route_does_not_shadow_specific_capabilities() -> None:
    # Belge/mesaj/generic komutlar operatöre KAÇMAMALI.
    expectations = {
        "türkiye ekonomisini araştır ve word belgesi olarak kaydet": "web_research",  # compound ilk adım
        "whatsapptan ahmete merhaba gönder": None,  # semantic route'a bırakılır
        "safari aç": "open_app",
        "saat kaç": "sys_info",
    }
    for text, expected in expectations.items():
        routed = route_text_to_tool(text)
        if expected is None:
            assert routed is None or routed.tool_name != "desktop_operator.run", f"{text!r} -> {routed}"
        else:
            tool = routed.tool_name if routed else None
            assert tool != "desktop_operator.run", f"{text!r} yanlışlıkla operatöre gitti"
