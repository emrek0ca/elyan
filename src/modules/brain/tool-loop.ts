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
import { buildRequestBody } from "./provider-request.js";
import { postJson } from "./provider-http.js";
import type { SharedBrainProvider } from "./runtime.js";

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

export type ServerToolLoopResult = {
  text: string;
  steps: ToolLoopStep[];
  rounds: number;
  promptTokens: number;
  completionTokens: number;
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
    options.allowlist === undefined ? null : new Set(options.allowlist);
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
    shouldAbort?: AgentToolContext["shouldAbort"];
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
    shouldAbort: input.shouldAbort,
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

/**
 * TAM DÖNGÜ: model → tool_call → gerçek sonuç → model → … → cevap
 *
 * Kendi sağlayıcı gidiş-dönüşünü yapar. Ana `inference.ts` akışının içine
 * yerleştirilmedi çünkü orada yanıt tüketimi ÜÇ ayrı yere dağılmış (akışlı,
 * akışsız, aday) ve altı denemeli bir yedekleme makinesinin içinde; oraya
 * körlemesine dokunmak bugün çalışır hale gelen sohbet yolunu riske atardı.
 * Bu fonksiyon o makineyi değiştirmeden, aynı ilkelerle (aynı istek kurucusu,
 * aynı yürütücü, aynı onay sınırı) döngüyü tamamlar.
 *
 * Sözleşme:
 *   - Model araç istemezse ilk turda düz cevabı döner (döngü maliyeti sıfır).
 *   - Araç isterse sonuçlar `tool` mesajı olarak geri beslenir ve model
 *     devam eder; en fazla `TOOL_LOOP_MAX_ROUNDS` tur.
 *   - Tur tavanı dolarsa modele araçsız son bir tur verilir ki kullanıcı
 *     cevapsız kalmasın (bu projede cevapsız tur = "hâlâ çalışıyor"da donma).
 */
export async function runServerToolLoop(
  app: FastifyInstance,
  input: {
    provider: SharedBrainProvider;
    model: string;
    url: string;
    messages: Array<Record<string, unknown>>;
    maxTokens: number;
    temperature: number;
    reasoningEffort: "low" | "medium" | "high";
    userId: string;
    sessionId?: string | null;
    taskId?: string | null;
    workload: AgentToolContext["workload"];
    allowlist?: readonly string[];
    timeoutMs?: number;
    requestKeySeed?: string;
    shouldAbort?: AgentToolContext["shouldAbort"];
  },
): Promise<ServerToolLoopResult> {
  const tools = buildReadOnlyServerTools({ allowlist: input.allowlist });
  const allowedToolByProviderName = new Map(
    tools.flatMap((tool) => {
      const providerName = tool.function.name;
      const registryName = serverToolForName(providerName);
      return registryName ? [[providerName, registryName] as const] : [];
    }),
  );
  const messages = [...input.messages];
  const steps: ToolLoopStep[] = [];
  let promptTokens = 0;
  let completionTokens = 0;
  const finish = (text: string, rounds: number): ServerToolLoopResult => ({
    text,
    steps,
    rounds,
    promptTokens,
    completionTokens,
  });

  for (let round = 0; round < TOOL_LOOP_MAX_ROUNDS; round += 1) {
    if (input.shouldAbort && (await input.shouldAbort())) {
      throw new Error("task_canceled");
    }
    const lastRound = round === TOOL_LOOP_MAX_ROUNDS - 1;
    const body = buildRequestBody(
      input.provider,
      input.model,
      messages as never,
      input.maxTokens,
      undefined,
      false,
      [],
      "hidden",
      input.reasoningEffort,
      input.temperature,
      undefined,
      false,
      false,
      // Son turda araç sunulmaz: model artık CEVAP vermeli, yeni iş açmamalı.
      lastRound ? undefined : tools,
      "auto",
    ) as Record<string, unknown>;

    const response = await postJson(
      app,
      input.provider,
      input.url,
      body,
      input.timeoutMs,
      input.requestKeySeed,
    );
    if (!response.ok) {
      throw new Error(`server_tool_loop_http_${response.status}`);
    }
    const payload = (await response.json()) as {
      choices?: Array<{
        message?: {
          content?: unknown;
          tool_calls?: unknown;
        };
      }>;
      usage?: {
        prompt_tokens?: unknown;
        completion_tokens?: unknown;
        input_tokens?: unknown;
        output_tokens?: unknown;
      };
    };
    promptTokens +=
      Number(
        payload.usage?.prompt_tokens ?? payload.usage?.input_tokens ?? 0,
      ) || 0;
    completionTokens +=
      Number(
        payload.usage?.completion_tokens ?? payload.usage?.output_tokens ?? 0,
      ) || 0;
    const message = payload.choices?.[0]?.message;
    const rawCalls = message?.tool_calls;
    const requested = Array.isArray(rawCalls) ? rawCalls : [];

    if (requested.length === 0) {
      const text = typeof message?.content === "string" ? message.content : "";
      return finish(text, round + 1);
    }

    // Modelin kendi araç isteği konuşmaya AYNEN geri konur; sağlayıcı bir
    // sonraki turda `tool` mesajlarını ancak bu çağrıyla eşleştirebilir.
    messages.push({
      role: "assistant",
      content: typeof message?.content === "string" ? message.content : "",
      tool_calls: requested,
    });

    const calls = requested
      .map((item) => {
        const record = item as Record<string, unknown>;
        const fn = record.function as Record<string, unknown> | undefined;
        const name = typeof fn?.name === "string" ? fn.name : "";
        const tool = lastRound ? null : allowedToolByProviderName.get(name);
        if (!tool) return null;
        let args: Record<string, unknown> = {};
        const rawArgs = fn?.arguments;
        if (typeof rawArgs === "string" && rawArgs.trim()) {
          try {
            const parsed: unknown = JSON.parse(rawArgs);
            if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
              args = parsed as Record<string, unknown>;
            }
          } catch {
            return null;
          }
        }
        return {
          id: typeof record.id === "string" ? record.id : tool,
          tool,
          args,
        };
      })
      .filter((call): call is { id: string; tool: string; args: Record<string, unknown> } => call != null);

    if (calls.length === 0) {
      // Model yalnız tanınmayan/bozuk araç istedi: yeni tur açmak aynı hatayı
      // tekrarlatır. Elimizdeki metinle dönmek daha dürüst.
      const text = typeof message?.content === "string" ? message.content : "";
      return finish(text, round + 1);
    }

    const executed = await runToolCalls(app, {
      userId: input.userId,
      sessionId: input.sessionId,
      taskId: input.taskId,
      workload: input.workload,
      shouldAbort: input.shouldAbort,
      calls,
    });
    steps.push(...executed);

    for (const [index, call] of calls.entries()) {
      const result = executed[index];
      messages.push({
        role: "tool",
        tool_call_id: call.id,
        content: result
          ? toolResultToMessage({
              tool: call.tool,
              ok: result.ok,
              permission: "read",
              durationMs: result.durationMs,
              output: result.output,
              error: result.error,
            })
          : JSON.stringify({ ok: false, error: "tool_missing_result" }),
      });
    }
  }

  return finish("", TOOL_LOOP_MAX_ROUNDS);
}
