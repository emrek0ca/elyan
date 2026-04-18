from __future__ import annotations

from cli.commands import desktop, gateway
from cli.commands.guide import render_install_to_ui_guide


def run(args) -> int:
    port = getattr(args, "port", None)
    no_browser = bool(getattr(args, "no_browser", False))
    ops = bool(getattr(args, "ops", False))
    force = bool(getattr(args, "force", False))

    print("🚀  Elyan launch başlıyor...")
    
    if force:
        print("🔄  Eski süreçler temizleniyor (--force)...")
        gateway.restart_gateway(daemon=True, port=port)
    else:
        gateway.start_gateway(daemon=True, port=port)

    gateway_port = int(port or gateway.DEFAULT_PORT)
    runtime = gateway._fetch_gateway_launch_health(gateway_port)
    if not runtime.get("ok") and gateway._wait_until_gateway_ready(gateway_port, timeout_s=4.0):
        runtime = gateway._fetch_gateway_launch_health(gateway_port)
    if not runtime.get("ok"):
        print(f"❌  Launch başarısız: {runtime.get('error', 'gateway hazır değil')}")
        return 1

    render_install_to_ui_guide(setup_ready=True, gateway_running=True, prefix="  ")

    if ops:
        print(f"ℹ️  Ops console ürün UI değil. Gerekirse gateway hazırken /ops endpoint'ini ayrı açın (port {gateway_port}).")
    if not no_browser:
        desktop.open_desktop(detached=True)
    print("✅  Elyan hazır. Desktop yüzeyi açıldıysa ilk oturum doğrulamasına geçebilirsin.")
    return 0
