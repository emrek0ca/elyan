from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = "http://127.0.0.1:4173"
ROUTES = [
    ("/", "Yapay zekâ"),
    ("/ozellikler", "Düşünceden çıktıya"),
    ("/nasil-calisir", "Telefonunda başlar"),
    ("/indir", "Elyan, cebinde"),
    ("/fiyatlandirma", "İhtiyacın kadar"),
    ("/destek", "Kur, eşleştir"),
    ("/gizlilik", "Gizlilik Politikası"),
    ("/kosullar", "Kullanım Koşulları"),
    ("/privacy", "Gizlilik Politikası"),
    ("/terms", "Kullanım Koşulları"),
    ("/kullanim-kosullari", "Kullanım Koşulları"),
    ("/ai", "Yapay Zekâ Bildirimi"),
    ("/yapay-zeka-bildirimi", "Yapay Zekâ Bildirimi"),
    ("/support", "Elyan Destek"),
    ("/account-deletion", "Hesap ve Veri Silme"),
    ("/hesap-silme", "Hesap ve Veri Silme"),
    ("/pricing", "İhtiyacın kadar"),
]

output = Path("test-results")
output.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    console_errors = []

    desktop = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    desktop.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    for route, text in ROUTES:
        response = desktop.goto(ROOT + route, wait_until="networkidle")
        assert response and response.ok, f"Route failed: {route}"
        assert desktop.get_by_text(text, exact=False).first.is_visible(), f"Heading missing: {route}"
    desktop.goto(ROOT + "/olmayan-sayfa", wait_until="networkidle")
    assert desktop.get_by_text("Bu sayfa burada değil", exact=False).is_visible()
    desktop.goto(ROOT, wait_until="networkidle")
    assert desktop.locator('a[href="https://apps.apple.com/tr/app/elyan/id6779045459"]').count() >= 1
    assert desktop.locator(".home-video").count() == 0
    assert desktop.locator(".home-hero-media img").count() == 1
    assert desktop.locator(".home-life img").count() == 1

    # In-app browsers may wrap scrollTo and return a Promise. ScrollTop must
    # never leak that value as a React effect cleanup function.
    desktop.evaluate("window.scrollTo = async () => undefined")
    desktop.evaluate("document.querySelector('.desktop-nav a[href=\"/ozellikler\"]')?.click()")
    desktop.wait_for_url(ROOT + "/ozellikler")
    desktop.evaluate("document.querySelector('.desktop-nav a[href=\"/nasil-calisir\"]')?.click()")
    desktop.wait_for_url(ROOT + "/nasil-calisir")
    desktop.wait_for_timeout(350)
    assert desktop.url == ROOT + "/nasil-calisir"
    desktop.goto(ROOT, wait_until="networkidle")
    for selector in [".home-hero", ".home-life", ".home-install", ".home-end"]:
        section = desktop.locator(selector)
        section.scroll_into_view_if_needed()
        desktop.wait_for_timeout(180)
        assert section.is_visible(), f"Home section hidden: {selector}"
    for y in range(0, desktop.evaluate("document.body.scrollHeight"), 700):
        desktop.evaluate(f"window.scrollTo(0, {y})")
        desktop.wait_for_timeout(80)
    desktop.evaluate("window.scrollTo(0, 0)")
    desktop.wait_for_timeout(200)
    desktop.screenshot(path=str(output / "home-desktop.png"), full_page=True)

    mobile = browser.new_page(viewport={"width": 375, "height": 812}, device_scale_factor=1)
    mobile.goto(ROOT, wait_until="networkidle")
    for y in range(0, mobile.evaluate("document.body.scrollHeight"), 600):
        mobile.evaluate(f"window.scrollTo(0, {y})")
        mobile.wait_for_timeout(60)
    mobile.evaluate("window.scrollTo(0, 0)")
    mobile.get_by_role("button", name="Menüyü aç").click()
    assert mobile.get_by_role("link", name="Neler yapar").is_visible()
    mobile.get_by_role("button", name="Menüyü kapat").click()
    assert mobile.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    mobile.screenshot(path=str(output / "home-mobile.png"), full_page=True)

    assert not console_errors, f"Console errors: {console_errors}"
    browser.close()

print(f"QA_OK routes={len(ROUTES)} aliases=9 not_found=1 desktop=1440 mobile=375 console_errors=0")
