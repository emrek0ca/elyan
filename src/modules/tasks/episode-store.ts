/**
 * EPİZOT AMBARI — deneyimi yazılabilir ve GERİ ÇAĞRILABİLİR yapar.
 *
 * NEDEN VAR
 * ---------
 * `recordAgentTrajectory` zaten zengin bir epizot kaydı üretiyordu, ama onu
 * `learning_events` tablosunun `metadata` sütununa gömüyordu. Yazmak için
 * yeterliydi; okumak için değil. "Bu isteğe benzer daha önce ne yaptım ve
 * işe yaradı mı?" sorusu düz metin eşlemesiyle cevaplanamıyordu — öğrenmenin
 * eşdeğer adaylar arası bir tie-breaker'dan öteye geçememesinin yapısal
 * sebebi buydu.
 *
 * Burada aynı epizot TİPLİ bir satıra ve 384 boyutlu bir gömmeye yazılır.
 * Böylece geri çağırma semantik komşuluğa dayanır ve şablon sentezi (aynı
 * ailede tekrarlayan adım imzalarını bulma) tek bir indeks taramasına iner.
 *
 * GİZLİLİK SINIRI
 * ---------------
 * Ham istek metni yazılmaz. `agent_trajectory` sözleşmesinin kararı burada da
 * geçerli: özet (sha256), uzunluk kovası, dil ve TÜREV gömme. Adım kaydı
 * değer değil ŞEKİL taşır — capability adı ve argüman ANAHTARLARI. Argüman
 * değerleri hiçbir koşulda bu tabloya girmez.
 *
 * FAIL-OPEN
 * ---------
 * Bu yol öğrenme içindir, yürütme değil. Yazamamak bir görevi asla
 * etkilememeli; her hata yutulur ve yalnız telemetriye düşer.
 */

