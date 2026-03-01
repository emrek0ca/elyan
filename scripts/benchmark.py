#!/usr/bin/env python3
"""
Elyan Performance Benchmark Suite
===================================
Sistem performansını ölçer ve hedef metriklerle karşılaştırır.

Kullanım:
  python scripts/benchmark.py               # Tüm testler
  python scripts/benchmark.py --suite intent # Sadece intent testleri
  python scripts/benchmark.py --json         # JSON çıktı
  python scripts/benchmark.py --compare baseline.json  # Önceki sonuçla karşılaştır

Hedef Metrikler (roadmap):
  - Intent parse:    <10ms
  - Fuzzy match:     <20ms
  - Cache hit:       <5ms
  - Fast response:   <100ms
  - LLM chat:        <2000ms (ağa bağlı)
"""
import asyncio
import json
import os
import sys
import time
import statistics
import argparse
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Dict, Any

# Proje kökünü path'e ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Hedef eşikler (ms)
THRESHOLDS = {
    "intent_parse_ms": 10,
    "fuzzy_match_ms": 20,
    "response_cache_hit_ms": 5,
    "fast_response_ms": 100,
    "task_engine_plan_ms": 500,
    "llm_chat_ms": 2000,
    "settings_load_ms": 50,
    "memory_query_ms": 30,
}

SAMPLES = 50  # Her test için örnek sayısı


@dataclass
class BenchResult:
    name: str
    samples: int
    min_ms: float
    max_ms: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    threshold_ms: Optional[float]
    passed: bool
    error: Optional[str] = None

    def to_row(self) -> str:
        status = "✅" if self.passed else "❌"
        thr = f"{self.threshold_ms:.0f}" if self.threshold_ms else "—"
        if self.error:
            return f"  {status} {self.name:<40} ERROR: {self.error}"
        return (
            f"  {status} {self.name:<40} "
            f"p50={self.p50_ms:>6.2f}ms  "
            f"p95={self.p95_ms:>6.2f}ms  "
            f"max={self.max_ms:>6.2f}ms  "
            f"thresh={thr}ms"
        )


def bench(name: str, fn, threshold_ms: Optional[float] = None, samples: int = SAMPLES) -> BenchResult:
    """Sync fonksiyon benchmark."""
    times = []
    error = None
    for _ in range(samples):
        t0 = time.perf_counter()
        try:
            fn()
        except Exception as exc:
            error = str(exc)
            break
        times.append((time.perf_counter() - t0) * 1000)

    if error or not times:
        return BenchResult(
            name=name, samples=0, min_ms=0, max_ms=0,
            mean_ms=0, p50_ms=0, p95_ms=0, p99_ms=0,
            threshold_ms=threshold_ms, passed=False, error=error or "no data",
        )
    times.sort()
    p50 = statistics.median(times)
    p95 = times[int(len(times) * 0.95)]
    p99 = times[int(len(times) * 0.99)]
    passed = (threshold_ms is None) or (p95 <= threshold_ms)
    return BenchResult(
        name=name, samples=len(times),
        min_ms=times[0], max_ms=times[-1],
        mean_ms=statistics.mean(times),
        p50_ms=p50, p95_ms=p95, p99_ms=p99,
        threshold_ms=threshold_ms, passed=passed,
    )


def bench_async(name: str, coro_fn, threshold_ms: Optional[float] = None, samples: int = SAMPLES) -> BenchResult:
    """Async fonksiyon benchmark."""
    times = []
    error = None

    async def run_all():
        nonlocal error
        for _ in range(samples):
            t0 = time.perf_counter()
            try:
                await coro_fn()
            except Exception as exc:
                error = str(exc)
                return
            times.append((time.perf_counter() - t0) * 1000)

    asyncio.run(run_all())

    if error or not times:
        return BenchResult(
            name=name, samples=0, min_ms=0, max_ms=0,
            mean_ms=0, p50_ms=0, p95_ms=0, p99_ms=0,
            threshold_ms=threshold_ms, passed=False, error=error or "no data",
        )
    times.sort()
    p50 = statistics.median(times)
    p95 = times[int(len(times) * 0.95)]
    p99 = times[int(len(times) * 0.99)]
    passed = (threshold_ms is None) or (p95 <= threshold_ms)
    return BenchResult(
        name=name, samples=len(times),
        min_ms=times[0], max_ms=times[-1],
        mean_ms=statistics.mean(times),
        p50_ms=p50, p95_ms=p95, p99_ms=p99,
        threshold_ms=threshold_ms, passed=passed,
    )


