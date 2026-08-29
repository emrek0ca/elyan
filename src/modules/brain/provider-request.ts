import type { ResolvedAttachmentContextVisionImage } from "./attachment-context.js";
import type { ChatCompletionTool } from "./tool-schemas.js";
import {
  ANALYTICAL_GENERATION_TEMPERATURE,
} from "./generation-policy.js";
import { resolveProviderModelCapabilities } from "./provider-capabilities.js";
import type { SharedBrainProvider } from "./runtime.js";
import {
  buildTurnEnvelopeSystemInstruction,
  buildTurnEnvelopeResponseFormat,
  TURN_ENVELOPE_COMPACT_SCHEMA_INSTRUCTION,
} from "./turn-envelope.js";
import { collapseWhitespace as compactText } from "../../lib/text.js";

export type SharedBrainConversationMessage = {
  role: "system" | "user" | "assistant";
  content: string;
};

export type SharedBrainRequestAttempt = {
  path: string;
  body: Record<string, unknown>;
  turnEnvelopeMode?: boolean;
  forceNonStreaming?: boolean;
};

type OpenAiContentBlock =
  | { type: "text"; text: string }
  | { type: "image_url"; image_url: { url: string; detail?: "low" | "high" | "auto" } };

export function getChatCompletionPath(provider: SharedBrainProvider): string {
  if (provider === "ollama") {
    return "/api/chat";
  }
  if (provider === "claude") {
    return "/messages";
  }
  return "/chat/completions";
}

/** Native shared-brain endpoint. Gemini utilities keep the compatibility path. */
export function getNativeChatPath(
  provider: SharedBrainProvider,
  stream = false,
): string {
  if (provider === "gemini") {
    return stream ? "/interactions?alt=sse" : "/interactions";
  }
  return getChatCompletionPath(provider);
}

function buildAnthropicRequestBody(
  model: string,
  messages: SharedBrainConversationMessage[],
  maxTokens: number,
) {
  const system = messages
    .filter((message) => message.role === "system")
    .map((message) => compactText(message.content))
    .filter(Boolean)
    .join("\n\n");

  return {
    model,
    max_tokens: maxTokens,
    temperature: 0.25,
    ...(system ? { system } : {}),
    messages: messages
      .filter((message) => message.role !== "system")
      .map((message) => ({
        role: message.role === "assistant" ? "assistant" : "user",
        content: [
          {
            type: "text",
            text: message.content,
          },
        ],
      })),
  };
}

function buildOpenAiMessagesWithVision(
  provider: SharedBrainProvider,
  messages: SharedBrainConversationMessage[],
  visionImages: ResolvedAttachmentContextVisionImage[],
): unknown[] {
  if (visionImages.length === 0) {
    return messages as unknown[];
  }
  const result: unknown[] = [];
  for (let i = 0; i < messages.length; i += 1) {
    const msg = messages[i];
    if (i === messages.length - 1 && msg.role === "user") {
      const textContent =
        typeof msg.content === "string"
          ? msg.content
          : String(msg.content ?? "");
      const blocks: OpenAiContentBlock[] = [
        { type: "text", text: textContent },
      ];
      for (const img of visionImages.slice(0, 5)) {
        blocks.push({
          type: "image_url",
          image_url: {
            url: `data:${img.mimeType};base64,${img.base64}`,
            ...(provider === "gemini" && img.detail ? { detail: img.detail } : {}),
          },
        });
      }
      result.push({ ...msg, content: blocks });
    } else {
      result.push(msg);
    }
  }
  return result;
}

type GeminiInteractionContentPart =
  | { type: "text"; text: string }
  | { type: "image"; data: string; mime_type: string };

type GeminiInteractionInputStep = {
  type: "user_input" | "model_output";
  content: GeminiInteractionContentPart[];
};

function buildGeminiInteractionInput(
  messages: SharedBrainConversationMessage[],
  visionImages: ResolvedAttachmentContextVisionImage[],
): GeminiInteractionInputStep[] {
  const conversationMessages = messages.filter(
    (message) => message.role !== "system",
  );
  const lastUserIndex = conversationMessages.reduce(
    (lastIndex, message, index) =>
      message.role === "user" ? index : lastIndex,
    -1,
  );

  return conversationMessages.flatMap((message, index) => {
    const text = message.content.trim();
    const content: GeminiInteractionContentPart[] = text
      ? [{ type: "text", text: message.content }]
      : [];

    // Images belong to the current user turn, not to a synthetic transcript
    // after the conversation. The preprocessor enforces byte and pixel
    // budgets before this adapter is reached.
    if (message.role === "user" && index === lastUserIndex) {
      for (const image of visionImages.slice(0, 10)) {
        content.push({
          type: "image",
          data: image.base64,
          mime_type: image.mimeType,
        });
      }
    }

    if (content.length === 0) return [];
    const type: GeminiInteractionInputStep["type"] =
      message.role === "assistant" ? "model_output" : "user_input";
    return [
      {
        type,
        content,
      },
    ];
  });
}

