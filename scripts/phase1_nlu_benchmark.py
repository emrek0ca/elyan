#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.nlu.phase1_engine import get_phase1_engine


DEFAULT_SAMPLES = [
    {"text": "pytorch hakkında araştırma yap", "intent": "research_document_delivery"},
    {"text": "Fourier serileri hakkında araştırma yap", "intent": "research_document_delivery"},
    {"text": "word dosyası oluştur", "intent": "create_word_document"},
    {"text": "excel tablo hazırla", "intent": "create_excel"},
    {"text": "portfolyo websitesi yap html css js ile", "intent": "create_website"},
    {"text": "python ile bir uygulama yap", "intent": "create_coding_project"},
    {"text": "sesi kapat", "intent": "set_volume"},
    {"text": "ekran görüntüsü al", "intent": "take_screenshot"},
    {"text": "youtube aç", "intent": "open_url"},
    {"text": "bu metni özetle", "intent": "summarize_text"},
]


def load_samples(path: str | None) -> list[dict[str, str]]:
    if not path:
        return list(DEFAULT_SAMPLES)
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("samples"), list):
        return [item for item in payload["samples"] if isinstance(item, dict)]
    return list(DEFAULT_SAMPLES)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Elyan Phase 1 NLU engine.")
    parser.add_argument("--samples", help="JSON file with samples", default="")
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    args = parser.parse_args()

    engine = get_phase1_engine()
    samples = load_samples(args.samples or None)
    report = engine.benchmark(samples)
    report["taxonomy_size"] = engine.describe()["taxonomy_size"]
    report["backend"] = engine.describe()["backend"]

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("Phase 1 NLU Benchmark")
        print(f"Backend      : {report['backend']}")
        print(f"Taxonomy size: {report['taxonomy_size']}")
        print(f"Accuracy     : {report['accuracy']:.3f}")
        print(f"Coverage     : {report['coverage']:.3f}")
        print(f"Clarify rate : {report['clarify_rate']:.3f}")
        print(f"Avg latency  : {report['avg_latency_ms']:.2f} ms")
        print("")
        for row in report["rows"]:
            print(
                f"- {row['text']} -> {row['predicted_action']} "
                f"({row['confidence']:.2f}, {row['latency_ms']:.2f} ms)"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

