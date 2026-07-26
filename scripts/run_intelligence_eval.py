"""Zekâ eval setini CANLI modelle koşturur ve geçti/kaldı tablosu basar.

Kullanım:
    PYTHONPATH=. python scripts/run_intelligence_eval.py
    PYTHONPATH=. python scripts/run_intelligence_eval.py --json
    PYTHONPATH=. python scripts/run_intelligence_eval.py --only gonderme_cozulur

Çıkış kodu: 0 = hiç kaldı yok; 1 = en az bir senaryo kaldı; 2 = backend yok
(hiçbir senaryo ölçülemedi). Böylece CI/el koşusu ayrımsız kullanılabilir.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Elyan zekâ eval seti")
    parser.add_argument("--json", action="store_true", help="makine okunur çıktı")
    parser.add_argument("--only", nargs="*", default=None, help="yalnız bu senaryo id'leri")
    args = parser.parse_args()

    from runtime import agent_decider, intelligence_eval, state_store
    from runtime.backend_client import BackendClient
    from runtime.bridge import _server_brain_structured_plan

    try:
        live_state = state_store.load_state()
    except Exception:
        live_state = None

    backend = BackendClient(os.environ.get("APP_BASE_URL"))
    if not backend.configured:
        print(
            "backend yapılandırılmamış (APP_BASE_URL yok) — canlı eval koşulamaz.",
            file=sys.stderr,
        )
        return 2

    def send_prompt_factory(message: str):
        # userText: kapılar zarf şablonunu değil kullanıcı cümlesini denetler.
        return agent_decider.make_backend_send_prompt(
            lambda prompt: _server_brain_structured_plan(
                backend, prompt, user_text=message
            )
        )

    report = intelligence_eval.run_intelligence_eval(
        send_prompt_factory=send_prompt_factory, only=args.only, state=live_state
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(intelligence_eval.format_report(report))

    if report["total"] > 0 and report["skipped"] == report["total"]:
        print("uyarı: tüm senaryolar atlandı (model erişilemedi).", file=sys.stderr)
        return 2
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
