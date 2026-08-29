import assert from "node:assert/strict";
import test from "node:test";
import {
  SHARED_BRAIN_WORKLOAD_PROFILES,
  sharedBrainWorkloadValues,
} from "./workloads.js";
import { resolveReasoningEffort } from "./generation-policy.js";
import { MACHINE_JSON_HIGH_REASONING_FLOOR } from "./provider-request.js";

/**
 * BU DEĞİŞMEZ TEK TEK İŞ YÜKLERİNDE DEĞİL, HEPSİNDE ARANIR.
 *
 * Aynı arıza sınıfı İKİ KEZ canlıya çıktı ve iki kez ELLE düzeltildi:
 *
 *   planning           560 token   → /desktop/plan hiç başarılı olamıyordu
 *   document_generate  1.600 token → "pdf olarak ver" turunda 13 denemenin
 *                                    tamamı düştü, kullanıcı hiçbir çıktı almadı
 *
 * İkisinde de sebep aynıydı: gpt-oss ailesinde gizli düşünme turu
 * `max_tokens`a SAYILIR, `high` efor bütçeyi yer ve görünür JSON'a yer
 * kalmaz. Yarım JSON'u Groq 400 `json_validate_failed` ile reddeder.
 *
 * İlkini düzelten kişi ikincisini göremedi, çünkü her iş yükünün kendi testi
 * vardı ve kimse LİSTEYİ taramıyordu. Üçüncüsü de aynı şekilde kaçardı.
 * Bu test listeyi tarar: yeni bir iş yükü eklendiğinde ya bütçesi yeterli
 * olur ya da bu test düşer.
 */
test("no high-reasoning workload is left without room for its JSON body", () => {
  const starved: string[] = [];
  for (const workload of sharedBrainWorkloadValues) {
    const effort = resolveReasoningEffort(workload, undefined);
    if (effort !== "high") continue;
    const profile = SHARED_BRAIN_WORKLOAD_PROFILES[workload];
    if (profile.maxTokens < MACHINE_JSON_HIGH_REASONING_FLOOR) {
      starved.push(`${workload} (${profile.maxTokens} token)`);
    }
  }
  assert.deepEqual(
    starved,
    [],
    `high efor ile koşan bu iş yüklerinde görünür JSON'a yer kalmayabilir: ${starved.join(", ")}. ` +
      `Ya bütçeyi ${MACHINE_JSON_HIGH_REASONING_FLOOR} üstüne çıkar ya da eforu düşür.`,
  );
});

/**
 * `reasoningMode: "deep"` HERHANGİ bir iş yükünü high efora çıkarabilir —
 * iş yükü tablosundaki eforu yener. O yolda bütçe taraması yapılamaz, çünkü
 * karar tur içinde veriliyor. Sağlayıcı isteği bu yüzden kendi tabanını
 * uygular; bu test o savunmanın yerinde durduğunu doğrular.
 */
test("a deep-mode turn on a small budget is still capped at request time", () => {
  for (const workload of sharedBrainWorkloadValues) {
    assert.equal(
      resolveReasoningEffort(workload, "deep"),
      "high",
      `deep mode her iş yükünü high'a çıkarmalı: ${workload}`,
    );
  }
});
