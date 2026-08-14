import { buildApp } from "../../app/build-app.js";
import { runBrainBenchmark } from "./benchmark.js";

// ENV'İ YÜKLE — beş worker'ın hepsi bunu yapıyor, benchmark yapmıyordu.
//
// Deploy bu betiği KONTEYNER DIŞINDA koşturuyor (`cd /srv/elyan-backend &&
// npm run brain:benchmark`), yani compose'un enjekte ettiği ortam yok. Env
// dosyası okunmayınca `buildApp()` içindeki zod doğrulaması ilk zorunlu
// değişkende patlıyordu:
//   RUNTIME_SECRET_PEPPER: Required
// Hata aşağıdaki catch'te jenerik `status:"warn", case_count:0` yüküne
// dönüşüyor, deploy çıktısı da `runner_error` alanını basmadığı için sebep
// HİÇ görünmüyordu. Sonuç: her deploy'da "benchmark çalıştı ama 0 vaka" gibi
// görünen, aslında hiç başlamamış bir ölçüm.
try {
  process.loadEnvFile();
} catch (error) {
  const code =
    typeof error === "object" && error && "code" in error
      ? String((error as { code?: string }).code)
      : "";
  if (code !== "ENOENT") throw error;
}

const BENCHMARK_RESULT_BEGIN = "<<<ELYAN_BENCHMARK_RESULT";
const BENCHMARK_RESULT_END = "ELYAN_BENCHMARK_RESULT>>>";

let app: Awaited<ReturnType<typeof buildApp>> | null = null;

try {
  app = await buildApp();
  const result = await runBrainBenchmark(app, {
    persistSummary: true,
  });
  // İŞARETÇİ ŞART. `buildApp()` ayağa kalkarken pino JSON log satırları
  // basıyor; deploy scripti sonucu "ilk { → son }" diye dilimlediği için o
  // loglarla sonuç tek parçaya karışıp JSON.parse'ı patlatıyordu (ölçüldü:
  // 2026-08-14 deploy). Sonuç artık kendi sınırlarını taşıyor.
  console.log(BENCHMARK_RESULT_BEGIN);
  console.log(JSON.stringify(result, null, 2));
  console.log(BENCHMARK_RESULT_END);
} catch (error) {
  console.log(BENCHMARK_RESULT_BEGIN);
  console.log(
    JSON.stringify(
      {
        status: "warn",
        constitution_version: "2026-06-05.eval-first.v1",
        overall_score: 0,
        boundary_score: 0,
        reasoning_score: 0,
        clarification_score: 0,
        tool_use_score: 0,
        latency_score: 0,
        case_count: 0,
        live_model_case_count: 0,
        workload_case_count: 0,
        workload_pass_count: 0,
        cases: [],
        runner_error: error instanceof Error ? error.message : "benchmark_runner_failed",
      },
      null,
      2,
    ),
  );
  console.log(BENCHMARK_RESULT_END);
} finally {
  await app?.close();
}
