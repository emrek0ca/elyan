import type { IntentClassification } from "../../core/understanding/types.js";
import type { CommandRouteDecision } from "../routing-policy/service.js";
import {
  buildDesktopWorkOrder,
  type DesktopWorkOrder,
  type DesktopWorkOrderStep,
} from "./desktop-work-order.js";
import {
  buildAllowedCapabilities,
  validateMaterializedPlanAgainstWorkOrder,
} from "./materialize-plan.js";

/**
 * Uçtan uca replay koşumu.
 *
 * NEDEN
 * -----
 * Şu ana kadarki kapılar zincirin TEK bir halkasını ölçüyordu: routing eval
 * yalnız yetenek seçimini, `dispatch-quality-matrix` yalnız iş emri
 * kurulumunu. Aradaki geçişler ölçüsüzdü ve canlı arızalar tam orada çıktı.
 *
 * Somut kanıt: "Chrome u kapat" (task 6a7ef5fb). Router isteği `app_control`
 * sandı → iş emri `desktop_operator.run`ı ŞART yazdı → planlayıcı doğru planı
 * kurdu (`close_app`) → doğrulayıcı planı reddetti → kullanıcı iki kez üst
 * üste "güvenilir yürütme planı hazırlanamadı" gördü. Hiçbir birim testi
 * kırılmadı, çünkü hiçbiri bu ZİNCİRİ koşmuyordu.
 *
 * NE YAPAR
 * --------
 * Gerçek `buildDesktopWorkOrder` → gerçek `buildAllowedCapabilities` →
 * gerçek `validateMaterializedPlanAgainstWorkOrder`. Sahte olan tek şey
 * masaüstü yürütmesi: planı model üretmez, vaka onu verir. Böylece
 * "doğru plan bu zincirden geçebiliyor mu?" sorusu model çağırmadan,
 * deterministik ve saniyeler içinde yanıtlanır.
 */

export type ReplayCase = {
  name: string;
  utterance: string;
  /** Router'ın o turda ürettiği yetenek tahmini — yanlış olabilir, olay bu. */
  routerCapabilities: string[];
  primaryIntent?: IntentClassification["primaryIntent"];
  /** Doğru planlayıcının üretmesi beklenen adımlar. */
  plan: DesktopWorkOrderStep[];
  /** Bu planın zincirden geçmesi mi bekleniyor, takılması mı. */
  expect: "accepted" | "rejected";
  /** `rejected` vakalarında hata metninde aranan iz. */
  expectedIssuePattern?: RegExp;
  note?: string;
};

export type ReplayOutcome = {
  name: string;
  passed: boolean;
  issues: string[];
  allowedCapabilities: string[];
  detail: string;
};

function replayIntent(
  primaryIntent: IntentClassification["primaryIntent"],
): IntentClassification {
  return {
    primaryIntent,
    secondaryIntents: [],
    requiresLocalRuntime: true,
    requiresRetrieval: false,
    requiresToolUse: true,
    requiresCitation: false,
    requiresLongRunningTask: true,
    privacyRisk: "low",
    confidence: 0.86,
    reason: "loop_replay",
    taskFrame: {
      goal: "loop replay",
      likelyAnswerShape: "structured",
      reasoningMode: "balanced",
      shouldClarify: false,
    },
    ecosystemHints: [],
    routingHints: {
      mode: "task",
      preferredCapabilities: [],
      avoidCloud: false,
      requiresLocalRuntime: true,
    },
  };
}

function replayRoute(capabilities: string[]): CommandRouteDecision {
  return {
    route: "desktop_runtime",
    mode: "executable_task",
    capabilities,
    privacyClass: "public_text",
    requiresApproval: false,
    reason: "loop_replay",
    intent: "desktop_cowork",
    confidence: 0.88,
    requiredRuntime: "desktop",
    privacyLevel: "medium",
    shouldAskClarification: false,
    failClosedReason: "desktop_runtime_selected_target",
    selectedWorkload: "desktop_handoff",
    taskRoute: {
      target: "desktop_runtime",
      operationalRoute: "desktop_runtime",
      executionPlan: ["desktop_runtime"],
      reason: "loop_replay",
      needsDesktop: true,
      needsPrivateDesktopData: false,
      needsUserApproval: false,
      requiredCapabilities: capabilities,
    },
  } as CommandRouteDecision;
}

export function buildReplayWorkOrder(testCase: ReplayCase): DesktopWorkOrder {
  return buildDesktopWorkOrder({
    message: testCase.utterance,
    title: testCase.name,
    routeDecision: replayRoute(testCase.routerCapabilities),
    requestedCapabilities: testCase.routerCapabilities,
    source: "mobile_chat_dispatch",
  }) as DesktopWorkOrder;
}

/** Tek vakayı zincirden geçirir. Model çağrısı yok. */
export function replayCase(testCase: ReplayCase): ReplayOutcome {
  const workOrder = buildReplayWorkOrder(testCase);
  const allowedCapabilities = buildAllowedCapabilities(workOrder);
  const issues = validateMaterializedPlanAgainstWorkOrder(
    testCase.plan,
    workOrder,
  );

  if (testCase.expect === "accepted") {
    return {
      name: testCase.name,
      passed: issues.length === 0,
      issues,
      allowedCapabilities,
      detail:
        issues.length === 0
          ? "plan zincirden geçti"
          : `doğru plan reddedildi: ${issues.join(" | ")}`,
    };
  }

  const matched =
    issues.length > 0 &&
    (!testCase.expectedIssuePattern ||
      testCase.expectedIssuePattern.test(issues.join("\n")));
  return {
    name: testCase.name,
    passed: matched,
    issues,
    allowedCapabilities,
    detail: matched
      ? "beklenen şekilde reddedildi"
      : issues.length === 0
        ? "reddedilmesi gereken plan geçti"
        : `farklı sebeple reddedildi: ${issues.join(" | ")}`,
  };
}

export function replayAll(cases: ReplayCase[]): ReplayOutcome[] {
  return cases.map(replayCase);
}

export function formatReplayReport(outcomes: ReplayOutcome[]): string {
  const failed = outcomes.filter((outcome) => !outcome.passed);
  const lines = [
    `replay ${outcomes.length - failed.length}/${outcomes.length} geçti`,
  ];
  for (const outcome of failed) {
    lines.push(`  ✗ ${outcome.name}: ${outcome.detail}`);
  }
  return lines.join("\n");
}
