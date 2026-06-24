import assert from "node:assert/strict";
import test from "node:test";
import {
  calculateBillablePlanTokens,
  resolveAdaptiveInferenceBudget,
  resolveTokenBudgetState,
} from "./token-metering.js";

test("calculateBillablePlanTokens keeps short chat from charging fixed prompt overhead", () => {
  const usage = calculateBillablePlanTokens({
    surface: "chat",
    workload: "mobile_chat_fast",
    userInputTokens: 2,
    promptTokens: 1_157,
    completionTokens: 18,
  });

  assert.equal(usage.billableTokens, 1);
  assert.equal(usage.depth, "short");
  assert.equal(usage.components.promptContextTokens, 1_155);
});

test("calculateBillablePlanTokens scales with message depth and answer length", () => {
  const shallow = calculateBillablePlanTokens({
    surface: "chat",
    workload: "mobile_chat_fast",
    userInputTokens: 80,
    promptTokens: 1_100,
    completionTokens: 120,
  });
  const deep = calculateBillablePlanTokens({
    surface: "chat",
    workload: "planning",
    userInputTokens: 2_200,
    promptTokens: 4_000,
    completionTokens: 900,
  });

  assert.equal(shallow.billableTokens, 1);
  assert.equal(deep.depth, "planning");
  assert.equal(deep.billableTokens > shallow.billableTokens, true);
});

test("calculateBillablePlanTokens charges server tasks more than chat for the same workload", () => {
  const chat = calculateBillablePlanTokens({
    surface: "chat",
    workload: "planning",
    userInputTokens: 2_200,
    promptTokens: 4_000,
    completionTokens: 900,
  });
  const task = calculateBillablePlanTokens({
    surface: "task",
    workload: "planning",
    userInputTokens: 2_200,
    promptTokens: 4_000,
    completionTokens: 900,
  });

  assert.equal(task.billableTokens > chat.billableTokens, true);
  assert.equal(task.surface, "task");
});

test("resolveAdaptiveInferenceBudget expands explicit long-form requests without changing normal chat", () => {
  const normal = resolveAdaptiveInferenceBudget({
    workload: "mobile_chat_balanced",
    prompt: "Bunu açıklar mısın?",
    baseMaxTokens: 384,
    premium: false,
    remainingCredits: 400,
    grantedCredits: 600,
  });
  const longForm = resolveAdaptiveInferenceBudget({
    workload: "mobile_chat_balanced",
    prompt: "Bunu kapsamlı ve detaylı bir rapor olarak yaz, yarım bırakma.",
    baseMaxTokens: 384,
    premium: true,
    remainingCredits: 1_500,
    grantedCredits: 2_000,
  });

  assert.equal(normal.maxCompletionTokens, 384);
  assert.equal(normal.requestedLongForm, false);
  assert.equal(normal.budgetReason, "standard");
  assert.equal(normal.qualityEscalated, false);
  assert.equal(longForm.maxCompletionTokens, 1_152);
  assert.equal(longForm.requestedLongForm, true);
  assert.equal(longForm.budgetReason, "long_form_expanded");
  assert.equal(longForm.conversationTokenBudget, 4_200);
});

test("resolveAdaptiveInferenceBudget honors additive long-form hints from mobile metadata", () => {
  const hinted = resolveAdaptiveInferenceBudget({
    workload: "mobile_chat_balanced",
    prompt: "Bunu aciklar misin?",
    requestedLongFormHint: true,
    baseMaxTokens: 384,
    premium: true,
    remainingCredits: 1_500,
    grantedCredits: 2_000,
  });

  assert.equal(hinted.requestedLongForm, true);
  assert.equal(hinted.budgetReason, "long_form_expanded");
  assert.equal(hinted.maxCompletionTokens, 1_152);
});

test("resolveAdaptiveInferenceBudget keeps free plan tighter than solo and pro", () => {
  const free = resolveAdaptiveInferenceBudget({
    workload: "mobile_chat_balanced",
    prompt: "Bunu kapsamlı ve detaylı bir rapor olarak yaz, yarım bırakma.",
    baseMaxTokens: 384,
    premium: false,
    planCode: "free",
    remainingCredits: 100,
    grantedCredits: 120,
  });
  const solo = resolveAdaptiveInferenceBudget({
    workload: "mobile_chat_balanced",
    prompt: "Bunu kapsamlı ve detaylı bir rapor olarak yaz, yarım bırakma.",
    baseMaxTokens: 384,
    premium: false,
    planCode: "solo",
    remainingCredits: 500,
    grantedCredits: 600,
  });
  const pro = resolveAdaptiveInferenceBudget({
    workload: "mobile_chat_balanced",
    prompt: "Bunu kapsamlı ve detaylı bir rapor olarak yaz, yarım bırakma.",
    baseMaxTokens: 384,
    premium: true,
    planCode: "pro",
    remainingCredits: 1_500,
    grantedCredits: 2_000,
  });

  assert.equal(free.maxCompletionTokens, 480);
  assert.equal(free.conversationTokenBudget, 1_400);
  assert.equal(free.conversationMessageBudget, 6);
  assert.equal(solo.maxCompletionTokens, 1_152);
  assert.equal(solo.conversationTokenBudget, 3_200);
  assert.equal(solo.conversationMessageBudget, 12);
  assert.equal(pro.maxCompletionTokens, 1_152);
  assert.equal(pro.conversationTokenBudget, 4_200);
  assert.equal(pro.conversationMessageBudget, 14);
});

