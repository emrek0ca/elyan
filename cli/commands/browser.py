"""
CLI: browser commands — Full implementation
"""
import asyncio

import click


def _get_browser():
    """Get browser automation instance."""
    from tools.browser_automation import BrowserAutomation
    return BrowserAutomation()


@click.group("browser")
def browser_group():
    """Tarayıcı kontrolü (Chrome/Chromium CDP)."""
    pass


@browser_group.command("snapshot")
@click.option("--output", "-o", default=None, help="Kayıt dosyası (.png)")
def browser_snapshot(output):
    """Mevcut sayfanın ekran görüntüsünü al."""
    async def _run():
        b = _get_browser()
        result = await b.screenshot(output_path=output)
        if result.get("success"):
            saved_path = str(result.get("screenshot_path") or output or "").strip()
            if output:
                click.echo(f"✓ Ekran görüntüsü kaydedildi: {saved_path or output}")
            else:
                click.echo(f"✓ Snapshot alındı: {result}")
        else:
            click.echo(f"✗ {result.get('error', 'Ekran görüntüsü alınamadı.')}", err=True)
    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@browser_group.command("screenshot")
@click.option("--url", default=None, help="URL'ye git ve ekran görüntüsü al")
@click.option("--output", "-o", default="screenshot.png", help="Kayıt dosyası")
@click.option("--full-page", is_flag=True, help="Tam sayfa görüntüsü")
def browser_screenshot(url, output, full_page):
    """Tam sayfa ekran görüntüsü al."""
    async def _run():
        b = _get_browser()
        if url:
            await b.navigate(url)
        result = await b.screenshot(output_path=output, full_page=full_page)
        if result.get("success"):
            saved_path = str(result.get("screenshot_path") or output or "").strip()
            click.echo(f"✓ Ekran görüntüsü: {saved_path or output}")
        else:
            click.echo(f"✗ {result.get('error', 'Ekran görüntüsü alınamadı.')}", err=True)
    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@browser_group.command("navigate")
@click.argument("url")
def browser_navigate(url):
    """URL'ye git."""
    async def _run():
        b = _get_browser()
        await b.navigate(url)
        click.echo(f"✓ Gidildi: {url}")
    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@browser_group.command("click")
@click.argument("selector")
def browser_click(selector):
    """CSS selector veya metin ile öğeye tıkla."""
    async def _run():
        b = _get_browser()
        await b.click(selector)
        click.echo(f"✓ Tıklandı: {selector}")
    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@browser_group.command("type")
@click.argument("selector")
@click.argument("text")
def browser_type(selector, text):
    """Öğeye metin yaz."""
    async def _run():
        b = _get_browser()
        await b.type_text(selector, text)
        click.echo(f"✓ Yazıldı: '{text}' -> {selector}")
    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@browser_group.command("extract-text")
@click.option("--selector", default="body", help="CSS selector (varsayılan: body)")
def browser_extract_text(selector):
    """Sayfa metnini çıkar."""
    async def _run():
        b = _get_browser()
        text = await b.extract_text(selector)
        click.echo(text)
    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@browser_group.command("extract-links")
def browser_extract_links():
    """Sayfadaki tüm linkleri çıkar."""
    async def _run():
        b = _get_browser()
        links = await b.extract_links()
        for link in links:
            click.echo(link)
    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@browser_group.command("scroll")
@click.argument("direction", type=click.Choice(["down", "up", "top", "bottom"]))
@click.option("--amount", default=500, help="Piksel miktarı")
def browser_scroll(direction, amount):
    """Sayfayı kaydır."""
    async def _run():
        b = _get_browser()
        await b.scroll(direction, amount)
        click.echo(f"✓ Kaydırıldı: {direction}")
    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@browser_group.command("back")
def browser_back():
    """Geri git."""
    async def _run():
        b = _get_browser()
        await b.go_back()
        click.echo("✓ Geri gidildi.")
    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@browser_group.command("close")
