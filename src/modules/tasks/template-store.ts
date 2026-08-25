/**
 * ŞABLON DEPOSU ve YAŞAM DÖNGÜSÜ.
 *
 * Sentez aday üretir; bu modül adayın nasıl olgunlaştığını yönetir:
 *
 *   candidate → shadow → canary → active
 *                  ↘        ↘        ↘
 *                     retired (yanlış yürütme / anlaşmazlık / manuel)
 *
 * HİÇBİR GEÇİŞ KENDİLİĞİNDEN "active" ÜRETMEZ. `active` yalnız açık bir yayın
 * çağrısıyla verilir — bu proje otomatik terfiye kapalıdır ve öyle kalmalıdır.
 * Gölge ve kanarya geçişleri ise ölçüme bağlıdır ve tek yönlüdür: bir kez
 * yanlış yürütme görülen şablon geri dönmez, emekli olur.
 */

import { and, eq, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { compiledTemplates } from "../../db/schema.js";
import {
  synthesizeCompiledTemplates,
  TEMPLATE_MIN_EPISODES,
  type CompiledTemplateCandidate,
  type CompiledTemplateStep,
} from "./template-synthesis.js";
import { listEpisodeDigestGroups } from "./episode-store.js";

export type CompiledTemplateState =
  | "candidate"
  | "shadow"
  | "canary"
  | "active"
  | "retired";

export type StoredCompiledTemplate = {
  templateId: string;
  intentFamily: string;
  contractDigest: string;
  steps: CompiledTemplateStep[];
  state: CompiledTemplateState;
  supportingEpisodes: number;
  consistency: number;
  shadowMatches: number;
  shadowAgreements: number;
  wrongExecutionCount: number;
};

/** Gölgeden kanaryaya geçiş için gereken en az eşleşme ve anlaşma oranı. */
export const TEMPLATE_SHADOW_MIN_MATCHES = 20;
export const TEMPLATE_SHADOW_MIN_AGREEMENT = 0.95;

/**
 * Adayları depoya yazar.
 *
 * Var olan bir şablonun DURUMU asla geri alınmaz: `shadow`'a geçmiş bir
 * şablon yeni sentez turunda tekrar `candidate` olmaz, yalnız destekleyici
 * sayıları tazelenir. Aksi hâlde her sentez turu olgunlaşmayı sıfırlardı.
 */
export async function upsertTemplateCandidates(
  app: FastifyInstance,
  input: { userId: string; candidates: CompiledTemplateCandidate[] },
): Promise<number> {
  if (input.candidates.length === 0) return 0;
  try {
    const rows = input.candidates.map((candidate) => ({
      templateId: candidate.templateId,
      userId: input.userId,
      intentFamily: candidate.intentFamily,
      contractDigest: candidate.contractDigest,
      steps: candidate.steps,
      state: "candidate" as const,
      supportingEpisodes: candidate.supportingEpisodes,
      fulfilledEpisodes: candidate.fulfilledEpisodes,
      consistency: candidate.consistency,
      evidenceKinds: candidate.evidenceKinds,
      medianLatencyMs: candidate.medianLatencyMs,
    }));
    await app.db
      .insert(compiledTemplates)
      .values(rows)
      .onConflictDoUpdate({
        target: [compiledTemplates.userId, compiledTemplates.templateId],
        set: {
          steps: sql`excluded.steps`,
          supportingEpisodes: sql`excluded.supporting_episodes`,
          fulfilledEpisodes: sql`excluded.fulfilled_episodes`,
          consistency: sql`excluded.consistency`,
          evidenceKinds: sql`excluded.evidence_kinds`,
          medianLatencyMs: sql`excluded.median_latency_ms`,
          updatedAt: new Date(),
        },
        // Emekli edilmiş şablon sentezle geri dirilmez.
        setWhere: sql`${compiledTemplates.state} <> 'retired'`,
      });
    return rows.length;
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "compiled template upsert failed",
    );
    return 0;
  }
}