function buildGeminiInteractionsRequestBody(
  model: string,
  messages: SharedBrainConversationMessage[],
  maxTokens: number,
  stream: boolean,
  visionImages: ResolvedAttachmentContextVisionImage[],
  reasoningEffort: "low" | "medium" | "high",
  temperature: number,
  responseSchema?: Record<string, unknown>,
  jsonObjectMode = false,
): Record<string, unknown> {
  const systemInstruction = messages
    .filter((message) => message.role === "system")
    .map((message) => message.content.trim())
    .filter(Boolean)
    .join("\n\n");
  const generationConfig: Record<string, unknown> = {
    temperature,
    max_output_tokens: maxTokens,
    thinking_level: capReasoningEffortForBudget(
      reasoningEffort,
      maxTokens,
      Boolean(responseSchema) || jsonObjectMode,
    ),
    thinking_summaries: "none",
  };
  if (visionImages.some((image) => image.detail === "high")) {
    generationConfig.media_resolution = "high";
  }

  return {
    model,
    input: buildGeminiInteractionInput(messages, visionImages),
    store: false,
    stream,
    ...(systemInstruction ? { system_instruction: systemInstruction } : {}),
    generation_config: generationConfig,
    ...(responseSchema
      ? {
          response_format: {
            type: "text",
            mime_type: "application/json",
            schema: responseSchema,
          },
        }
      : jsonObjectMode
        ? {
            response_format: {
              type: "text",
              mime_type: "application/json",
            },
          }
        : {}),
  };
}

