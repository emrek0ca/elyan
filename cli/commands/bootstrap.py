from __future__ import annotations

import argparse

from elyan.bootstrap.manager import get_bootstrap_manager


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="elyan bootstrap", add_help=False)
    sub = parser.add_subparsers(dest="action")

    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("install")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("onboard")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--channel", default=None)
    p.add_argument("--install-daemon", action="store_true")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("repair")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("restore")
    p.add_argument("--bundle", default=None)

    p = sub.add_parser("snapshot")
    p.add_argument("--output", default=None)

    return parser


def handle_bootstrap(args) -> int:
    manager = get_bootstrap_manager()
    action = str(getattr(args, "action", "") or "status").strip().lower()
    if action == "status":
        status = manager.status()
        if getattr(args, "json", False):
            import json

            print(json.dumps(status, ensure_ascii=False, indent=2))
        else:
            print("Elyan bootstrap durumu")
            print(f"  setup_complete: {status.get('setup_complete')}")
            print(f"  installed:      {status.get('installed')}")
            print(f"  onboarded:       {status.get('onboarded')}")
            print(f"  restored:        {status.get('restored')}")
            print(f"  vault:           {status.get('runtime', {}).get('config', {}).get('provider', '-')}")
        return 0
    if action == "install":
        result = manager.install(headless=bool(getattr(args, "headless", False)), force=bool(getattr(args, "force", False)))
        print(result.get("message") or "Kurulum tamamlandı.")
        return 0 if result.get("ok") else 1
    if action == "onboard":
        result = manager.onboard(
            headless=bool(getattr(args, "headless", False)),
            channel=getattr(args, "channel", None),
            install_daemon=bool(getattr(args, "install_daemon", False)),
            force=bool(getattr(args, "force", False)),
        )
        print(result.get("message") or "Onboarding tamamlandı.")
        return 0 if result.get("ok") else 1
    if action == "repair":
        result = manager.repair(force=bool(getattr(args, "force", False)))
        print(result.get("message") or "Onarım tamamlandı.")
        return 0 if result.get("ok") else 1
    if action == "restore":
        result = manager.restore(bundle_path=getattr(args, "bundle", None))
        print(f"Geri yükleme tamamlandı: {result.get('bundle_path')}")
        return 0 if result.get("ok") else 1
    if action == "snapshot":
        result = manager.export_bundle(output=getattr(args, "output", None))
        print(f"Yedek oluşturuldu: {result.get('bundle_path')}")
        return 0 if result.get("ok") else 1
    print("Usage: elyan bootstrap [status|install|onboard|repair|restore|snapshot]")
    return 1


def run(args) -> int:
    return handle_bootstrap(args)