export async function listTemplates(
  app: FastifyInstance,
  input: { userId: string; intentFamily?: string; states?: CompiledTemplateState[] },
): Promise<StoredCompiledTemplate[]> {
  try {
    const filters = [eq(compiledTemplates.userId, input.userId)];
    if (input.intentFamily) {
      filters.push(eq(compiledTemplates.intentFamily, input.intentFamily));
    }
    if (input.states && input.states.length > 0) {
      filters.push(
        sql`${compiledTemplates.state} in (${sql.join(
          input.states.map((state) => sql`${state}`),
          sql`, `,
        )})`,
      );
    }
    const rows = await app.db
      .select({
        templateId: compiledTemplates.templateId,
        intentFamily: compiledTemplates.intentFamily,
        contractDigest: compiledTemplates.contractDigest,
        steps: compiledTemplates.steps,
        state: compiledTemplates.state,
        supportingEpisodes: compiledTemplates.supportingEpisodes,
        consistency: compiledTemplates.consistency,
        shadowMatches: compiledTemplates.shadowMatches,
        shadowAgreements: compiledTemplates.shadowAgreements,
        wrongExecutionCount: compiledTemplates.wrongExecutionCount,
      })
      .from(compiledTemplates)
      .where(and(...filters))
      .limit(128);
    return rows.map((row) => ({
      templateId: row.templateId,
      intentFamily: row.intentFamily,
      contractDigest: row.contractDigest,
      steps: Array.isArray(row.steps) ? (row.steps as CompiledTemplateStep[]) : [],
      state: row.state as CompiledTemplateState,
      supportingEpisodes: row.supportingEpisodes,
      consistency: row.consistency,
      shadowMatches: row.shadowMatches,
      shadowAgreements: row.shadowAgreements,
      wrongExecutionCount: row.wrongExecutionCount,
    }));
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "compiled template listing failed",
    );
    return [];
  }
}

/**
 * Gölge gözlemini kaydeder.
 *
 * `agreed`, şablonun ürettiği adım imzasının o turda GERÇEKTEN yürütülen
 * imzayla aynı olup olmadığıdır. Anlaşmazlık bir hata değildir — şablonun
 * henüz kanonik olmadığının kanıtıdır ve terfiyi geciktirir.
 */
export async function recordTemplateShadowObservation(
  app: FastifyInstance,
  input: { userId: string; templateId: string; agreed: boolean },
): Promise<void> {
  try {
    await app.db
      .update(compiledTemplates)
      .set({
        shadowMatches: sql`${compiledTemplates.shadowMatches} + 1`,
        shadowAgreements: sql`${compiledTemplates.shadowAgreements} + ${input.agreed ? 1 : 0}`,
        updatedAt: new Date(),
      })
      .where(
        and(
          eq(compiledTemplates.userId, input.userId),
          eq(compiledTemplates.templateId, input.templateId),
          sql`${compiledTemplates.state} <> 'retired'`,
        ),
      );
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "template shadow observation not recorded",
    );
  }
}

/**
 * YANLIŞ YÜRÜTME ŞABLONU EMEKLİ EDER — geri dönüşü yoktur.
 *
 * Tek bir yanlış yürütme, şablonun kanonik olmadığının kesin kanıtıdır. Oran
 * hesabına girmez, eşik beklemez: derhal kapanır.
 */
export async function retireTemplate(
  app: FastifyInstance,
  input: { userId: string; templateId: string; reason: string },
): Promise<void> {
  try {
    await app.db
      .update(compiledTemplates)
      .set({
        state: "retired",
        retiredAt: new Date(),
        retiredReason: String(input.reason ?? "").slice(0, 120) || "unspecified",
        wrongExecutionCount: sql`${compiledTemplates.wrongExecutionCount} + 1`,
        updatedAt: new Date(),
      })
      .where(
        and(
          eq(compiledTemplates.userId, input.userId),
          eq(compiledTemplates.templateId, input.templateId),
        ),
      );
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "template retirement failed",
    );
  }
}

