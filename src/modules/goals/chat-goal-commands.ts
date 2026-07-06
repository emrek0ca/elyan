import type { FastifyInstance } from "fastify";
import type { ActiveGoalContext } from "./service.js";
import { advanceGoal, createGoal, getActiveGoalForContext } from "./service.js";

type TurnGoalOp = {
  op: "advance" | "complete" | "block" | "open";
  goalId?: string;
  step?: string;
  next?: string;
};

/**
 * Sohbetten deterministik hedef komutu algılama.
 *
 * Neden model değil de regex: hedef oluşturma kullanıcıya "çalıştı/çalışmadı"
 * olarak görünen bir yan etki. Modelin turn-envelope tool çağrısına bırakılırsa
 * flag'e, modele ve parse başarısına bağımlı olur — üç kırılma noktası.
 * Deterministik yol her mesajda mikrosaniyede çalışır, model yolunu da
 * dışlamaz (envelope açıkken goal_ops yine işler).
 *
 * Pattern'ler bilinçli olarak dar: "hedef" + emir kipi fiil bitişik olmalı.
 * "hedef kitle belirle" (pazarlama) eşleşmez çünkü araya "kitle" girer.
 */
export type GoalChatCommand =
  | { kind: "create"; title: string; maxSteps: number | null }
  | { kind: "complete" };

const CREATE_PATTERNS: RegExp[] = [
  // "... hedefi oluştur/ekle/koy/belirle/aç", "hedef oluştur: ..."
  /(?:^|\s)hedef(?:i|im)?\s*(?:oluştur|olustur|ekle|koy|belirle|aç|ac)\b/iu,
  // "bana ... için (bir) hedef oluştur"
  /\bhedef\s+(?:oluşturur|olusturur|ekler|koyar)\s*m[ıi]s[ıi]n\b/iu,
  // "hedefim ... olsun"
  /\bhedefim\s+.{3,120}\s+olsun\b/iu,
  /\b(?:create|set|add|open)\s+(?:a\s+)?(?:new\s+)?goal\b/i,
];

const COMPLETE_PATTERNS: RegExp[] = [
  /\bhedef(?:i|imi)?\s*(?:tamamla|tamamland[ıi]|bitir|bitti|kapat)\b/iu,
  /\b(?:complete|finish|close)\s+(?:the\s+|my\s+)?goal\b/i,
];

// Başlık çıkarımında silinecek komut kalıpları.
const TITLE_STRIP =
  /(?:^|\s)(?:bana|benim|için|icin|bir|yeni|lütfen|lutfen)(?=\s|$)|(?:^|\s)hedef(?:i|im)?\s*(?:oluştur|olustur|ekle|koy|belirle|aç|ac)(?:ur|ar)?\s*m?[ıi]?s?[ıi]?n?\b|\bhedefim\b|\bolsun\b|\b(?:create|set|add|open)\s+(?:a\s+)?(?:new\s+)?goal\b|[:?!.]+$/giu;

const MAX_STEPS_PATTERN = /(\d{1,3})\s*(?:adım(?:l[ıi]k|da)?|step)/iu;

export function detectGoalChatCommand(message: string): GoalChatCommand | null {
  const text = String(message ?? "").trim();
  if (!text || text.length > 2_000) {
    return null;
  }
  // "hedef kitle", "hedef fiyat" gibi isim tamlamaları komut değil.
  if (/\bhedef\s+(?:kitle|fiyat|pazar|okur|müşteri|musteri)\b/iu.test(text)) {
    return null;
  }
  if (COMPLETE_PATTERNS.some((pattern) => pattern.test(text))) {
    return { kind: "complete" };
  }
  if (CREATE_PATTERNS.some((pattern) => pattern.test(text))) {
    const maxSteps = text.match(MAX_STEPS_PATTERN);
    const title = text
      .replace(MAX_STEPS_PATTERN, " ")
      .replace(TITLE_STRIP, " ")
      .replace(/\s+/g, " ")
      .trim();
    return {
      kind: "create",
      // Başlık çıkmazsa mesajın kendisi başlık olur — boş hedef asla.
      title: (title || text).slice(0, 200),
      maxSteps: maxSteps ? Math.max(1, Math.min(Number(maxSteps[1]), 100)) : null,
    };
  }
  return null;
}

export type GoalChatCommandResult = {
  goal: ActiveGoalContext;
  block: {
    type: "goal_progress";
    goalId: string;
    step: number;
    ofSteps: number;
    advancedTo: string;
    blocker: null;
    done: boolean;
  };
};