test("resolveAdaptiveInferenceBudget conserves free plan context as credits run low", () => {
  const budget = resolveAdaptiveInferenceBudget({
    workload: "planning",
    prompt: "Çok uzun ve ayrıntılı bir rapor yaz.",
    baseMaxTokens: 560,
    premium: false,
    planCode: "free",
    remainingCredits: 2,
    grantedCredits: 120,
  });

  assert.equal(budget.budgetState, "critical");
  assert.equal(budget.maxCompletionTokens, 180);
  assert.equal(budget.budgetReason, "low_balance_critical");
  assert.equal(budget.conversationTokenBudget, 650);
  assert.equal(budget.conversationMessageBudget, 6);
});

test("resolveAdaptiveInferenceBudget keeps low balances useful without allowing long-form expansion", () => {
  const budget = resolveAdaptiveInferenceBudget({
    workload: "planning",
    prompt: "Çok uzun ve ayrıntılı bir rapor yaz.",
    baseMaxTokens: 560,
    premium: true,
    remainingCredits: 2,
    grantedCredits: 2_000,
  });

  assert.equal(resolveTokenBudgetState({ remaining: 2, granted: 2_000 }), "critical");
  assert.equal(budget.budgetState, "critical");
  assert.equal(budget.maxCompletionTokens, 320);
  assert.equal(budget.budgetReason, "low_balance_critical");
  assert.equal(budget.conversationTokenBudget, 1_000);
});

test("resolveAdaptiveInferenceBudget gives conserve state a bounded useful answer", () => {
  const budget = resolveAdaptiveInferenceBudget({
    workload: "mobile_chat_balanced",
    prompt: "Bunu kapsamlı ve detaylı açıkla.",
    baseMaxTokens: 384,
    premium: false,
    planCode: "solo",
    remainingCredits: 50,
    grantedCredits: 600,
  });

  assert.equal(budget.budgetState, "conserve");
  assert.equal(budget.budgetReason, "low_balance_conserve");
  assert.equal(budget.maxCompletionTokens, 520);
  assert.equal(budget.conversationTokenBudget, 1_800);
});

test("resolveAdaptiveInferenceBudget treats document analysis as its own long-form workload", () => {
  const budget = resolveAdaptiveInferenceBudget({
    workload: "document_analysis",
    prompt: "Bu belgeyi kapsamlı ve detaylı analiz et, yarım bırakma.",
    baseMaxTokens: 640,
    premium: true,
    planCode: "pro",
    remainingCredits: 1_200,
    grantedCredits: 2_000,
  });

  assert.equal(budget.requestedLongForm, true);
  assert.equal(budget.maxCompletionTokens, 1_920);
  assert.equal(budget.conversationTokenBudget, 4_200);
});

test("resolveAdaptiveInferenceBudget escalates normal mobile chat quality when the prompt is nontrivial", () => {
  const budget = resolveAdaptiveInferenceBudget({
    workload: "mobile_chat_fast",
    prompt: "Bu cevabı daha akıllı ve net olacak şekilde nedenleriyle açıkla.",
    baseMaxTokens: 224,
    premium: false,
    remainingCredits: 400,
    grantedCredits: 600,
  });

  assert.equal(budget.requestedLongForm, false);
  assert.equal(budget.qualityEscalated, true);
  assert.equal(budget.budgetReason, "quality_escalated");
  assert.equal(budget.maxCompletionTokens, 403);
  assert.equal(budget.conversationTokenBudget, 2_100);
});

test("resolveAdaptiveInferenceBudget escalates health and reasoning prompts without long-form mode", () => {
  const budget = resolveAdaptiveInferenceBudget({
    workload: "mobile_chat_balanced",
    prompt: "Sağlık verilerimi mantık yürüterek değerlendir ama kısa ve tam yaz.",
    baseMaxTokens: 384,
    premium: false,
    planCode: "solo",
    remainingCredits: 500,
    grantedCredits: 600,
  });

  assert.equal(budget.requestedLongForm, false);
  assert.equal(budget.qualityEscalated, true);
  assert.equal(budget.budgetReason, "quality_escalated");
  assert.equal(budget.maxCompletionTokens, 595);
});
