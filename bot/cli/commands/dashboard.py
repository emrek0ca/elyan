import webbrowser
import time
from config.elyan_config import elyan_config

def open_dashboard(port: int | None = None, no_browser: bool = False):
    port = int(port or elyan_config.get("gateway.port", 18789))
    url = f"http://localhost:{port}/dashboard"
    
    print(f"🚀  Elyan Control Center açılıyor...")
    print(f"🔗  URL: {url}")
    
    # Give a small delay for server to be ready if called during start
    if no_browser:
        return
    webbrowser.open(url)