# ── Benchmark Suiteler ────────────────────────────────────────────────────────

def suite_intent() -> List[BenchResult]:
    """Intent Parser performansı."""
    print("\n📐 Intent Parser Suite")
    results = []
    try:
        from core.intent_parser import IntentParser
        parser = IntentParser()
        cases = [
            ("screenshot", "ekran görüntüsü al"),
            ("open_app", "safari aç"),
            ("volume", "sesi yüzde elli yap"),
            ("research", "python hakkında araştırma yap"),
            ("close_app", "chrome kapat"),
            ("create_folder", "belgeler klasörü oluştur"),
            ("greeting", "merhaba"),
        ]
        for label, text in cases:
            r = bench(
                f"intent_parse/{label}", lambda t=text: parser.parse(t),
                threshold_ms=THRESHOLDS["intent_parse_ms"],
                samples=100,
            )
            results.append(r)
            print(r.to_row())
    except Exception as exc:
        print(f"  ⚠️  Intent suite yüklenemedi: {exc}")
    return results


def suite_fuzzy() -> List[BenchResult]:
    """Fuzzy Intent Matcher performansı."""
    print("\n🔍 Fuzzy Intent Suite")
    results = []
    try:
        from core.fuzzy_intent import FuzzyIntentMatcher
        matcher = FuzzyIntentMatcher()
        cases = [
            ("normalize_simple", "bi ss atsana"),
            ("normalize_suffix", "chrome'u kapat"),
            ("fuzzy_screenshot", "bi ss atsana"),
            ("fuzzy_volume", "abi sesi bi kis ya"),
            ("fuzzy_open_chrome", "chrome'u aç bana"),
        ]
        r_norm = bench(
            "fuzzy/normalize_turkish",
            lambda: matcher.normalize_turkish("abi sesi bi kis ya chrome'u kapat"),
            threshold_ms=THRESHOLDS["fuzzy_match_ms"],
            samples=200,
        )
        results.append(r_norm)
        print(r_norm.to_row())

        for label, text in cases:
            r = bench(
                f"fuzzy/match_{label}", lambda t=text: matcher.match(t),
                threshold_ms=THRESHOLDS["fuzzy_match_ms"],
                samples=100,
            )
            results.append(r)
            print(r.to_row())
    except Exception as exc:
        print(f"  ⚠️  Fuzzy suite yüklenemedi: {exc}")
    return results


def suite_cache() -> List[BenchResult]:
    """Response cache performansı."""
    print("\n⚡ Cache Suite")
    results = []
    try:
        from core.response_cache import ResponseCache
        cache = ResponseCache()
        key = "test_benchmark_key"
        cache.set(key, "cached response")

        r_hit = bench(
            "cache/hit",
            lambda: cache.get(key),
            threshold_ms=THRESHOLDS["response_cache_hit_ms"],
            samples=500,
        )
        results.append(r_hit)
        print(r_hit.to_row())

        r_miss = bench(
            "cache/miss",
            lambda: cache.get("nonexistent_key_xyz"),
            threshold_ms=THRESHOLDS["response_cache_hit_ms"] * 2,
            samples=500,
        )
        results.append(r_miss)
        print(r_miss.to_row())
    except Exception as exc:
        print(f"  ⚠️  Cache suite yüklenemedi: {exc}")
    return results


def suite_settings() -> List[BenchResult]:
    """Settings/Config yükleme performansı."""
    print("\n⚙️  Settings Suite")
    results = []
    try:
        r = bench(
            "settings/load_defaults",
            lambda: __import__("config.settings_manager", fromlist=["DEFAULT_SETTINGS"]).DEFAULT_SETTINGS,
            threshold_ms=THRESHOLDS["settings_load_ms"],
            samples=50,
        )
        results.append(r)
        print(r.to_row())
    except Exception as exc:
        print(f"  ⚠️  Settings suite yüklenemedi: {exc}")

    try:
        from config.elyan_config import elyan_config
        r2 = bench(
            "settings/elyan_config_get",
            lambda: elyan_config.get("models.default.provider", "groq"),
            threshold_ms=THRESHOLDS["settings_load_ms"],
            samples=200,
        )
        results.append(r2)
        print(r2.to_row())
    except Exception as exc:
        print(f"  ⚠️  elyan_config suite yüklenemedi: {exc}")
    return results