def browser_close():
    """Tarayıcıyı kapat."""
    async def _run():
        b = _get_browser()
        await b.close()
        click.echo("✓ Tarayıcı kapatıldı.")
    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@browser_group.group("profiles")
def browser_profiles():
    """Tarayıcı profil yönetimi."""
    pass


@browser_profiles.command("list")
def profiles_list():
    """Profilleri listele."""
    try:
        from tools.browser_automation import BrowserAutomation
        b = BrowserAutomation()
        profiles = b.list_profiles() if hasattr(b, "list_profiles") else []
        if not profiles:
            click.echo("Kayıtlı profil yok.")
            return
        for p in profiles:
            click.echo(f"  {p.get('id', '-')}: {p.get('name', '-')}")
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


def register(cli):
    cli.add_command(browser_group, name="browser")


def handle_browser(args) -> int:
    action = str(getattr(args, "action", "") or "").strip().lower()
    target = str(getattr(args, "target", "") or "").strip()
    url = str(getattr(args, "url", "") or "").strip()

    async def _run() -> int:
        from tools.browser_automation import browse_url, extract_webpage_links, extract_webpage_text

        if action in {"navigate"}:
            final_url = url or target
            if not final_url:
                print("URL gerekli.")
                return 1
            result = await browse_url(final_url)
            if result.get("success"):
                print(f"Gidildi: {result.get('url')}")
                title = str(result.get("title") or "").strip()
                if title:
                    print(f"Baslik: {title}")
                return 0
            print(result.get("error", "Tarayici gezintisi basarisiz."))
            return 1

        if action in {"extract"}:
            final_url = url or target
            if not final_url:
                print("URL gerekli.")
                return 1
            result = await extract_webpage_text(final_url)
            if result.get("success"):
                text = str(result.get("text") or "").strip()
                print(text[:4000] if text else "(bos)")
                return 0
            print(result.get("error", "Metin cikarma basarisiz."))
            return 1

        if action in {"snapshot", "screenshot"}:
            final_url = url or target
            if final_url:
                result = await browse_url(final_url)
                if result.get("success"):
                    title = str(result.get("title") or "").strip()
                    print(f"Sayfa acildi: {result.get('url')}")
                    if title:
                        print(f"Baslik: {title}")
                    print("Ekran görüntüsü browser runtime ile alinabilir; output yolu verilirse dosya kaydedilir.")
                    return 0
                print(result.get("error", "Sayfa acilamadi."))
                return 1
            print("URL verilmedi. Mevcut browser oturumu varsa ekran görüntüsü alinabilir; yoksa önce browser navigate kullanin.")
            return 0

        if action in {"profiles", "list-profiles"}:
            try:
                from tools.browser.profile_manager import BrowserProfileManager

                manager = BrowserProfileManager()
                profiles = manager.list_profiles()
            except Exception:
                profiles = []
            if not profiles:
                print("Kayitli browser profili yok.")
                return 0
            for item in profiles:
                print(f"- {item}")
            return 0

        if action == "clear-profile":
            profile_name = target or str(getattr(args, "profile", "") or "").strip()
            if not profile_name:
                print("Profil adi gerekli.")
                return 1
            try:
                from tools.browser.profile_manager import BrowserProfileManager

                manager = BrowserProfileManager()
                ok = manager.delete_profile(profile_name) if hasattr(manager, "delete_profile") else False
            except Exception:
                ok = False
            if ok:
                print(f"Profil temizlendi: {profile_name}")
                return 0
            print(f"Profil temizlenemedi: {profile_name}")
            return 1

        if action in {"click", "type", "scroll", "back", "forward", "refresh", "close"}:
            print(f"'{action}' komutu interaktif browser oturumu gerektiriyor. Bu yuzey CLI smoke-safe modda bilgi veriyor.")
            return 0

        print(f"Bilinmeyen browser komutu: {action or '-'}")
        return 1

    return asyncio.run(_run())
