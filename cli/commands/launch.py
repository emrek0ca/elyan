from __future__ import annotations

from cli.commands import dashboard, gateway


def run(args) -> int:
    port = getattr(args, "port", None)
    no_browser = bool(getattr(args, "no_browser", False))
    ops = bool(getattr(args, "ops", False))

    print("🚀  Elyan launch başlıyor...")
    gateway.start_gateway(daemon=True, port=port)

    gateway_port = int(port or gateway.DEFAULT_PORT)
    runtime = gateway._fetch_gateway_status(gateway_port)
    if not runtime.get("ok") and gateway._wait_until_gateway_ready(gateway_port, timeout_s=4.0):
        runtime = gateway._fetch_gateway_status(gateway_port)
    if not runtime.get("ok"):
        print(f"❌  Launch başarısız: {runtime.get('error', 'gateway hazır değil')}")
        return 1

    dashboard.open_dashboard(port=gateway_port, no_browser=no_browser, ops=ops)
    print("✅  Elyan hazır.")
    return 0
