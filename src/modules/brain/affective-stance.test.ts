import { strict as assert } from "node:assert";
import { test } from "node:test";
import { deriveAffectiveStance, mergeDialogueState } from "./dialogue-state.js";
import { resolveGenerationTemperature } from "./generation-policy.js";

function stateWithMoods(
  moods: Array<{ mood: string; energy?: "low" | "mid" | "high" }>,
  turnCount: number,
) {
  // newest-first, matching how mergeDialogueState prepends
  const now = Date.now();
  return {
    moodTrend: moods.map((m, i) => ({
      mood: m.mood,
      energy: m.energy ?? "mid",
      at: new Date(now - i * 1000).toISOString(),
    })),
    conversationDynamics: {
      turnCount,
      averageReplyChars: 100,
      recentOpeners: [],
      recentClosers: [],
    },
    userRegister: "casual",
  } as unknown as Parameters<typeof deriveAffectiveStance>[0];
}

test("dominant recent mood wins with recency weight", () => {
  const stance = deriveAffectiveStance(
    stateWithMoods(
      [{ mood: "çok sinirli ve gergin" }, { mood: "mutlu" }, { mood: "mutlu" }],
      6,
    ),
  );
  assert.ok(stance);
  assert.equal(stance.mood, "frustrated");
});

test("rapport grows with sustained turns and warms temperature", () => {
  const early = deriveAffectiveStance(stateWithMoods([{ mood: "mutlu" }], 1));
  const deep = deriveAffectiveStance(stateWithMoods([{ mood: "mutlu" }], 24));
  assert.ok(early && deep);
  assert.ok(deep.rapport > early.rapport);

  const warm = resolveGenerationTemperature({
    workload: "mobile_chat_fast",
    prompt: "bugün nasıl gidiyor",
    affect: { mood: "positive", rapport: deep.rapport, volatility: 0 },
  });
  const base = resolveGenerationTemperature({
    workload: "mobile_chat_fast",
    prompt: "bugün nasıl gidiyor",
  });
  assert.ok(warm > base, `warm ${warm} should exceed base ${base}`);
});

test("user-level interaction depth carries rapport into a fresh session", () => {
  // Fresh session (turnCount 1) but a returning user with lifetime depth.
  const newUser = deriveAffectiveStance(stateWithMoods([{ mood: "mutlu" }], 1), {
    userInteractionCount: 0,
  });
  const returning = deriveAffectiveStance(
    stateWithMoods([{ mood: "mutlu" }], 1),
    { userInteractionCount: 60 },
  );
  assert.ok(newUser && returning);
  assert.ok(
    returning.rapport > newUser.rapport,
    `returning ${returning.rapport} should exceed new ${newUser.rapport}`,
  );
  // 60 lifetime turns should already read as an established relationship.
  assert.ok(returning.rapport >= 0.55);
});

test("distress steadies temperature below the conversational base", () => {
  const steady = resolveGenerationTemperature({
    workload: "mobile_chat_fast",
    prompt: "bir şey soracağım",
    affect: { mood: "frustrated", rapport: 0.2, volatility: 0.8 },
  });
  const base = resolveGenerationTemperature({
    workload: "mobile_chat_fast",
    prompt: "bir şey soracağım",
  });
  assert.ok(steady < base, `steady ${steady} should be below base ${base}`);
});

test("analytical turns ignore affect (stay precise)", () => {
  const t = resolveGenerationTemperature({
    workload: "planning",
    prompt: "planla",
    affect: { mood: "positive", rapport: 0.9, volatility: 0 },
  });
  assert.equal(t, 0.25);
});

test("fresh moodless session with no register yields no stance", () => {
  const stance = deriveAffectiveStance({
    moodTrend: [],
    conversationDynamics: {
      turnCount: 0,
      averageReplyChars: 0,
      recentOpeners: [],
      recentClosers: [],
    },
  } as unknown as Parameters<typeof deriveAffectiveStance>[0]);
  assert.equal(stance, null);
});

test("stance rides on real merged state (integration)", () => {
  let state = mergeDialogueState({
    userMessage: "bu hata beni çıldırtıyor, hiç çalışmıyor",
    assistantText: "anladım, birlikte çözelim",
    envelope: {
      reply: { text: "", lang: "tr", tone: "warm" },
      blocks: [],
      memory_ops: [],
      goal_ops: [],
      follow_ups: [],
      tool_requests: [],
      affect: { user_mood_guess: "sinirli ve bunalmış", energy: "high", register: "casual" },
    } as unknown as Parameters<typeof mergeDialogueState>[0]["envelope"],
  });
  const stance = deriveAffectiveStance(state);
  assert.ok(stance);
  assert.equal(stance.mood, "frustrated");
  assert.ok(stance.directive.includes("gergin") || stance.directive.includes("çöz"));
});
