"""
CLI: browser commands — Full implementation
"""
import asyncio
import json
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