def suite_quick_intent() -> List[BenchResult]:
    """Quick Intent (kurallı hızlı path) performansı."""
    print("\n⚡ Quick Intent Suite")
    results = []
    try:
        from core.quick_intent import QuickIntent
        qi = QuickIntent()
        cases = [
            ("screenshot", "ekran görüntüsü al"),
            ("volume_mute", "sesi kapat"),
            ("greeting", "merhaba"),
            ("time", "saat kaç"),
            ("calc", "5 çarpı 7"),
        ]
        for label, text in cases:
            r = bench(
                f"quick_intent/{label}", lambda t=text: qi.check(t),
                threshold_ms=5,  # Quick intent çok hızlı olmalı
                samples=200,
            )
            results.append(r)
            print(r.to_row())
    except Exception as exc:
        print(f"  ⚠️  Quick intent suite yüklenemedi: {exc}")
    return results


def suite_fast_response() -> List[BenchResult]:
    """Fast Response (sync path) performansı."""
    print("\n🚀 Fast Response Suite")
    results = []
    try:
        from core.fast_response import FastResponse
        fr = FastResponse()
        cases = [
            ("greeting_tr", "merhaba"),
            ("greeting_en", "hello"),
            ("time_query", "saat kaç"),
            ("calc", "123 artı 456"),
            ("unknown", "python nedir"),
        ]
        for label, text in cases:
            r = bench(
                f"fast_response/{label}", lambda t=text: fr.try_handle(t),
                threshold_ms=THRESHOLDS["fast_response_ms"],
                samples=100,
            )
            results.append(r)
            print(r.to_row())
    except Exception as exc:
        print(f"  ⚠️  Fast response suite yüklenemedi: {exc}")
    return results


def suite_memory() -> List[BenchResult]:
    """Memory sistemi performansı."""
    print("\n🧠 Memory Suite")
    results = []
    try:
        from core.memory import Memory
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = f.name

        mem = Memory(db_path=tmp_path)
        # Önce bazı veri ekle
        for i in range(100):
            mem.store_conversation(
                user_id=1,
                user_message=f"test message {i}",
                bot_response={"text": f"response {i}", "action": "chat", "success": True},
            )

        r_read = bench(
            "memory/get_recent",
            lambda: mem.get_recent_conversations(user_id=1, limit=10),
            threshold_ms=THRESHOLDS["memory_query_ms"],
            samples=100,
        )
        results.append(r_read)
        print(r_read.to_row())

        r_search = bench(
            "memory/search",
            lambda: mem.search_conversations(user_id=1, query="test", limit=5),
            threshold_ms=THRESHOLDS["memory_query_ms"] * 2,
            samples=50,
        )
        results.append(r_search)
        print(r_search.to_row())

        r_write = bench(
            "memory/store_conversation",
            lambda: mem.store_conversation(1, "bench", {"text": "x", "action": "chat", "success": True}),
            threshold_ms=THRESHOLDS["memory_query_ms"],
            samples=50,
        )
        results.append(r_write)
        print(r_write.to_row())

        mem.close()
        os.unlink(tmp_path)
    except Exception as exc:
        print(f"  ⚠️  Memory suite yüklenemedi: {exc}")
    return results



def suite_pipeline() -> List[BenchResult]:
    """Pipeline Stage Profiler sonuçlarını ölçer."""
    print("\n🎬 Pipeline Suite")
    results = []
    try:
        from core.pipeline import PipelineRunner, PipelineContext
        from core.agent import Agent
        runner = PipelineRunner()
        agent = Agent()
        ctx = PipelineContext(user_input="merhaba", role="chat")
        
        async def run_pipeline():
            await runner.run(ctx, agent)
            
        r = bench_async(
            "pipeline/full_run_chat",
            run_pipeline,
            threshold_ms=5000,
            samples=5
        )
        results.append(r)
        print(r.to_row())
    except Exception as exc:
        print(f"  ⚠️  Pipeline suite yüklenemedi: {exc}")
    return results