export type TemplatePromotionDecision =
  | { action: "hold"; reason: string }
  | { action: "advance"; to: "shadow" | "canary" }
  | { action: "retire"; reason: string };

/**
 * Bir sonraki adım ne olmalı — SAF karar, yan etkisiz.
 *
 * `active`'e terfi bu fonksiyondan ÇIKMAZ. Kanaryadan yayına geçiş bilinçli
 * olarak insan kararıdır; buradan en fazla "kanaryaya hazır" denir.
 */
export function decideTemplateLifecycle(
  template: StoredCompiledTemplate,
): TemplatePromotionDecision {
  if (template.wrongExecutionCount > 0) {
    return { action: "retire", reason: "wrong_execution_observed" };
  }
  if (template.state === "candidate") {
    return { action: "advance", to: "shadow" };
  }
  if (template.state === "shadow") {
    if (template.shadowMatches < TEMPLATE_SHADOW_MIN_MATCHES) {
      return { action: "hold", reason: "insufficient_shadow_matches" };
    }
    const agreement =
      template.shadowMatches > 0
        ? template.shadowAgreements / template.shadowMatches
        : 0;
    if (agreement < TEMPLATE_SHADOW_MIN_AGREEMENT) {
      return { action: "retire", reason: "shadow_disagreement" };
    }
    return { action: "advance", to: "canary" };
  }
  // canary → active geçişi otomatik YAPILMAZ.
  return { action: "hold", reason: "manual_release_required" };
}

export async function advanceTemplateState(
  app: FastifyInstance,
  input: { userId: string; templateId: string; to: CompiledTemplateState },
): Promise<void> {
  try {
    await app.db
      .update(compiledTemplates)
      .set({
        state: input.to,
        ...(input.to === "active" ? { promotedAt: new Date() } : {}),
        updatedAt: new Date(),
      })
      .where(
        and(
          eq(compiledTemplates.userId, input.userId),
          eq(compiledTemplates.templateId, input.templateId),
          sql`${compiledTemplates.state} <> 'retired'`,
        ),
      );
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "template state advance failed",
    );
  }
}

/**
 * SENTEZ TURU — epizot → aday → yaşam döngüsü.
 *
 * Bayrak kapalıyken hiç çalışmaz. Açıkken bile ürettiği en ileri durum
 * `canary`'dir; `active` yalnız açık bir yayın çağrısıyla verilir.
 *
 * Fail-open: öğrenme turu hiçbir görevi etkilemez.
 */
export async function runTemplateSynthesisRound(
  app: FastifyInstance,
  input: { userId: string; minEpisodes?: number; sinceDays?: number },
): Promise<{ candidates: number; advanced: number; retired: number }> {
  const summary = { candidates: 0, advanced: 0, retired: 0 };
  if (!app.config?.ELYAN_LEARNED_COMPILER_ENABLED) return summary;
  try {
    const groups = await listEpisodeDigestGroups(app, {
      userId: input.userId,
      sinceDays: input.sinceDays ?? 90,
      minTotal: input.minEpisodes ?? TEMPLATE_MIN_EPISODES,
    });
    if (groups.length === 0) return summary;

    const { candidates } = synthesizeCompiledTemplates(groups, {
      minEpisodes: input.minEpisodes,
    });
    summary.candidates = await upsertTemplateCandidates(app, {
      userId: input.userId,
      candidates,
    });

    const stored = await listTemplates(app, {
      userId: input.userId,
      states: ["candidate", "shadow", "canary"],
    });
    for (const template of stored) {
      const decision = decideTemplateLifecycle(template);
      if (decision.action === "advance") {
        await advanceTemplateState(app, {
          userId: input.userId,
          templateId: template.templateId,
          to: decision.to,
        });
        summary.advanced += 1;
      } else if (decision.action === "retire") {
        await retireTemplate(app, {
          userId: input.userId,
          templateId: template.templateId,
          reason: decision.reason,
        });
        summary.retired += 1;
      }
    }
    return summary;
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "template synthesis round failed",
    );
    return summary;
  }
}
