export type InformationNeed = {
  contract: "elyan.information_need.v1";
  field: string;
  impact: "result" | "target" | "permission" | "irreversible_action";
  candidates: string[];
  safeDefaultAvailable: boolean;
  goalId: string | null;
  stepId: string | null;
  informationGain: number;
  urgency: "now" | "before_execution";
  question: string;
};

const genericQuestion = /^(?:netleştireyim|biraz daha bilgi|ek bilgi|ne yapmak istiyorsun|tam olarak neyi|detay verir misin)/i;

function classifyField(question: string): Pick<InformationNeed, "field" | "impact" | "informationGain"> {
  const folded = question.toLocaleLowerCase("tr-TR");
  if (/(izin|onay|erişim|paylaş|gönder)/.test(folded)) {
    return { field: "permission_scope", impact: "permission", informationGain: 1 };
  }
  if (/(sil|üzerine yaz|değiştir|iptal|kapat)/.test(folded)) {
    return { field: "irreversible_action", impact: "irreversible_action", informationGain: 0.98 };
  }
  if (/(hangi dosya|hangi klasör|nereye|konum|hedef)/.test(folded)) {
    return { field: "target", impact: "target", informationGain: 0.94 };
  }
  if (/(tarih|aralık|format|biçim|hangisi|mevcut .* mi|yeni .* mi)/.test(folded)) {
    return { field: "output_constraint", impact: "result", informationGain: 0.88 };
  }
  return { field: "execution_detail", impact: "result", informationGain: 0.65 };
}

function normalizeQuestion(value: string): string | null {
  const question = value.trim().replace(/\s+/g, " ").replace(/[.!]+$/u, "");
  if (!question || question.length > 240 || genericQuestion.test(question)) return null;
  return question.endsWith("?") ? question : `${question}?`;
}

export function selectInformationNeed(input: {
  questions: readonly string[];
  knownContext?: readonly string[];
  goalId?: string | null;
  stepId?: string | null;
}): InformationNeed | null {
  const known = new Set((input.knownContext ?? []).map((item) => item.trim().toLocaleLowerCase("tr-TR")));
  const needs = input.questions.flatMap((raw) => {
    const question = normalizeQuestion(raw);
    if (!question || known.has(question.toLocaleLowerCase("tr-TR"))) return [];
    const classification = classifyField(question);
    return [{
      contract: "elyan.information_need.v1" as const,
      ...classification,
      candidates: [],
      safeDefaultAvailable: false,
      goalId: input.goalId ?? null,
      stepId: input.stepId ?? null,
      urgency: classification.impact === "result" ? "before_execution" as const : "now" as const,
      question,
    }];
  });
  return needs.sort((a, b) => b.informationGain - a.informationGain)[0] ?? null;
}