def suite_startup() -> List[BenchResult]:
    """Sistem açılış hızı (import + init)."""
    print("\n🏁 Startup Suite")
    results = []
    try:
        def import_core():
            # Use __import__ to avoid caching issues during repeats if possible
            import core.agent
            import core.pipeline
            
        r = bench(
            "startup/core_imports",
            import_core,
            threshold_ms=2000,
            samples=10
        )
        results.append(r)
        print(r.to_row())
    except Exception as exc:
        print(f"  ⚠️  Startup suite yüklenemedi: {exc}")
    return results

# ── Ana Çalıştırıcı ───────────────────────────────────────────────────────────

SUITES = {
    "intent": suite_intent,
    "fuzzy": suite_fuzzy,
    "cache": suite_cache,
    "settings": suite_settings,
    "quick_intent": suite_quick_intent,
    "fast_response": suite_fast_response,
    "memory": suite_memory,
    "pipeline": suite_pipeline,
    "startup": suite_startup,
}


def print_summary(all_results: List[BenchResult]) -> int:
    """Özet tablosu yaz, çıkış kodu döndür (0=geçti, 1=başarısız)."""
    passed = [r for r in all_results if r.passed]
    failed = [r for r in all_results if not r.passed]

    print("\n" + "═" * 72)
    print(f"  SONUÇ: {len(passed)}/{len(all_results)} test geçti")
    print("═" * 72)
    if failed:
        print("\n❌ Başarısız testler:")
        for r in failed:
            print(r.to_row())
    print()
    return 0 if not failed else 1


def compare_with_baseline(current: List[BenchResult], baseline_path: str):
    """Mevcut sonuçları baseline ile karşılaştır."""
    try:
        with open(baseline_path) as f:
            baseline_raw = json.load(f)
        baseline = {item["name"]: item for item in baseline_raw}
        print("\n📊 Baseline Karşılaştırması")
        print(f"  {'Test':<40} {'Baseline p95':>12} {'Şimdi p95':>10} {'Fark':>8}")
        print("  " + "─" * 72)
        for r in current:
            if r.name in baseline:
                base_p95 = baseline[r.name]["p95_ms"]
                diff = r.p95_ms - base_p95
                sign = "+" if diff > 0 else ""
                icon = "🔴" if diff > base_p95 * 0.1 else ("🟢" if diff < 0 else "🟡")
                print(f"  {icon} {r.name:<40} {base_p95:>10.2f}ms {r.p95_ms:>8.2f}ms {sign}{diff:>+6.2f}ms")
    except FileNotFoundError:
        print(f"  ⚠️  Baseline bulunamadı: {baseline_path}")
    except Exception as exc:
        print(f"  ⚠️  Karşılaştırma hatası: {exc}")


def main():
    global SAMPLES

    _default_samples = SAMPLES
    parser = argparse.ArgumentParser(
        description="Elyan Performance Benchmark Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--suite", choices=list(SUITES.keys()), help="Tek suite çalıştır")
    parser.add_argument("--json", action="store_true", help="JSON formatında çıktı")
    parser.add_argument("--output", metavar="FILE", help="Sonuçları dosyaya kaydet")
    parser.add_argument("--compare", metavar="BASELINE", help="Baseline JSON ile karşılaştır")
    parser.add_argument("--samples", type=int, default=_default_samples,
                        help=f"Örnek sayısı (varsayılan: {_default_samples})")
    args = parser.parse_args()

    SAMPLES = args.samples

    print("🏁 Elyan Benchmark Suite başlatıldı")
    print(f"   Örnekler: {SAMPLES} | Çalışma ortamı: {sys.version.split()[0]}")

    suites_to_run = [args.suite] if args.suite else list(SUITES.keys())
    all_results: List[BenchResult] = []

    for suite_name in suites_to_run:
        results = SUITES[suite_name]()
        all_results.extend(results)

    exit_code = print_summary(all_results)

    if args.compare:
        compare_with_baseline(all_results, args.compare)

    results_dict = [asdict(r) for r in all_results]

    if args.json:
        print(json.dumps(results_dict, indent=2))

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results_dict, f, indent=2)
        print(f"\n💾 Sonuçlar kaydedildi: {args.output}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