import { createHash } from "node:crypto";
import { and, desc, eq, gte, isNotNull, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { taskEpisodes } from "../../db/schema.js";
import { embedQueryForStorage, embedTextsForStorage } from "../brain/semantic-embedder.js";
import type { AgentTrajectoryRecord } from "./agent-trajectory.js";

export const TASK_EPISODE_EMBEDDING_MODEL = "storage-e5-384";

export type TaskEpisodeStepShape = {
  capability: string;
  device: string | null;
  /** Argüman ANAHTARLARI — değerler değil. Şablon sentezi bunlardan slot çıkarır. */
  argKeys: string[];
};

export type TaskEpisodeRow = {
  episodeId: string;
  intentFamily: string;
  route: string | null;
  mode: "compiled" | "dynamic" | null;
  contractDigest: string | null;
  stepShapes: TaskEpisodeStepShape[];
  outcomeVerdict: "fulfilled" | "degraded" | "unfulfilled";
  verificationEvidence: string[];
  latencyMs: number | null;
  createdAt: Date;
  similarity?: number;
};

function compact(value: unknown, max: number): string | null {
  const normalized = String(value ?? "").replace(/\s+/gu, " ").trim();
  if (!normalized) return null;
  return normalized.slice(0, max);
}

/**
 * Adım dizisinin İMZASI.
 *
 * Aynı işi yapan iki epizot, argümanları farklı olsa bile aynı imzayı
 * üretmelidir — şablon sentezi tekrarı buradan tanır. Bu yüzden imza yalnız
 * capability sırası ve argüman anahtar kümesi üzerinden hesaplanır.
 */
export function taskEpisodeContractDigest(steps: TaskEpisodeStepShape[]): string | null {
  if (steps.length === 0) return null;
  const canonical = steps
    .map((step) => `${step.capability}(${[...step.argKeys].sort().join(",")})`)
    .join("→");
  return createHash("sha256").update(canonical).digest("hex").slice(0, 48);
}

/** Trajectory kaydından adım ŞEKİLLERİNİ çıkarır; değer taşımaz. */
export function stepShapesFromTrajectory(
  record: AgentTrajectoryRecord,
): TaskEpisodeStepShape[] {
  const planned = record.plan.steps.map((step) => ({
    capability: compact(step.capability, 120) ?? "unknown",
    device: compact(step.device, 32),
    argKeys: Object.keys(step.args ?? {}).map((key) => compact(key, 60) ?? "").filter(Boolean),
  }));
  if (planned.length > 0) return planned.slice(0, 24);
  // Derlenmiş adım yoksa gerçekten çağrılan araçlar epizodun şeklidir.
  return record.toolCalls
    .map((call) => ({
      capability: compact(call.tool, 120) ?? "unknown",
      device: null,
      argKeys: Object.keys(call.args ?? {}).map((key) => compact(key, 60) ?? "").filter(Boolean),
    }))
    .slice(0, 24);
}

function intentFamilyFrom(record: AgentTrajectoryRecord): string {
  return (
    compact(record.modelDecision.intent, 120) ??
    compact(record.modelDecision.route, 120) ??
    "unknown"
  );
}

function toVectorLiteral(vector: number[]): string {
  return `[${vector.map((value) => (Number.isFinite(value) ? value : 0)).join(",")}]`;
}

export type RecordTaskEpisodeInput = {
  userId: string;
  taskId: string | null;
  turnId?: string | null;
  /**
   * Gömme ÜRETMEK için kullanılan istek metni. Saklanmaz — yalnız vektöre
   * dönüştürülür ve atılır.
   */
  requestText?: string | null;
  record: AgentTrajectoryRecord;
  mode?: "compiled" | "dynamic" | null;
  modelCalls?: number | null;
};

export async function recordTaskEpisode(
  app: FastifyInstance,
  input: RecordTaskEpisodeInput,
): Promise<boolean> {
  const { record } = input;
  try {
    const stepShapes = stepShapesFromTrajectory(record);
    // Gömme yalnız eğitime uygun epizotlar için üretilir: uygun olmayan bir
    // epizot geri çağırma havuzuna hiç girmemeli.
    const embedding =
      record.privacy.trainingEligible && input.requestText
        ? await embedTextsForStorage(
            [input.requestText],
            app.log,
            "task_episode",
          ).then((vectors) => vectors?.[0] ?? null)
        : null;

    await app.db
      .insert(taskEpisodes)
      .values({
        userId: input.userId,
        taskId: input.taskId,
        episodeId: record.episodeId,
        turnId: compact(input.turnId, 160),
        requestSha256: compact(record.request.sha256, 64),
        requestLengthBucket: compact(record.request.lengthBucket, 24),
        language: compact(record.request.language, 16),
        ...(embedding
          ? {
              requestEmbedding: toVectorLiteral(embedding),
              embeddingModel: TASK_EPISODE_EMBEDDING_MODEL,
            }
          : {}),
        intentFamily: intentFamilyFrom(record),
        route: compact(record.modelDecision.route, 64),
        mode: input.mode ?? null,
        contractDigest: taskEpisodeContractDigest(stepShapes),
        stepShapes,
        outcomeVerdict: record.outcome.verdict,
        verificationEvidence: record.verification.evidenceKinds.slice(0, 16),
        latencyMs: record.telemetry.latencyMs ?? null,
        modelCalls: input.modelCalls ?? null,
        repairAttempts: record.replanning.count ?? 0,
        trainingEligible: record.privacy.trainingEligible,
      })
      .onConflictDoNothing();
    return true;
  } catch (error) {
    app.log?.warn?.(
      {
        err: error instanceof Error ? error.message : String(error),
        taskId: input.taskId,
      },
      "task episode not recorded",
    );
    return false;
  }
}

export type RecallTaskEpisodesInput = {
  userId: string;
  requestText: string;
  intentFamily?: string | null;
  limit?: number;
  /** Yalnız bu doğrulukta veya daha iyi sonuçlananları getir. */
  minVerdict?: "fulfilled" | "degraded";
  sinceDays?: number;
};

/**
 * Benzer geçmiş epizotları SEMANTİK komşuluğa göre getirir.
 *
 * Gömme üretilemezse (worker kapalı/soğumada) boş döner — hash tabanlı bir
 * yaklaşıklığa düşmek, "benzer" olmayan epizotları benzer göstererek yanlış
 * ders çıkarmaya yol açardı. Kanıtsız geri çağırma yapmamak daha güvenli.
 */
export async function recallSimilarTaskEpisodes(
  app: FastifyInstance,
  input: RecallTaskEpisodesInput,
): Promise<TaskEpisodeRow[]> {
  const limit = Math.max(1, Math.min(20, input.limit ?? 5));
  try {
    const queryVector = await embedQueryForStorage(
      input.requestText,
      app.log,
      "task_episode",
    );
    if (!queryVector) return [];
    const literal = toVectorLiteral(queryVector);
    const filters = [
      eq(taskEpisodes.userId, input.userId),
      eq(taskEpisodes.trainingEligible, true),
      isNotNull(taskEpisodes.requestEmbedding),
    ];
    if (input.intentFamily) {
      filters.push(eq(taskEpisodes.intentFamily, input.intentFamily));
    }
    if (input.minVerdict === "fulfilled") {
      filters.push(eq(taskEpisodes.outcomeVerdict, "fulfilled"));
    } else if (input.minVerdict === "degraded") {
      filters.push(sql`${taskEpisodes.outcomeVerdict} in ('fulfilled', 'degraded')`);
    }
    if (input.sinceDays && input.sinceDays > 0) {
      filters.push(
        gte(
          taskEpisodes.createdAt,
          new Date(Date.now() - input.sinceDays * 86_400_000),
        ),
      );
    }

    const rows = await app.db
      .select({
        episodeId: taskEpisodes.episodeId,
        intentFamily: taskEpisodes.intentFamily,
        route: taskEpisodes.route,
        mode: taskEpisodes.mode,
        contractDigest: taskEpisodes.contractDigest,
        stepShapes: taskEpisodes.stepShapes,
        outcomeVerdict: taskEpisodes.outcomeVerdict,
        verificationEvidence: taskEpisodes.verificationEvidence,
        latencyMs: taskEpisodes.latencyMs,
        createdAt: taskEpisodes.createdAt,
        distance: sql<number>`${taskEpisodes.requestEmbedding} <=> ${literal}::vector`,
      })
      .from(taskEpisodes)
      .where(and(...filters))
      .orderBy(sql`${taskEpisodes.requestEmbedding} <=> ${literal}::vector`)
      .limit(limit);

    return rows.map((row) => ({
      episodeId: row.episodeId,
      intentFamily: row.intentFamily,
      route: row.route,
      mode: (row.mode as TaskEpisodeRow["mode"]) ?? null,
      contractDigest: row.contractDigest,
      stepShapes: Array.isArray(row.stepShapes)
        ? (row.stepShapes as TaskEpisodeStepShape[])
        : [],
      outcomeVerdict: row.outcomeVerdict as TaskEpisodeRow["outcomeVerdict"],
      verificationEvidence: Array.isArray(row.verificationEvidence)
        ? (row.verificationEvidence as string[])
        : [],
      latencyMs: row.latencyMs,
      createdAt: row.createdAt,
      similarity: 1 - Number(row.distance ?? 1),
    }));
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "task episode recall failed",
    );
    return [];
  }
}

