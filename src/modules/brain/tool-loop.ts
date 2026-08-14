import type { FastifyInstance } from "fastify";
import {
  executeAgentTool,
  getAgentToolMetadata,
  listAgentTools,
  type AgentToolContext,
  type AgentToolResult,
} from "./tool-registry.js";
import { serverToolJsonSchema } from "./tool-schemas.js";
import type { ChatCompletionTool } from "./tool-schemas.js";

/**
 * GÖZLE-UYGULA DÖNGÜSÜ.
 *
 * Elyan bugüne kadar araç ÇAĞIRMIYOR, araç PLANI yazıyordu: model şemaya uyan
 * tek bir plan üretiyor, backend onu materyalize ediyor, sonuç modele geri
 * DÖNMÜYORDU. ChatGPT/Gemini'yi farklı kılan şey tam olarak bu döngü:
 *
 *   model → tool_call → gerçek sonuç → model → tool_call → ... → cevap
 *
 * Plan-tek-atış yaklaşımının iki ölçülmüş bedeli vardı: `json_validate_failed`
 * kırılganlığı (2026-08-08 ve 2026-08-13, ikincisinde PDF hiç üretilemedi) ve
 * modelin kendi araç çıktısını görüp üstüne düşünememesi.
 *
 * GÜVENLİK SINIRI — BU DOSYANIN EN ÖNEMLİ ÖZELLİĞİ:
 * Döngü YALNIZ okuma izinli araçları sunar ve `executeAgentTool`'u
 * `allowSideEffects: false` + `allowStateWrites: false` ile çağırır. Yan etkili
 * ve yazan araçlar mevcut ONAY yolundan geçmeye devam eder. Modele doğrudan
 * verilmeleri onay kapısını atlatmak olurdu; bu proje o kapıyı bir kez atlamayı
 * denedi ve 28 regresyon üretti.
 */

export type ToolLoopStep = {
  tool: string;
  args: Record<string, unknown>;
  ok: boolean;
  durationMs: number;
  output: Record<string, unknown> | null;
  error: { code: string; message: string } | null;
};

export type ToolLoopMessage = {
  role: "assistant" | "tool";
  content: string;
  tool_call_id?: string;
  tool_calls?: unknown;
};

/** Bir turda izin verilen azami araç turu. Sonsuz döngüye karşı sert tavan. */
export const TOOL_LOOP_MAX_ROUNDS = 4;
/** Tek turda paralel çalıştırılacak azami araç. */
export const TOOL_LOOP_MAX_PARALLEL = 4;

/**
 * Modele sunulacak SALT-OKUNUR sunucu araçları.
 *
 * Kayıtta bugün 18 araç var: 14 okuma, 2 yazma, 2 yan etkili. Yalnız okuma
 * olanlar sunulur — sınır burada, çağıran tarafta değil, ki bir çağıran onu
 * gevşetmeyi unutamasın.
 */
export function buildReadOnlyServerTools(options: {
  allowlist?: readonly string[];
} = {}): ChatCompletionTool[] {
  const allow =
    options.allowlist && options.allowlist.length > 0
      ? new Set(options.allowlist)
      : null;
  const tools: ChatCompletionTool[] = [];
  for (const entry of listAgentTools()) {
    if (entry.permission !== "read") continue;
    if (allow && !allow.has(entry.name)) continue;
    const metadata = getAgentToolMetadata(entry.name);
    if (!metadata) continue;
    const schema = serverToolJsonSchema(entry.name);
    if (!schema) continue;
    const description = [metadata.selectionHints.purpose, metadata.selectionHints.modelContract]
      .filter((part): part is string => typeof part === "string" && part.trim().length > 0)
      .join(" ")
      .trim()
      .slice(0, 1024);
    if (!description) continue;
    tools.push({
      type: "function",
      function: {
        name: serverToolName(entry.name),
        description,
        parameters: schema,
      },
    });
  }
  return tools;
}

/** `web.search` → `web_search` (sağlayıcı ad kuralı). */
export function serverToolName(tool: string): string {
  return tool.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 64);
}

const SERVER_TOOL_BY_NAME = new Map<string, string>(
  listAgentTools().map((entry) => [serverToolName(entry.name), entry.name]),
);

export function serverToolForName(name: string): string | null {
  return SERVER_TOOL_BY_NAME.get(name) ?? null;
}

/**
 * Araç sonucunu modele geri verilecek metne çevirir.
 *
 * Ham çıktı çok büyük olabilir (web araması, dosya listesi). Kırpılmazsa bir
 * sonraki turun bağlam bütçesini yiyip modeli cevapsız bırakır — bu projede
 * token bütçesi tükenmesi zaten boş üretim üretiyor.
 */
export function toolResultToMessage(result: AgentToolResult): string {
  if (!result.ok) {
    return JSON.stringify({
      ok: false,
      error: result.error?.code ?? "tool_failed",
      message: result.error?.message ?? "",
    });
  }
  const payload = JSON.stringify({ ok: true, output: result.output ?? {} });
  return payload.length > 8_000 ? `${payload.slice(0, 8_000)}…` : payload;
}

/**
 * Model tarafından istenen araçları çalıştırır.
 *
 * Paralel çalıştırma bilinçli: ChatGPT/Gemini bir turda birden çok aracı aynı
 * anda çağırır ve plan-şeması bunu ifade edemiyordu. Yalnız okuma araçları
 * sunulduğu için paralellik yan etki sırası sorunu doğurmaz.
 */
export async function runToolCalls(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId?: string | null;
    taskId?: string | null;
    workload: AgentToolContext["workload"];
    calls: Array<{ id: string; tool: string; args: Record<string, unknown> }>;
  },
): Promise<ToolLoopStep[]> {
  const context: AgentToolContext = {
    userId: input.userId,
    sessionId: input.sessionId ?? null,
    taskId: input.taskId ?? null,
    workload: input.workload,
    // ONAY SINIRI. Bu iki bayrak asla `true` yapılmamalı: döngü modele yalnız
    // okuma araçları sunuyor ve yürütücü de yan etkiyi burada kapatıyor.
    // Gevşetilirse model, kullanıcı onayı olmadan yan etkili iş çalıştırabilir.
    allowSideEffects: false,
    allowStateWrites: false,
  };
  const calls = input.calls.slice(0, TOOL_LOOP_MAX_PARALLEL);
  const results = await Promise.all(
    calls.map(async (call) => {
      try {
        const result = await executeAgentTool(app, context, {
          tool: call.tool,
          args: call.args,
        });
        return {
          tool: call.tool,
          args: call.args,
          ok: result.ok,
          durationMs: result.durationMs,
          output: result.output,
          error: result.error,
        } satisfies ToolLoopStep;
      } catch (error) {
        // Bir aracın patlaması turu öldürmemeli; model hatayı GÖRÜP başka bir
        // yol deneyebilmeli. Sessizce yutmak, modeli kör bırakır.
        return {
          tool: call.tool,
          args: call.args,
          ok: false,
          durationMs: 0,
          output: null,
          error: {
            code: "tool_execution_failed",
            message: error instanceof Error ? error.message : "tool failed",
          },
        } satisfies ToolLoopStep;
      }
    }),
  );
  return results;
}
