#!/usr/bin/env python3
"""
Elyan Gateway Yük Testi
========================
Çalışan bir Gateway'e concurrent HTTP isteği göndererek yük altında
performans ve hata oranını ölçer.

Kullanım:
  # Gateway çalışırken:
  python scripts/load_test.py                       # Varsayılan 50 istek
  python scripts/load_test.py --url http://localhost:18789
  python scripts/load_test.py --concurrency 20 --requests 200
  python scripts/load_test.py --suite health        # Sadece /health testi

Gereksinimler:
  pip install aiohttp
"""
import asyncio
import argparse
import json
import sys
import time
import statistics
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@dataclass
class RequestResult:
    url: str
    status: int
    latency_ms: float
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and 200 <= self.status < 300


@dataclass
class LoadTestResult:
    endpoint: str
    total_requests: int
    concurrency: int
    elapsed_s: float
    success_count: int
    error_count: int
    rps: float
    min_ms: float
    max_ms: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    errors: List[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.success_count / self.total_requests * 100 if self.total_requests else 0

    def print_summary(self):
        icon = "✅" if self.success_rate >= 99 else ("⚠️" if self.success_rate >= 90 else "❌")
        print(f"\n  {icon} {self.endpoint}")
        print(f"     İstekler: {self.total_requests} | Eş zamanlı: {self.concurrency} | Süre: {self.elapsed_s:.2f}s")
        print(f"     RPS: {self.rps:.1f} | Başarı: {self.success_rate:.1f}%")
        print(f"     Gecikme — p50: {self.p50_ms:.1f}ms | p95: {self.p95_ms:.1f}ms | max: {self.max_ms:.1f}ms")
        if self.errors:
            unique_errors = list(set(self.errors))[:3]
            for e in unique_errors:
                print(f"     ⚠️  Hata: {e}")


async def load_endpoint(
    session,
    url: str,
    method: str = "GET",
    json_body: Optional[dict] = None,
    semaphore: Optional[asyncio.Semaphore] = None,
) -> RequestResult:
    async with (semaphore or asyncio.Semaphore(1)):
        t0 = time.perf_counter()
        try:
            if method == "POST":
                async with session.post(url, json=json_body, timeout=10) as resp:
                    await resp.text()
                    return RequestResult(url=url, status=resp.status, latency_ms=(time.perf_counter() - t0) * 1000)
            else:
                async with session.get(url, timeout=10) as resp:
                    await resp.text()
                    return RequestResult(url=url, status=resp.status, latency_ms=(time.perf_counter() - t0) * 1000)
        except asyncio.TimeoutError:
            return RequestResult(url=url, status=0, latency_ms=(time.perf_counter() - t0) * 1000, error="timeout")
        except Exception as exc:
            return RequestResult(url=url, status=0, latency_ms=(time.perf_counter() - t0) * 1000, error=str(exc)[:80])


async def run_load_test(
    base_url: str,
    endpoint: str,
    total: int,
    concurrency: int,
    method: str = "GET",
    body: Optional[dict] = None,
) -> LoadTestResult:
    import aiohttp
    semaphore = asyncio.Semaphore(concurrency)
    url = f"{base_url.rstrip('/')}{endpoint}"

    t0 = time.perf_counter()
    async with aiohttp.ClientSession() as session:
        tasks = [
            load_endpoint(session, url, method=method, json_body=body, semaphore=semaphore)
            for _ in range(total)
        ]
        results: List[RequestResult] = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - t0

    successes = [r for r in results if r.success]
    latencies = sorted(r.latency_ms for r in results)
    errors = [r.error for r in results if r.error]

    def pct(lst, p):
        idx = max(0, int(len(lst) * p) - 1)
        return lst[idx]

    return LoadTestResult(
        endpoint=endpoint,
        total_requests=total,
        concurrency=concurrency,
        elapsed_s=elapsed,
        success_count=len(successes),
        error_count=len(results) - len(successes),
        rps=total / elapsed if elapsed > 0 else 0,
        min_ms=latencies[0] if latencies else 0,
        max_ms=latencies[-1] if latencies else 0,
        mean_ms=statistics.mean(latencies) if latencies else 0,
        p50_ms=pct(latencies, 0.50) if latencies else 0,
        p95_ms=pct(latencies, 0.95) if latencies else 0,
        p99_ms=pct(latencies, 0.99) if latencies else 0,
        errors=errors,
    )


# ── Test Suiteler ─────────────────────────────────────────────────────────────

async def suite_health(base_url: str, total: int, concurrency: int) -> List[LoadTestResult]:
    """Temel sağlık endpoint testi."""
    results = []
    r = await run_load_test(base_url, "/health", total, concurrency)
    results.append(r)
    r.print_summary()
    return results


async def suite_api(base_url: str, total: int, concurrency: int) -> List[LoadTestResult]:
    """API endpoint yük testi."""
    results = []
    endpoints = [
        ("/api/status", "GET", None),
        ("/api/analytics", "GET", None),
        ("/api/activity", "GET", None),
    ]
    for endpoint, method, body in endpoints:
        r = await run_load_test(base_url, endpoint, total // len(endpoints), concurrency, method, body)
        results.append(r)
        r.print_summary()
    return results


async def suite_message(base_url: str, total: int, concurrency: int) -> List[LoadTestResult]:
    """Mesaj işleme endpoint testi (yüksek yük)."""
    results = []
    bodies = [
        {"text": "merhaba", "user_id": "load_test_user", "channel": "web"},
        {"text": "ekran görüntüsü al", "user_id": "load_test_user", "channel": "web"},
        {"text": "saat kaç", "user_id": "load_test_user", "channel": "web"},
    ]
    for i, body in enumerate(bodies):
        r = await run_load_test(
            base_url, "/api/message",
            total // len(bodies), concurrency, "POST", body
        )
        results.append(r)
        r.print_summary()
    return results


SUITES = {
    "health": suite_health,
    "api": suite_api,
    "message": suite_message,
}


async def main_async(args):
    print(f"\n⚡ Elyan Yük Testi")
    print(f"   Hedef: {args.url}")
    print(f"   İstekler: {args.requests} | Eş zamanlı: {args.concurrency}")
    print("─" * 60)

    # Gateway'in ayakta olup olmadığını kontrol et
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{args.url}/health", timeout=3) as resp:
                if resp.status != 200:
                    print(f"  ❌ Gateway çalışmıyor veya sağlıklı değil (HTTP {resp.status})")
                    return 1
    except Exception as exc:
        print(f"  ❌ Gateway'e ulaşılamıyor: {exc}")
        print(f"  → Önce 'elyan gateway start' veya 'python main.py --cli' çalıştırın.")
        return 1

    print(f"  ✅ Gateway çalışıyor")

    suites_to_run = [args.suite] if args.suite else list(SUITES.keys())
    all_results = []

    for suite_name in suites_to_run:
        print(f"\n🔥 Suite: {suite_name}")
        suite_fn = SUITES[suite_name]
        results = await suite_fn(args.url, args.requests, args.concurrency)
        all_results.extend(results)

    # Genel özet
    total_reqs = sum(r.total_requests for r in all_results)
    total_ok = sum(r.success_count for r in all_results)
    overall_rate = total_ok / total_reqs * 100 if total_reqs else 0
    p95_all = statistics.mean(r.p95_ms for r in all_results) if all_results else 0

    print(f"\n{'═' * 60}")
    print(f"  GENEL SONUÇ: {total_ok}/{total_reqs} başarılı ({overall_rate:.1f}%)")
    print(f"  Ortalama p95 gecikme: {p95_all:.1f}ms")
    print(f"{'═' * 60}\n")

    if args.output:
        with open(args.output, "w") as f:
            json.dump([asdict(r) for r in all_results], f, indent=2)
        print(f"  💾 Sonuçlar kaydedildi: {args.output}")

    return 0 if overall_rate >= 99 else 1


def main():
    parser = argparse.ArgumentParser(description="Elyan Gateway Yük Testi")
    parser.add_argument("--url", default="http://127.0.0.1:18789", help="Gateway URL")
    parser.add_argument("--requests", type=int, default=50, help="Toplam istek sayısı")
    parser.add_argument("--concurrency", type=int, default=10, help="Eş zamanlı istek sayısı")
    parser.add_argument("--suite", choices=list(SUITES.keys()), help="Tek suite çalıştır")
    parser.add_argument("--output", metavar="FILE", help="JSON çıktı dosyası")
    args = parser.parse_args()

    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