export function buildRequestBody(
  provider: SharedBrainProvider,
  model: string,
  messages: SharedBrainConversationMessage[],
  maxTokens: number,
  keepAlive?: string,
  stream = false,
  visionImages: ResolvedAttachmentContextVisionImage[] = [],
  reasoningPolicy: "hidden" | "visible" = "hidden",
  reasoningEffort: "low" | "medium" | "high" = "low",
  temperature: number = ANALYTICAL_GENERATION_TEMPERATURE,
  responseSchema?: Record<string, unknown>,
  // Makine-JSON rotaları (masaüstü plan/anlama) için: şema DAYATMADAN düzyazıyı
  // yasakla. Şema dayatmak §4.11'de modeli iki şema arasında sıkıştırıp boş
  // üretime sokmuştu; json_object ise biçim serbest bırakır, yalnız "bu bir
  // JSON nesnesi olacak" der. Bunsuz model soruyu CEVAPLIYOR (ölçüldü: soru
  // biçimli mesajlarda ~%40 düzyazı → sınıflandırma kaybı → degraded).
  jsonObjectMode = false,
  nativeGemini = false,
  // YEREL ARAÇ ÇAĞRISI. Verilmezse davranış birebir eskisi gibidir.
  //
  // Ana sohbet yolu bugüne kadar modele HİÇ araç göndermiyordu: yetenekler
  // yalnız prompt metniydi ve model, dayatılan bir plan şemasını doldurmaya
  // çalışıyordu. O yol `response_format: json_schema` üzerinden gittiği için
  // reasoning kanalı olan modellerde Groq `json_validate_failed` ile 400
  // dönüyor (ölçüldü: 2026-08-08 yönlendirme, 2026-08-13 görev a4924a76).
  // Araçlar sağlayıcının kendi mekanizmasıyla verildiğinde o hata sınıfı yok
  // ve model aracı GERÇEKTEN seçebiliyor.
  //
  // Şema modu ile araç modu AYNI istekte gönderilmez: ikisi modelden farklı
  // çıktı biçimi ister ve birlikte gönderildiğinde sağlayıcı çoğu kez şemayı
  // kazandırıp araç çağrısını sessizce düşürür.
  tools?: ChatCompletionTool[],
  toolChoice: "auto" | "none" | "required" = "auto",
) {
  if (provider === "ollama") {
    return {
      model,
      messages,
      stream,
      ...(keepAlive ? { keep_alive: keepAlive } : {}),
      options: {
        temperature,
        num_predict: maxTokens,
      },
    };
  }

  if (provider === "claude") {
    return buildAnthropicRequestBody(model, messages, maxTokens);
  }

  if (provider === "gemini" && nativeGemini) {
    return buildGeminiInteractionsRequestBody(
      model,
      messages,
      maxTokens,
      stream,
      visionImages,
      reasoningEffort,
      temperature,
      responseSchema,
      jsonObjectMode,
    );
  }

  // BASTIRMA ARTIK MODELE ÖZEL (2026-08-22).
  //
  // Kural qwen/qwen3.6-27b için yazılmıştı — o model makine rotasında
  // `response_format` gönderilince 400 dönüyor. Ama koşul TÜM Groq modellerine
  // uygulanıyordu; yani asıl planlayıcı (gpt-oss) da hiçbir biçim kısıtı
  // ALMADAN çağrılıyordu ve model düzyazı dönmekte serbestti.
  //
  // Canlı bedel: iki görevde de ilk planlama denemesi Markdown tablo döndü
  // (`jsonObjectFound: false`), üstelik PLANI DOĞRUYDU ("Metin üret → belgeye
  // yaz"). Onarım yolu sıfırdan planlayıp tek adıma çöktü ve belgeye konu
  // tarifi yazıldı.
  //
  // Ölçüm (gerçek 33KB planlama promptu, canlı Groq):
  //   qwen/qwen3.6-27b   biçim yok → 0/2 JSON   json_object → 0/2 (HTTP 400)
  //   openai/gpt-oss-20b biçim yok → 2/2 JSON   json_object → 2/2
  //   openai/gpt-oss-120b                        json_object → 4/4 (2–3 adım)
  //
  // Yani bastırma qwen için HÂLÂ gerekli, gpt-oss için saf kayıp. `json_object`
  // sağlayıcı düzeyinde zorlama sağlar; sistem istemi ne derse desin çıktı JSON
  // kalır. `json_schema` (katı) DEĞİL — o gpt-oss'ta json_validate_failed
  // veriyordu ve `modelSupportsJsonSchemaFormat` zaten onu eliyor.
  const suppressGroqMachineJsonResponseFormat =
    provider === "groq" &&
    jsonObjectMode &&
    modelRejectsMachineJsonResponseFormat(model);
  const outMessages = buildOpenAiMessagesWithVision(provider, messages, visionImages);
  return {
    model,
    messages: outMessages,
    temperature,
    max_tokens: maxTokens,
    stream,
    ...(tools && tools.length > 0 &&
    ["groq", "openai", "openrouter"].includes(provider)
      ? { tools, tool_choice: toolChoice }
      : {}),
    // ŞEMA MODU YALNIZ DESTEKLEYEN MODELE GÖNDERİLİR.
    //
    // Yetenek kontrolü (`modelSupportsJsonSchemaFormat`) kod tabanında zaten
    // vardı ama SADECE TurnEnvelope yolunda uygulanıyordu; ana istek kurucusu
    // şemayı koşulsuz ekliyordu. Sonuç canlıda ölçüldü (2026-08-14, görev
    // 20687958 — "Bana anlatır mısın Atatürk'ün gençliğini"):
    //   llama-3.1-8b + json_schema → HTTP 400 invalid_request_error
    //   gpt-oss-20b  + json_schema → json_validate_failed
    // İki model de reddedince zincir tükendi ve kullanıcı "Bu turda yanıt
    // oluşturulamadı" gördü. Doğrudan sağlayıcıya atılan testte llama'nın
    // `json_object` modunda 200 döndüğü doğrulandı.
    //
    // Desteklemeyen modelde `json_object`e düşüyoruz: biçim yine JSON'a
    // zorlanır, şema ise prompt'ta anlatılır. Cevapsız kalmaktansa şemasız
    // ama GEÇERLİ bir JSON almak her zaman iyidir.
    ...(!suppressGroqMachineJsonResponseFormat &&
    !(tools && tools.length > 0) &&
    responseSchema &&
    ["gemini", "groq", "openai", "openrouter"].includes(provider)
      ? modelSupportsJsonSchemaFormat(provider, model)
        ? {
            response_format: {
              type: "json_schema",
              json_schema: {
                name: "elyan_structured_output",
                strict: true,
                schema: responseSchema,
              },
            },
          }
        : { response_format: { type: "json_object" } }
      : !suppressGroqMachineJsonResponseFormat &&
          !(tools && tools.length > 0) &&
          jsonObjectMode &&
          ["gemini", "groq", "openai", "openrouter"].includes(provider)
        ? { response_format: { type: "json_object" } }
        : {}),
    // DÜŞÜNME BÜTÇESİ, GÖRÜNÜR ÇIKTIYI AÇ BIRAKMAMALI.
    //
    // gpt-oss ailesinde gizli düşünme turu `max_tokens`a SAYILIR. Eşik
    // 1500'dü ve ÇIPLAK BİR SAYIYDI; asıl kuralı ifade etmiyordu.
    //
    // Kural şu: çıktının GEÇERLİ JSON OLMAK ZORUNDA olduğu turlarda kesilme
    // bir kalite kaybı değil, SERT BİR HATADIR. Yarım cümle okunabilir ama
    // yarım JSON'u Groq 400 `json_validate_failed` ile reddeder; hiç token
    // kalmazsa da akış boş döner. İki belirti de canlıda ölçüldü
    // (2026-08-30, `document_generate`): 13 denemenin tamamı bu iki sebeple
    // düştü ve kullanıcı hiçbir çıktı alamadı.
    //
    // Bu yüzden taban makine-JSON turlarında daha yüksek: düşünme, gövdeyi
    // yazacak yeri BIRAKMAK zorunda. Serbest metin turlarında eski taban
    // korunur — orada kesilme yalnız cevabı kısaltır.
    ...(resolveProviderModelCapabilities(provider, model).reasoningRequestControls
      ? {
          reasoning_format: reasoningPolicy === "visible" ? "parsed" : "hidden",
          reasoning_effort: capReasoningEffortForBudget(
            reasoningEffort,
            maxTokens,
            Boolean(responseSchema) || jsonObjectMode,
          ),
        }
      : {}),
  };
}

