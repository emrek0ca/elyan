#!/usr/bin/env python3
"""Hafta-1 stabilizasyon baseline runner.

Yeni feature eklemeden mevcut sistemi sayısallaştırır:
- sabit komut seti
- hata sınıf / frekans / etki raporu
- günlük kalite notu (dashboard'a taşınabilir markdown)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts" / "stability"

ERROR_IMPACT = {
    "PLAN_ERROR": "P1",
    "TOOL_ERROR": "P1",
    "ENV_ERROR": "P0",
    "VALIDATION_ERROR": "P1",
    "CALLBACK_MISMATCH": "P0",
    "TEST_FAILURE": "P1",
    "TIMEOUT": "P0",
    "DEPENDENCY_ERROR": "P0",
    "NETWORK_ERROR": "P1",
    "UNKNOWN_ERROR": "P2",
}

ERROR_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("PLAN_ERROR", re.compile(r"\bPLAN_ERROR\b")),
    ("TOOL_ERROR", re.compile(r"\bTOOL_ERROR\b")),
    ("ENV_ERROR", re.compile(r"\bENV_ERROR\b")),
    ("VALIDATION_ERROR", re.compile(r"\bVALIDATION_ERROR\b")),
    ("CALLBACK_MISMATCH", re.compile(r"(callback|onay).*(stale|mismatch|alias|user)", re.I)),
    ("TIMEOUT", re.compile(r"(timed out|timeout|TimeoutError)", re.I)),
    ("DEPENDENCY_ERROR", re.compile(r"(ModuleNotFoundError|ImportError|No module named)", re.I)),
    ("NETWORK_ERROR", re.compile(r"(ConnectionError|ReadTimeout|Max retries exceeded|Temporary failure)", re.I)),
]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    command: list[str]
    timeout_s: int


@dataclass
class CommandResult:
    name: str
    command: list[str]
    returncode: int
    duration_s: float
    stdout: str
    stderr: str
    error_classes: list[str]
    log_path: str = ""

    @property
    def passed(self) -> bool:
        return self.returncode == 0


def _python_bin() -> str:
    venv_py = ROOT / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable or "python3"


def _command_set(profile: str) -> list[CommandSpec]:
    py = _python_bin()
    compile_targets = [
        "core/agent.py",
        "core/pipeline.py",
        "core/spec/task_spec.py",
        "core/gateway/router.py",
        "core/gateway/adapters/telegram.py",
        "core/runtime_policy.py",
        "core/gateway/server.py",
    ]
    base = [
        CommandSpec("doctor", ["bash", "scripts/doctor.sh"], 120),
        CommandSpec("py_compile_focus", [py, "-m", "py_compile", *compile_targets], 180),
        CommandSpec("unit_gateway_core", [py, "-m", "pytest", "tests/unit/test_gateway_router.py", "tests/unit/test_gateway_adapters.py", "-q"], 900),
        CommandSpec("unit_agent_routing", [py, "-m", "pytest", "tests/unit/test_agent_routing.py", "-q"], 1200),
    ]
    if profile == "quick":
        return base[:3]
    return base


def _extract_error_classes(text: str, returncode: int) -> list[str]:
    found: set[str] = set()
    for code, rx in ERROR_PATTERNS:
        if rx.search(text):
            found.add(code)
    if returncode != 0 and not found:
        if "FAILED" in text or "AssertionError" in text:
            found.add("TEST_FAILURE")
        else:
            found.add("UNKNOWN_ERROR")
    return sorted(found)


def _run_command(spec: CommandSpec, logs_dir: Path) -> CommandResult:
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            spec.command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=spec.timeout_s,
            check=False,
        )
        duration = time.perf_counter() - start
        merged = f"{proc.stdout}\n{proc.stderr}"
        result = CommandResult(
            name=spec.name,
            command=spec.command,
            returncode=proc.returncode,
            duration_s=duration,
            stdout=proc.stdout,
            stderr=proc.stderr,
            error_classes=_extract_error_classes(merged, proc.returncode),
        )
        log_file = logs_dir / f"{spec.name}.log"
        log_file.write_text(
            "\n".join(
                [
                    f"$ {' '.join(shlex.quote(x) for x in spec.command)}",
                    f"[returncode] {result.returncode}",
                    "",
                    "[stdout]",
                    result.stdout,
                    "",
                    "[stderr]",
                    result.stderr,
                ]
            ),
            encoding="utf-8",
        )
        result.log_path = str(log_file)
        return result
    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - start
        merged = f"{exc.stdout or ''}\n{exc.stderr or ''}\nTIMEOUT"
        result = CommandResult(
            name=spec.name,
            command=spec.command,
            returncode=124,
            duration_s=duration,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + "\nTIMEOUT",
            error_classes=_extract_error_classes(merged, 124),
        )
        log_file = logs_dir / f"{spec.name}.log"
        log_file.write_text(
            "\n".join(
                [
                    f"$ {' '.join(shlex.quote(x) for x in spec.command)}",
                    "[returncode] 124",
                    "",
                    "[stdout]",
                    result.stdout,
                    "",
                    "[stderr]",
                    result.stderr,
                ]
            ),
            encoding="utf-8",
        )
        result.log_path = str(log_file)
        return result


def _aggregate_errors(results: Iterable[CommandResult]) -> list[dict]:
    freq: dict[str, int] = {}
    for res in results:
        for code in res.error_classes:
            freq[code] = freq.get(code, 0) + 1
    rows = [
        {"code": code, "count": count, "impact": ERROR_IMPACT.get(code, "P2")}
        for code, count in sorted(freq.items(), key=lambda x: (-x[1], x[0]))
    ]
    return rows


def _write_markdown(
    target: Path,
    run_id: str,
    profile: str,
    results: list[CommandResult],
    errors: list[dict],
    started_at: str,
) -> None:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    success_rate = (passed / total * 100.0) if total else 0.0
    lines = [
        f"# Stability Baseline Report ({run_id})",
        "",
        f"- Tarih: {started_at}",
        f"- Profil: `{profile}`",
        f"- Komut başarısı: `{passed}/{total}` (%{success_rate:.1f})",
        "",
        "## Komut Sonuçları",
        "",
        "| Komut | Durum | Süre (sn) | Çıkış Kodu | Log |",
        "|---|---:|---:|---:|---|",
    ]
    for r in results:
        lines.append(
            f"| `{r.name}` | {'PASS' if r.passed else 'FAIL'} | {r.duration_s:.2f} | {r.returncode} | `{r.log_path}` |"
        )
    lines.extend(["", "## Hata Envanteri (Sınıf / Frekans / Etki)", ""])
    if errors:
        lines.extend([
            "| Hata Kodu | Frekans | Etki |",
            "|---|---:|---:|",
        ])
        for item in errors:
            lines.append(f"| `{item['code']}` | {item['count']} | {item['impact']} |")
    else:
        lines.append("- Hata bulunmadı.")
    lines.extend(
        [
            "",
            "## Günlük Kalite Notu",
            "",
            "- Bugün düzelenler: Bu raporda FAIL olmayan komutlar stabil kabul edildi.",
            "- Kalan riskler: FAIL komutları P0/P1 önceliklendirmesi ile ele alınmalı.",
            "- Yarın planı: Hata envanterindeki en yüksek frekanslı iki sınıfa odaklan.",
            "",
        ]
    )
    target.write_text("\n".join(lines), encoding="utf-8")


def _write_json(
    target: Path,
    run_id: str,
    profile: str,
    results: list[CommandResult],
    errors: list[dict],
    started_at: str,
) -> None:
    payload = {
        "run_id": run_id,
        "started_at": started_at,
        "profile": profile,
        "kpi": {
            "commands_total": len(results),
            "commands_passed": sum(1 for r in results if r.passed),
            "commands_failed": sum(1 for r in results if not r.passed),
        },
        "commands": [
            {
                "name": r.name,
                "command": " ".join(shlex.quote(x) for x in r.command),
                "status": "PASS" if r.passed else "FAIL",
                "returncode": r.returncode,
                "duration_s": round(r.duration_s, 3),
                "error_classes": r.error_classes,
                "log_path": r.log_path,
            }
            for r in results
        ],
        "error_inventory": errors,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Elyan Hafta-1 baseline raporu üretir.")
    parser.add_argument(
        "--profile",
        choices=("quick", "full"),
        default="quick",
        help="quick: hızlı set, full: daha geniş unit kapsamı",
    )
    args = parser.parse_args()

    started = dt.datetime.now().astimezone()
    run_id = started.strftime("baseline_%Y%m%d_%H%M%S")
    out_dir = ARTIFACT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    specs = _command_set(args.profile)
    results = [_run_command(spec, logs_dir) for spec in specs]
    errors = _aggregate_errors(results)

    report_md = out_dir / "report.md"
    report_json = out_dir / "report.json"
    daily_note = out_dir / "daily_quality_note.md"
    started_at = started.strftime("%Y-%m-%d %H:%M:%S %Z")

    _write_markdown(report_md, run_id, args.profile, results, errors, started_at)
    _write_json(report_json, run_id, args.profile, results, errors, started_at)

    # Dashboard veya hızlı paylaşım için kısa not kopyası.
    daily_note.write_text(
        "\n".join(
            [
                f"# Daily Quality Note ({run_id})",
                "",
                f"- Rapor: {report_md}",
                f"- JSON: {report_json}",
                f"- Toplam komut: {len(results)}",
                f"- Başarısız komut: {sum(1 for r in results if not r.passed)}",
            ]
        ),
        encoding="utf-8",
    )

    print(f"[STABILITY] run_id={run_id}")
    print(f"[STABILITY] report={report_md}")
    print(f"[STABILITY] json={report_json}")
    print(f"[STABILITY] daily_note={daily_note}")

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
