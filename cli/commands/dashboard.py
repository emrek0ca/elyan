import webbrowser
import secrets
from config.elyan_config import elyan_config


def _ensure_admin_token() -> str:
    token = str(elyan_config.get("gateway.admin.token", "") or "").strip()
    if token:
        return token
    token = secrets.token_urlsafe(24)
    elyan_config.set("gateway.admin.token", token)
    return token


def open_dashboard(port: int | None = None, no_browser: bool = False, ops: bool = False):
    port = int(port or elyan_config.get("gateway.port", 18789))
    if ops:
        token = _ensure_admin_token()
        url = f"http://localhost:{port}/ops?token={token}"
        print("🔐  Elyan Ops Console açılıyor...")
    else:
        url = f"http://localhost:{port}/product"
        print("🚀  Elyan Product Surface açılıyor...")
    
    print(f"🔗  URL: {url}")
    
    # Give a small delay for server to be ready if called during start
    if no_browser:
        return
    webbrowser.open(url)