export function buildGenerateRequestBody(
  model: string,
  prompt: string,
  maxTokens: number,
  keepAlive?: string,
  stream = false,
  temperature: number = ANALYTICAL_GENERATION_TEMPERATURE,
) {
  return {
    model,
    prompt,
    stream,
    ...(keepAlive ? { keep_alive: keepAlive } : {}),
    options: {
      temperature,
      num_predict: maxTokens,
    },
  };
}

function supportsTurnEnvelopeResponseFormat(
  provider: SharedBrainProvider,
  path: string,
): boolean {
  return (
    (path === getChatCompletionPath(provider) &&
      (provider === "groq" ||
        provider === "openai" ||
        provider === "openrouter" ||
        provider === "gemini")) ||
    (provider === "gemini" && path.startsWith("/interactions"))
  );
}

/**
 * Groq'ta `json_schema` yalnız yapılandırılmış çıktı destekleyen modellerde
 * çalışır. gpt-oss ailesi JSON üretebilir ama canlı reasoning + şema zorlaması
 * kombinasyonunda `json_validate_failed`/boş çıktı üretebildi; bu da normal
 * sohbet zarfında araç/skill seçiminin hiç ulaşmamasına ve gereksiz provider
 * fallback gecikmesine yol açtı. Bu modellerde `json_object` kullanılır:
 * zarf sözleşmesi system prompt'a taşınır, otoriter doğrulama typed parser'da
 * kalır. qwen gibi diğer desteklenmeyen modeller de aynı fallback'i kullanır.
 */
/**
 * Makine-JSON rotasında `response_format` gönderilince 400 dönen modeller.
 *
 * Ölçülerek doldurulur, tahminle değil. Bugün tek üye qwen ailesi.
 */
/**
 * `reasoning_effort: "high"` için asgari token tabanları.
 *
 * Serbest metinde kesilme cevabı kısaltır; makine-JSON'da ise çıktıyı
 * TAMAMEN geçersiz kılar (Groq 400 `json_validate_failed`) veya hiç görünür
 * token bırakmaz. Bu yüzden iki farklı taban.
 */
export const FREE_TEXT_HIGH_REASONING_FLOOR = 1_500;
export const MACHINE_JSON_HIGH_REASONING_FLOOR = 3_000;

