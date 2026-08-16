export const CHAT_CONTEXT_REGRESSION_FIXTURE = [
  {
    id: "greeting",
    prompt: "Selam Elyan, bugün nasılsın? Kısaca kendinden bahseder misin?",
    expectedTurnKind: "new_request",
    expectedWorkload: "mobile_chat_fast",
  },
  {
    id: "fatigue-advice",
    prompt: "Bugün çok yorgunum, kısa ve uygulanabilir bir öneri verir misin?",
    expectedTurnKind: "new_request",
    expectedWorkload: "mobile_chat_balanced",
  },
  {
    id: "context-follow-up",
    prompt: "Önceki konuşmamıza göre ihtiyacımı özetleyip bir takip sorusu sorar mısın?",
    expectedTurnKind: "follow_up",
    expectedWorkload: "mobile_chat_fast",
  },
  {
    id: "deep-chat",
    prompt: "Bu konuşmadaki ihtiyaçlarımı üç olasılık halinde ayırıp analiz et; derin düşün ve sonunda tek bir öneri ver.",
    expectedTurnKind: "new_request",
    expectedWorkload: "mobile_chat_deep_refine",
    expectedOutputContract: "chat_reply",
  },
  {
    id: "correction",
    prompt: "Az önceki cevap ilgisizdi, düzelt; aynı belge/kaynak cevabını tekrarlama.",
    expectedTurnKind: "correction",
    expectedWorkload: "mobile_chat_balanced",
  },
] as const;

export type ChatRegressionMeasurement = {
  fixtureId: string;
  acceptedMs: number | null;
  firstDeltaMs: number | null;
  totalMs: number | null;
  route: string | null;
  workload: string | null;
  model: string | null;
  reasoningEffort: string | null;
  turnKind: string | null;
  historyDigest: string | null;
  blockTypes: string[];
  semanticGateResult: string | null;
  fallbackReason: string | null;
  taskAssistantMatch: boolean | null;
};
