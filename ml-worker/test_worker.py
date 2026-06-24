from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import worker


class WorkerScoringTests(unittest.TestCase):
    def test_build_safe_metrics_is_deterministic_and_safe(self) -> None:
        job = {
            "id": "11111111-1111-4111-8111-111111111111",
            "config": {
                "trainingBackend": "pytorch_cpu_safe",
                "adapterMode": "quantum_neural_eval",
                "quantumBenchmarkScore": 0.82,
            },
        }
        dataset = {
            "id": "22222222-2222-4222-8222-222222222222",
            "scope": "shared",
            "record_count": 128,
            "token_estimate": 12_000,
            "metadata": {
                "problemClass": "quantum_optimization",
                "datasetSnapshot": {
                    "approvedCorrectionCount": 3,
                    "compactedRecordCount": 2,
                    "freshSignalCount": 2,
                    "correctionDensity": 0.6667,
                    "freshSignalRatio": 1.0,
                    "signalFreshnessScore": 0.8432,
                    "lineageScore": 1.0,
                    "compactionQualityScore": 0.8221,
                    "compactDatasetEligible": True,
                    "sourceLineage": "approved_corrections",
                },
            },
        }

        first = worker.build_safe_metrics(job, dataset, "pytorch_cpu_safe", "quantum_neural_eval")
        second = worker.build_safe_metrics(job, dataset, "pytorch_cpu_safe", "quantum_neural_eval")

        self.assertEqual(first, second)
        self.assertEqual(first["quantumBenchmarkScore"], 0.82)
        self.assertEqual(first["evaluationState"], "bounded_offline_eval")
        self.assertEqual(first["promotionGate"], "ready")
        self.assertEqual(first["compactionQualityScore"], 0.8221)
        self.assertGreaterEqual(first["evaluationScore"], 0.72)
        self.assertGreaterEqual(first["datasetQualityScore"], 0.7)
        self.assertRegex(first["datasetFingerprint"], r"^[a-f0-9]{64}$")

        original_optional_libraries = worker.optional_libraries
        try:
            worker.optional_libraries = lambda: {  # type: ignore[assignment]
                "numpy": False,
                "scikitLearn": False,
                "sentenceTransformers": False,
                "torch": False,
            }
            without_optional_libs = worker.build_safe_metrics(job, dataset, "pytorch_cpu_safe", "quantum_neural_eval")
        finally:
            worker.optional_libraries = original_optional_libraries

        self.assertEqual(first, without_optional_libs)

    def test_heartbeat_payload_exposes_runner_fields_without_private_data(self) -> None:
        payload = worker.heartbeat_payload(None, last_job_at="2030-01-01T00:00:00Z", last_error_code=None)

        self.assertEqual(payload["mode"], "runner")
        self.assertEqual(payload["lastJobAt"], "2030-01-01T00:00:00Z")
        self.assertIsNone(payload["lastErrorCode"])
        self.assertEqual(payload["runnerBacklog"], 0)
        self.assertIn("optionalLibraries", payload)
        self.assertIn("brain.neural.eval", payload["capabilities"])
        self.assertNotIn("DATABASE_URL", str(payload))
        self.assertNotIn("REDIS_URL", str(payload))

    def test_failed_dataset_path_uses_safe_code(self) -> None:
        error = RuntimeError("private /Users/example/path should not leak")

        self.assertEqual(worker.safe_error_code(error), "ML_WORKER_JOB_FAILED")


if __name__ == "__main__":
    unittest.main()