export type EpisodeDigestGroup = {
  intentFamily: string;
  contractDigest: string;
  fulfilledCount: number;
  totalCount: number;
  stepShapes: TaskEpisodeStepShape[];
  evidenceKinds: string[];
  medianLatencyMs: number | null;
};

/**
 * Şablon sentezinin girdisi: aynı ailede aynı adım imzasının kaç kez ve hangi
 * sonuçla tekrarlandığı.
 *
 * Yalnız `training_eligible` epizotlar sayılır; kanıtsız "completed" olanlar
 * `fulfilled` sayılmaz çünkü verdict zaten kanıta bağlı üretiliyor.
 */
export async function listEpisodeDigestGroups(
  app: FastifyInstance,
  input: { userId?: string; intentFamily?: string; sinceDays?: number; minTotal?: number },
): Promise<EpisodeDigestGroup[]> {
  const minTotal = Math.max(2, input.minTotal ?? 20);
  try {
    const filters = [
      eq(taskEpisodes.trainingEligible, true),
      isNotNull(taskEpisodes.contractDigest),
    ];
    if (input.userId) filters.push(eq(taskEpisodes.userId, input.userId));
    if (input.intentFamily) filters.push(eq(taskEpisodes.intentFamily, input.intentFamily));
    if (input.sinceDays && input.sinceDays > 0) {
      filters.push(
        gte(taskEpisodes.createdAt, new Date(Date.now() - input.sinceDays * 86_400_000)),
      );
    }

    const rows = await app.db
      .select({
        intentFamily: taskEpisodes.intentFamily,
        contractDigest: taskEpisodes.contractDigest,
        totalCount: sql<number>`count(*)::int`,
        fulfilledCount: sql<number>`count(*) filter (where ${taskEpisodes.outcomeVerdict} = 'fulfilled')::int`,
        stepShapes: sql<unknown>`(array_agg(${taskEpisodes.stepShapes} order by ${taskEpisodes.createdAt} desc))[1]`,
        evidenceKinds: sql<unknown>`(array_agg(${taskEpisodes.verificationEvidence} order by ${taskEpisodes.createdAt} desc))[1]`,
        medianLatencyMs: sql<number | null>`percentile_disc(0.5) within group (order by ${taskEpisodes.latencyMs})`,
      })
      .from(taskEpisodes)
      .where(and(...filters))
      .groupBy(taskEpisodes.intentFamily, taskEpisodes.contractDigest)
      .having(sql`count(*) >= ${minTotal}`)
      .orderBy(desc(sql`count(*)`))
      .limit(64);

    return rows.map((row) => ({
      intentFamily: row.intentFamily,
      contractDigest: String(row.contractDigest ?? ""),
      fulfilledCount: Number(row.fulfilledCount ?? 0),
      totalCount: Number(row.totalCount ?? 0),
      stepShapes: Array.isArray(row.stepShapes)
        ? (row.stepShapes as TaskEpisodeStepShape[])
        : [],
      evidenceKinds: Array.isArray(row.evidenceKinds) ? (row.evidenceKinds as string[]) : [],
      medianLatencyMs:
        row.medianLatencyMs == null ? null : Number(row.medianLatencyMs),
    }));
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "episode digest grouping failed",
    );
    return [];
  }
}
