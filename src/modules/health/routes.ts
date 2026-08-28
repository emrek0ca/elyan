import type { FastifyPluginAsync, FastifyReply } from "fastify";
import { getReadiness } from "./service.js";
import { getPerfSnapshot } from "../../lib/perf-telemetry.js";
import { summarizeProactiveHealth } from "../brain/proactive-metrics.js";
import { getDesktopPlanCacheTelemetry } from "../tasks/plan-cache.js";
import { getPlanningCatalogCacheStats } from "../tasks/materialize-plan.js";
import { nlpDaemon } from "../../lib/nlp-daemon.js";
import {
  evaluateVoiceLatencyTargets,
  getVoiceStreamingTelemetry,
} from "../speech/voice-metrics.js";

export const healthRoutes: FastifyPluginAsync = async (app) => {
  const shapePublicHealthPayload = (readiness: Awaited<ReturnType<typeof getReadiness>>) => ({
    ok: readiness.ok,
    status: readiness.ok ? "ok" : "degraded",
    timestamp: new Date().toISOString(),
    mobile: {
      statusSummary: readiness.mobile.statusSummary,
      safeForExternalClients: readiness.mobile.safeForExternalClients,
    },
    realtime: {
      sseEnabled: readiness.realtime.sseEnabled,
      websocketEnabled: readiness.realtime.websocketEnabled,
      heartbeatSeconds: readiness.realtime.heartbeatSeconds,
    },
    coreSurfaces: readiness.coreSurfaces,
    network: {
      warning: readiness.network.warning,
      externalClientsCanReachAdvertisedBaseUrl:
        readiness.network.externalClientsCanReachAdvertisedBaseUrl,
      advertisedBaseUrl: readiness.network.advertisedBaseUrl,
    },
  });

  const sendReadiness = async (reply: FastifyReply) => {
    const readiness = await getReadiness(app);
    const payload = shapePublicHealthPayload(readiness);

    if (!readiness.ok) {
      reply.header("retry-after", "15");
      return reply.status(503).send(payload);
    }

    return reply.send(payload);
  };

  // İç gözlem: event loop lag + stage p95. Kimlik verisi içermez, yalnız
  // süre istatistikleri — operasyonel teşhis için.
  app.get("/internal/perf", async () => ({
    ...getPerfSnapshot(),
    // C NLP çekirdeği. Bakılacak alan `degraded`: süreç AYAKTA olduğu hâlde
    // istekler üst üste düşüyorsa anlama katmanı sessizce JS yedeğinde
    // çalışıyor demektir — ölüm görünürdü, bu hâl değildi.
    nlpDaemon: nlpDaemon.stats(),
    desktopPlanCache: getDesktopPlanCacheTelemetry(),
    desktopPlanningCatalogCache: getPlanningCatalogCacheStats(),
    // Live voice (CANLI-SES-PLANI.md §4). The p95 targets live in the stage
    // table above as voice.first_partial (<400ms) and
    // voice.final_to_dispatch (<800ms); this adds the revision rate, which is
    // a ratio rather than a duration.
    voiceStreaming: {
      ...getVoiceStreamingTelemetry(),
      // Verdict, not just numbers: `breached` is what a probe should watch.
      latencyTargets: evaluateVoiceLatencyTargets(),
    },
  }));

  // Proaktif sağlık: fleet geneli, kimlik verisi YOK — yalnız sayımlar ve
  // oranlar. Bakılacak tek sayı muteRate: yükselirse sorun kodda değil
  // tasarımdadır (Elyan susması gereken yerde konuşuyor).
  app.get("/internal/proactive-health", async (request) => {
    const query = (request.query ?? {}) as Record<string, unknown>;
    const windowDays = Number.parseInt(String(query.windowDays ?? "7"), 10);
    return summarizeProactiveHealth(app, {
      windowDays: Number.isFinite(windowDays) ? windowDays : 7,
    });
  });

  app.get("/livez", async () => ({
    status: "ok",
    service: "elyan-backend",
    timestamp: new Date().toISOString(),
  }));

  app.get("/readyz", async (request, reply) => {
    const readiness = await getReadiness(app);

    if (!readiness.ok) {
      return reply.status(503).send({
        status: "degraded",
        ...readiness,
      });
    }

    return {
      status: "ok",
      ...readiness,
    };
  });

  app.get("/healthz", async (request, reply) => {
    return sendReadiness(reply);
  });

  app.get("/control-plane/health", async (request, reply) => {
    return sendReadiness(reply);
  });
};