/**
 * Algılanan komutu goals servisine uygular ve mobilin zaten render ettiği
 * goal_progress bloğunu üretir. Hata durumunda null döner (fail-open) —
 * sohbet cevabı hedef yazımı başarısız diye asla bloklanmaz.
 */
export async function executeGoalChatCommand(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId?: string | null;
    taskId?: string | null;
    command: GoalChatCommand;
  },
): Promise<GoalChatCommandResult | null> {
  try {
    if (input.command.kind === "create") {
      const created = await createGoal(app, {
        userId: input.userId,
        sessionId: input.sessionId ?? undefined,
        taskId: input.taskId ?? undefined,
        title: input.command.title,
        maxSteps: input.command.maxSteps ?? undefined,
      });
      return {
        goal: created.goal,
        block: {
          type: "goal_progress",
          goalId: created.goal.id,
          step: 0,
          ofSteps: created.goal.maxSteps,
          advancedTo: `Hedef oluşturuldu: ${created.goal.title}`,
          blocker: null,
          done: false,
        },
      };
    }
    const active = await getActiveGoalForContext(app, {
      userId: input.userId,
      sessionId: input.sessionId ?? null,
    });
    if (!active) {
      return null;
    }
    const advanced = await advanceGoal(app, {
      userId: input.userId,
      goalId: active.id,
      step: active.maxSteps,
      ofSteps: active.maxSteps,
      advancedTo: "Hedef tamamlandı",
      done: true,
    });
    const goal = advanced?.goal ?? active;
    return {
      goal,
      block: {
        type: "goal_progress",
        goalId: goal.id,
        step: goal.maxSteps,
        ofSteps: goal.maxSteps,
        advancedTo: `Hedef tamamlandı: ${goal.title}`,
        blocker: null,
        done: true,
      },
    };
  } catch (error) {
    app.log.warn(
      {
        userId: input.userId,
        kind: input.command.kind,
        reason: error instanceof Error ? error.message : "unknown",
      },
      "goal chat command failed open",
    );
    return null;
  }
}

/**
 * Turn envelope'daki goal_ops'u goals servisine kalıcılaştırır. Envelope'daki
 * goalId model üretimi olduğu için güvenilmez — "open" dışındaki op'lar aktif
 * hedefe uygulanır; goalId ancak kullanıcının kendi hedefiyle eşleşirse
 * kullanılır (cross-user yazım imkânsız: tüm servis çağrıları userId scope'lu).
 */
export async function applyTurnGoalOps(
  app: FastifyInstance,
  input: {
    userId: string;
    taskId?: string | null;
    sessionId?: string | null;
    goalOps: TurnGoalOp[];
    userMessage: string;
  },
): Promise<void> {
  // Tur başına en fazla 1 open + 3 ilerleme — model taşkını DB'ye yansımasın.
  let opened = 0;
  let advancedCount = 0;
  for (const op of input.goalOps.slice(0, 8)) {
    try {
      if (op.op === "open") {
        if (opened >= 1) continue;
        opened += 1;
        await createGoal(app, {
          userId: input.userId,
          sessionId: input.sessionId ?? undefined,
          taskId: input.taskId ?? undefined,
          title: (op.step ?? op.next ?? input.userMessage).slice(0, 200),
        });
        continue;
      }
      if (advancedCount >= 3) continue;
      const active = await getActiveGoalForContext(app, {
        userId: input.userId,
        sessionId: input.sessionId ?? null,
      });
      const goalId =
        op.goalId && op.goalId === active?.id ? op.goalId : active?.id;
      if (!goalId || !active) continue;
      advancedCount += 1;
      if (op.op === "complete") {
        await advanceGoal(app, {
          userId: input.userId,
          goalId,
          step: active.maxSteps,
          ofSteps: active.maxSteps,
          advancedTo: op.step ?? op.next ?? "Hedef tamamlandı",
          done: true,
        });
      } else {
        await advanceGoal(app, {
          userId: input.userId,
          goalId,
          step: Math.min(active.currentStep + 1, active.maxSteps),
          ofSteps: active.maxSteps,
          advancedTo: op.step ?? op.next ?? "İlerleme kaydedildi",
          blocker: op.op === "block" ? op.next ?? op.step ?? "Engel bildirildi" : null,
          done: false,
        });
      }
    } catch {
      // Tek op hatası kalanları durdurmaz; sohbet cevabı hiç etkilenmez.
    }
  }
}
