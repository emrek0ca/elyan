"""Zekâ eval'ini N kez koşturur ve KARARLILIK tablosu basar.

NEDEN
-----
Eval model tabanlıdır; tek koşu gürültülüdür. Aynı senaryo bir koşuda geçip
diğerinde kalabilir. "13/16 geçti" cümlesi tek koşudan çıkarıldığında ölçüm
değil TAHMİN olur — önceki oturumlar tam bu yüzden yanlış rapor verdi.

Bu koşucu her senaryoyu N kez ölçer ve senaryo başına geçme oranı üretir
(ör. ``chat_selamlasma  0/5``). Karar oranla verilir, tek koşuyla değil.

``degraded_skip`` (model erişilemedi) ne geçti ne kaldı sayılır; ayrı sütunda
raporlanır ki sağlayıcı tökezlemesi başarı ya da başarısızlık gibi görünmesin.

KULLANIM
--------
    PYTHONPATH=. python scripts/run_eval_stability.py --runs 5
    PYTHONPATH=. python scripts/run_eval_stability.py --runs 5 --only chat_selamlasma
    PYTHONPATH=. python scripts/run_eval_stability.py --runs 5 --json

Çıkış kodu: 0 = her senaryo eşiği (varsayılan 4/5 oranı) tutturdu;
1 = en az bir senaryo eşiğin altında; 2 = hiçbir şey ölçülemedi.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Elyan zekâ eval kararlılık koşucusu")
    parser.add_argument("--runs", type=int, default=5, help="senaryo başına koşu sayısı")
    parser.add_argument("--only", nargs="*", default=None, help="yalnız bu senaryo id'leri")
    parser.add_argument("--json", action="store_true", help="makine okunur çıktı")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        help="geçme oranı eşiği (varsayılan 0.8 = 5 koşuda 4)",
    )
    args = parser.parse_args()

    from runtime import agent_decider, intelligence_eval, state_store
    from runtime.backend_client import BackendClient
    from runtime.bridge import _server_brain_structured_plan

    # Gerçek state: eval canlı yolun gördüğü öz-model/izin/ekosistem bilgisini
    # görsün diye. Yoksa ölçüm production'ı değil boş bir kurguyu ölçer.
    try:
        live_state = state_store.load_state()
    except Exception:
        live_state = None

    backend = BackendClient(os.environ.get("APP_BASE_URL"))
    if not backend.configured:
        print("backend yapılandırılmamış (APP_BASE_URL yok).", file=sys.stderr)
        return 2

    def send_prompt_factory(message: str):
        return agent_decider.make_backend_send_prompt(
            lambda prompt: _server_brain_structured_plan(backend, prompt, user_text=message)
        )

    tally: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"passed": 0, "failed": 0, "skipped": 0, "intents": [], "failures": []}
    )
    for index in range(max(1, args.runs)):
        report = intelligence_eval.run_intelligence_eval(
            send_prompt_factory=send_prompt_factory, only=args.only, state=live_state
        )
        for case in report["cases"]:
            row = tally[case["id"]]
            if case["status"] == "passed":
                row["passed"] += 1
            elif case["status"] == "failed":
                row["failed"] += 1
                row["failures"].extend(case.get("failures", []))
            else:
                row["skipped"] += 1
            if case.get("intent"):
                row["intents"].append(case["intent"])
        if not args.json:
            print(
                f"koşu {index + 1}/{args.runs}: "
                f"{report['passed']} geçti / {report['failed']} kaldı / "
                f"{report['skipped']} atlandı",
                file=sys.stderr,
            )

    rows: list[dict[str, Any]] = []
    for scenario in intelligence_eval.SCENARIOS:
        name = scenario["id"]
        if name not in tally:
            continue
        row = tally[name]
        measured = row["passed"] + row["failed"]
        rate = (row["passed"] / measured) if measured else 0.0
        rows.append(
            {
                "id": name,
                "passed": row["passed"],
                "failed": row["failed"],
                "skipped": row["skipped"],
                "measured": measured,
                "rate": round(rate, 2),
                "stable": measured > 0 and rate >= args.threshold,
                # Aynı senaryonun koşular arası niyet dağılımı: kararsızlık
                # nerede oynuyor, tek bakışta görünsün.
                "intents": sorted(set(row["intents"])),
                "failures": sorted(set(row["failures"]))[:4],
            }
        )

    if args.json:
        print(json.dumps({"runs": args.runs, "rows": rows}, ensure_ascii=False, indent=2))
    else:
        unstable = [row for row in rows if not row["stable"]]
        print(
            f"\nKARARLILIK — {args.runs} koşu · "
            f"{len(rows) - len(unstable)}/{len(rows)} senaryo eşiği tutturdu "
            f"(eşik {args.threshold:.0%})\n"
        )
        for row in rows:
            mark = "✓" if row["stable"] else "✗"
            skip = f" ○{row['skipped']}" if row["skipped"] else ""
            print(f"  {mark} {row['id']:<32} {row['passed']}/{row['measured']}{skip}")
            if not row["stable"]:
                if row["intents"]:
                    print(f"      niyetler: {', '.join(row['intents'])}")
                for failure in row["failures"]:
                    print(f"      → {failure}")

    if not rows or all(row["measured"] == 0 for row in rows):
        print("uyarı: hiçbir senaryo ölçülemedi (model erişilemedi).", file=sys.stderr)
        return 2
    return 0 if all(row["stable"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