/**
 * TABAN HER SAĞLAYICIDA UYGULANIR, BİRİNDE DEĞİL.
 *
 * Koruma yalnız OpenAI-şekilli gövdede vardı. Gemini yolu aynı eforu
 * `thinking_level` olarak KORUMASIZ gönderiyordu ve orada da düşünme
 * `max_output_tokens`tan yeniyor — yani `document_analysis` 640 token
 * bütçesiyle `high` düşünme istiyordu. Aynı açlık hatası, ikinci bir kapıda.
 *
 * Tek yerde durması, üçüncü bir sağlayıcı eklendiğinde korumanın unutulmasını
 * da engeller.
 */
export function capReasoningEffortForBudget(
  effort: "low" | "medium" | "high",
  maxTokens: number,
  machineJsonRequired: boolean,
): "low" | "medium" | "high" {
  if (effort !== "high") return effort;
  const floor = machineJsonRequired
    ? MACHINE_JSON_HIGH_REASONING_FLOOR
    : FREE_TEXT_HIGH_REASONING_FLOOR;
  return maxTokens < floor ? "medium" : effort;
}

function modelRejectsMachineJsonResponseFormat(model: unknown): boolean {
  return String(model ?? "").toLowerCase().startsWith("qwen/");
}

function modelSupportsJsonSchemaFormat(
  provider: SharedBrainProvider,
  model: unknown,
): boolean {
  if (provider !== "groq") return true;
  const name = String(model ?? "").toLowerCase();
  // gpt-oss'un normal cevaplarda JSON üretmesini kullanıyoruz; reasoning
  // kanalını provider-level json_schema ile kilitlemiyoruz. Kimi K2'nin
  // şema desteği korunur. Bilinmeyen Groq modelleri fail-safe olarak
  // json_object yoluna düşer.
  return name.startsWith("moonshotai/kimi-k2");
}

function withTurnEnvelopeResponseFormat(
  provider: SharedBrainProvider,
  body: Record<string, unknown>,
  proactiveOpsEnabled: boolean,
): Record<string, unknown> {
  if (provider === "gemini" && body.input) {
    const openAiFormat = buildTurnEnvelopeResponseFormat(proactiveOpsEnabled);
    const jsonSchema =
      openAiFormat.json_schema &&
      typeof openAiFormat.json_schema === "object" &&
      !Array.isArray(openAiFormat.json_schema)
        ? (openAiFormat.json_schema as Record<string, unknown>).schema
        : null;
    const systemInstruction = buildTurnEnvelopeSystemInstruction(proactiveOpsEnabled);
    return {
      ...body,
      system_instruction:
        typeof body.system_instruction === "string" && body.system_instruction.trim()
          ? `${body.system_instruction}\n\n${systemInstruction}`
          : systemInstruction,
      ...(jsonSchema
        ? {
            response_format: {
              type: "text",
              mime_type: "application/json",
              schema: jsonSchema,
            },
          }
        : {}),
    };
  }
  const jsonSchemaSupported = modelSupportsJsonSchemaFormat(
    provider,
    body.model,
  );
  const systemInstruction = jsonSchemaSupported
    ? buildTurnEnvelopeSystemInstruction(proactiveOpsEnabled)
    : `${buildTurnEnvelopeSystemInstruction(proactiveOpsEnabled)} ${TURN_ENVELOPE_COMPACT_SCHEMA_INSTRUCTION}`;
  const messages = Array.isArray(body.messages)
    ? (body.messages as SharedBrainConversationMessage[])
    : null;
  return {
    ...body,
    ...(messages
      ? {
          messages: [
            {
              role: "system",
              content: systemInstruction,
            },
            ...messages,
          ],
        }
      : {}),
    response_format: jsonSchemaSupported
      ? buildTurnEnvelopeResponseFormat(proactiveOpsEnabled)
      : { type: "json_object" },
  };
}

export function buildSharedBrainRequestAttempt(input: {
  provider: SharedBrainProvider;
  path: string;
  body: Record<string, unknown>;
  turnEnvelopeEnabled: boolean;
  proactiveOpsEnabled?: boolean;
}): SharedBrainRequestAttempt {
  const turnEnvelopeMode =
    input.turnEnvelopeEnabled &&
    supportsTurnEnvelopeResponseFormat(input.provider, input.path);
  return {
    path: input.path,
    body: turnEnvelopeMode
      ? withTurnEnvelopeResponseFormat(
          input.provider,
          input.body,
          input.proactiveOpsEnabled === true,
        )
      : input.body,
    turnEnvelopeMode,
  };
}
