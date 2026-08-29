import assert from "node:assert/strict";
import test from "node:test";
import { classifyIntent } from "./intent-classifier.js";
import {
  buildSemanticContract,
  finalizeSemanticContractForRoute,
} from "./intent-semantic.js";
import { compileOutputContract } from "./output-contract.js";

function contractFor(message: string) {
  const classification = classifyIntent({
    userId: "user-1",
    message,
    routeContext: "command_route",
    source: "mobile",
  });
  return buildSemanticContract({
    classification,
    outputContract: compileOutputContract({ message }),
  });
}

test("semantic contract represents an ordinary answer without artifact or local context", () => {
  const contract = contractFor("Fotosentez nasıl çalışır");

  assert.deepEqual(contract, {
    schemaVersion: "elyan.semantic_contract.v1",
    conversationMode: "chat",
    surface: "server_brain",
    intent: "answer",
    artifact: "none",
    requiredContext: ["none"],
    sideEffect: "none",
    privacyClass: "public",
    requiredCapabilities: [],
    needsApproval: false,
    confidence: 0.55,
    ambiguity: 0.02,
    evidence: [
      "classifier:no_rule_match",
      "classifier_intent:chat",
      "reasoning:fast",
      "intent:answer",
      "artifact:none",
      "context:none",
      "operation:answer",
      "reference:current_prompt",
    ],
  });
});

test("semantic contract preserves explicit document creation as an artifact request", () => {
  const contract = contractFor("Kedilerin tarihini araştırıp PDF olarak ver");

  assert.equal(contract.conversationMode, "chat");
  assert.equal(contract.surface, "server_brain");
  assert.equal(contract.intent, "create");
  assert.equal(contract.artifact, "document");
  assert.deepEqual(contract.requiredContext, ["none"]);
  assert.equal(contract.requiredCapabilities.includes("document.write"), true);
  assert.equal(contract.requiredCapabilities.includes("web_research"), true);
  assert.equal(contract.sideEffect, "none");
});

test("fresh public evidence makes web research a typed capability independent of lexical intent", () => {
  const message = "Merhaba bugünün haberleri nedir Türkiye'deki?";
  const contract = buildSemanticContract({
    classification: classifyIntent({
      userId: "user-1",
      message,
      routeContext: "command_route",
      source: "mobile",
    }),
    outputContract: compileOutputContract({ message }),
    additionalEvidence: ["fresh_public_research"],
  });

  assert.equal(contract.surface, "server_brain");
  assert.equal(contract.requiredCapabilities.includes("web_research"), true);
});

test("route finalization changes only trusted runtime fields and keeps the contract typed", () => {
  const contract = contractFor("Masaüstümdeki raporu aç");
  const finalized = finalizeSemanticContractForRoute({
    contract,
    route: "desktop_runtime",
    requiresApproval: false,
    capabilities: ["document.read"],
    reason: "desktop_runtime_required",
  });

  assert.equal(finalized.surface, "desktop_runtime");
  assert.equal(finalized.conversationMode, "execute");
  assert.equal(finalized.requiredCapabilities.includes("document.read"), true);
  assert.equal(finalized.evidence.includes("route:desktop_runtime"), true);
  assert.equal(
    finalized.evidence.includes("route_reason:desktop_runtime"),
    true,
  );
  assert.equal(finalized.intent, "automate");
});
