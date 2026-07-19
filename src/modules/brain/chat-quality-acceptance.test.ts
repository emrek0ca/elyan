import assert from "node:assert/strict";
import test from "node:test";
import {
  buildTypedUnderstandingEnvelope,
  preferredWorkloadFromUnderstandingEnvelope,
} from "../../core/understanding/understanding-envelope.js";
import { isExplicitTableRequest } from "../../core/understanding/structured-output-policy.js";
import type { IntentClassification } from "../../core/understanding/types.js";
import { classifyElyanTurnIntent } from "./response-policy.js";
import { shouldAcceptExtractedTypedBlock } from "./typed-block-policy.js";
import { classifyWebGroundingDecision } from "./web-grounding.js";

function chatIntent(): IntentClassification {
  return {
    primaryIntent: "chat",
    secondaryIntents: [],
    requiresLocalRuntime: false,
    requiresRetrieval: false,
    requiresToolUse: false,
    requiresCitation: false,
    requiresLongRunningTask: false,
    privacyRisk: "low",
    confidence: 0.9,
    reason: "quality_acceptance",
    taskFrame: {
      goal: "answer",
      likelyAnswerShape: "direct answer",
      reasoningMode: "balanced",
      shouldClarify: false,
    },
    ecosystemHints: [],
    routingHints: {
      mode: "fast",
      preferredCapabilities: [],
      avoidCloud: false,
      requiresLocalRuntime: false,
    },
  };
}

const cases = [
  {
    name: "live backoff regression remains prose",
    prompt:
      "Exponential backoff’u iki maddede açıkla. Süreler 1, 2 ve 4 saniye olsun, jitter ekle. Tablo kullanma.",
    table: false,
    web: "no_web_needed",
  },
  {
    name: "live multiplication regression remains offline math",
    prompt: "Yalnızca sonucu yaz: 12 × 14 kaçtır?",
    table: false,
    web: "no_web_needed",
    intent: "math",
  },
  {
    name: "sadece instruction is not a named entity",
    prompt: "Sadece sonucu söyle: 9 + 7",
    table: false,
    web: "no_web_needed",
    intent: "math",
  },
  {
    name: "explicit Turkish table request is accepted",
    prompt: "A: 1 ve B: 2 verilerini tablo olarak göster.",
    table: true,
    workload: "table_generate",
  },
  {
    name: "explicit Excel request is accepted",
    prompt: "Kalem ve tutar kolonlarıyla Excel tablo oluştur.",
    table: true,
    workload: "table_generate",
  },
  {
    name: "table negation before prose request wins",
    prompt: "Tablo yapma; sonucu üç maddeyle açıkla.",
    table: false,
    web: "no_web_needed",
  },
  {
    name: "English table negation wins",
    prompt: "No table; explain exponential backoff in two bullets.",
    table: false,
    web: "no_web_needed",
  },
  {
    name: "short greeting stays offline",
    prompt: "Selam, nasılsın?",
    table: false,
    web: "no_web_needed",
  },
  {
    name: "self-contained coding explanation stays offline",
    prompt: "Bu Python kodundaki TypeError hatasını açıkla.",
    table: false,
    web: "no_web_needed",
  },
  {
    name: "self-contained equation stays offline",
    prompt: "2x + 4 = 10 denkleminde x kaçtır?",
    table: false,
    web: "no_web_needed",
    intent: "math",
  },
  {
    name: "current currency requires web",
    prompt: "Bugünkü dolar kuru kaç TL?",
    table: false,
    web: "web_required",
  },
  {
    name: "latest framework release requires web",
    prompt: "Flutter son sürümde breaking change var mı?",
    table: false,
    web: "web_required",
  },
  {
    name: "explicit source request requires web",
    prompt: "2026 yapay zeka pazarını güncel kaynaklarla araştır.",
    table: false,
    web: "web_required",
  },
  {
    name: "non-current conceptual comparison is optional web",
    prompt: "Yapay zeka eğitim yaklaşımlarını karşılaştır.",
    table: false,
    web: "web_optional",
  },
] as const;

test("chat quality acceptance set keeps output and web routing aligned", () => {
  assert.ok(cases.length >= 12);

  for (const qualityCase of cases) {
    const envelope = buildTypedUnderstandingEnvelope({
      userId: "quality_user",
      message: qualityCase.prompt,
      intent: chatIntent(),
    });
    const workload = preferredWorkloadFromUnderstandingEnvelope(
      envelope,
      qualityCase.prompt,
    );
    const explicitTable = isExplicitTableRequest(qualityCase.prompt);
    const tableAccepted = shouldAcceptExtractedTypedBlock({
      block: { type: "table" },
      prompt: qualityCase.prompt,
      selectedWorkload: workload ?? "mobile_chat_fast",
    });

    assert.equal(explicitTable, qualityCase.table, qualityCase.name);
    assert.equal(
      envelope.desired_outputs.some((output) => output.kind === "table"),
      qualityCase.table,
      qualityCase.name,
    );
    assert.equal(tableAccepted, qualityCase.table, qualityCase.name);

    if ("workload" in qualityCase) {
      assert.equal(workload, qualityCase.workload, qualityCase.name);
    } else {
      assert.notEqual(workload, "table_generate", qualityCase.name);
    }
    if ("web" in qualityCase) {
      assert.equal(
        classifyWebGroundingDecision({
          prompt: qualityCase.prompt,
          workload: workload ?? "mobile_chat_fast",
        }).mode,
        qualityCase.web,
        qualityCase.name,
      );
    }
    if ("intent" in qualityCase) {
      assert.equal(
        classifyElyanTurnIntent(qualityCase.prompt),
        qualityCase.intent,
        qualityCase.name,
      );
    }
  }
});
