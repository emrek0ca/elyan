import {
  DESKTOP_CAPABILITY_MANIFEST,
  type DesktopCapabilityManifestEntry,
} from "../tasks/desktop-capability-manifest.js";
import { serverToolArgsSchema } from "./tool-registry.js";

/**
 * YETENEK KATALOĞUNU MODELE "ARAÇ" OLARAK SUNAN KATMAN.
 *
 * Bugüne kadar 82 yetenek modele yalnız PROMPT METNİ olarak gidiyordu; model
 * aracı SEÇMİYOR, kendisine dayatılan bir plan şemasını doldurmaya çalışıyordu.
 * Bunun iki ölçülmüş bedeli var:
 *
 *   1. Kırılganlık. Plan `response_format: json_schema` ile üretiliyor ve
 *      reasoning kanalı olan modellerde Groq bunu `json_validate_failed` ile
 *      400'lüyor (2026-08-08 yönlendirme, 2026-08-13 görev a4924a76 "PDF yaz").
 *      Yerel araç çağrısında bu hata sınıfı yok: aracı sağlayıcı kendi
 *      mekanizmasıyla seçer.
 *   2. Tek atış. Şema bir turda tek plan ifade eder; paralel araç çağrısı ve
 *      "sonucu gör, devam et" döngüsü kurulamaz.
 *
 * Bu dosya SAF dönüşümdür: manifest → OpenAI/Groq uyumlu tool şeması. Yürütme,
 * onay ve güvenlik kararları burada DEĞİLDİR ve buraya taşınmamalıdır — onay
 * sınırı masaüstündedir, manifest yalnız kelime dağarcığıdır.
 */

export type ChatCompletionTool = {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: {
      type: "object";
      properties: Record<string, unknown>;
      required?: string[];
      additionalProperties: false;
    };
  };
};

/** Araç adları sağlayıcı tarafında `^[a-zA-Z0-9_-]{1,64}$` olmak zorunda. */
export function toolNameForCapability(capability: string): string {
  return capability.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 64);
}

const TOOL_NAME_TO_CAPABILITY = new Map<string, string>(
  DESKTOP_CAPABILITY_MANIFEST.map((entry) => [
    toolNameForCapability(entry.name),
    entry.name,
  ]),
);

/**
 * Modelin döndürdüğü araç adını GERÇEK yetenek adına çevirir.
 *
 * `desktop_operator.locate` → `desktop_operator_locate` dönüşümü tersine
 * çevrilebilir olmalı; aksi halde model doğru aracı seçse bile yürütücü onu
 * bulamaz ve tur sessizce "yetenek yok"a düşer.
 */
export function capabilityForToolName(toolName: string): string | null {
  return TOOL_NAME_TO_CAPABILITY.get(toolName) ?? null;
}

function jsonSchemaType(rawType: unknown): string {
  const normalized = String(rawType ?? "").trim().toUpperCase();
  switch (normalized) {
    case "NUMBER":
    case "INTEGER":
      return "number";
    case "BOOLEAN":
      return "boolean";
    case "ARRAY":
      return "array";
    case "OBJECT":
      return "object";
    default:
      return "string";
  }
}

function toolParameters(
  entry: DesktopCapabilityManifestEntry,
): ChatCompletionTool["function"]["parameters"] {
  const contract = (entry.inputContract ?? {}) as {
    required?: unknown;
    properties?: unknown;
  };
  const rawProperties =
    contract.properties && typeof contract.properties === "object"
      ? (contract.properties as Record<string, Record<string, unknown>>)
      : {};
  const properties: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(rawProperties)) {
    const schema: Record<string, unknown> = {
      type: jsonSchemaType(value?.type),
    };
    if (typeof value?.description === "string" && value.description.trim()) {
      schema.description = value.description.trim().slice(0, 400);
    }
    if (Array.isArray(value?.enum) && value.enum.length > 0) {
      schema.enum = value.enum;
    }
    if (schema.type === "array") {
      schema.items = { type: "string" };
    }
    properties[key] = schema;
  }
  const required = Array.isArray(contract.required)
    ? contract.required.filter(
        (item): item is string =>
          typeof item === "string" && item in properties,
      )
    : [];
  return {
    type: "object",
    properties,
    ...(required.length > 0 ? { required } : {}),
    additionalProperties: false,
  };
}

/**
 * Aracın ne işe yaradığını modele TEK metinde anlatır.
 *
 * `usage` alanı "ne zaman kullan / ne zaman KULLANMA" bilgisini taşıyor ve
 * canlı arızaların önlenmesinde belirleyici oldu (ör. `desktop_operator.locate`
 * bir yol çözücü değildir). Açıklamayı kırpmak o bilgiyi modelden gizler, o
 * yüzden ikisi birleştirilip sağlayıcı sınırına kadar korunur.
 */
function toolDescription(entry: DesktopCapabilityManifestEntry): string {
  const parts = [entry.description, entry.usage].filter(
    (part) => typeof part === "string" && part.trim().length > 0,
  );
  return parts.join(" ").trim().slice(0, 1024);
}

export type ToolCatalogOptions = {
  /** Yalnız bu yetenekler sunulur. Boş/verilmemişse tüm katalog. */
  allowlist?: readonly string[];
  /** Onay gerektiren yetenekler dışarıda bırakılsın mı. */
  excludeApprovalRequired?: boolean;
  /** Sağlayıcıya gönderilecek azami araç sayısı. */
  limit?: number;
};

/**
 * Manifestten sağlayıcıya gönderilebilir araç listesi üretir.
 *
 * Katalog 82 yetenek; hepsini her turda göndermek hem token yakar hem de model
 * dikkatini dağıtır. Çağıran taraf `allowlist` ile daraltır — daraltma kararı
 * SEMANTİK yönlendirmenin işidir, bu dosyanın değil.
 */
export function buildDesktopToolCatalog(
  options: ToolCatalogOptions = {},
): ChatCompletionTool[] {
  const allow =
    options.allowlist && options.allowlist.length > 0
      ? new Set(options.allowlist)
      : null;
  const tools: ChatCompletionTool[] = [];
  for (const entry of DESKTOP_CAPABILITY_MANIFEST) {
    if (allow && !allow.has(entry.name)) continue;
    if (options.excludeApprovalRequired && entry.requiresApproval) continue;
    const description = toolDescription(entry);
    if (!description) continue;
    tools.push({
      type: "function",
      function: {
        name: toolNameForCapability(entry.name),
        description,
        parameters: toolParameters(entry),
      },
    });
    if (options.limit && tools.length >= options.limit) break;
  }
  return tools;
}

export type ParsedToolCall = {
  id: string;
  capability: string;
  args: Record<string, unknown>;
};

/**
 * Sağlayıcı yanıtındaki `tool_calls` dizisini yürütülebilir çağrılara çevirir.
 *
 * Argümanlar sağlayıcıdan STRING olarak gelir ve bozuk JSON olabilir; bozuk
 * çağrı sessizce atlanır, tur ölmez. Tanınmayan araç adı da atlanır: modelin
 * uydurduğu bir yeteneği yürütmeye kalkmak, hiç yürütmemekten tehlikelidir.
 */
export function parseToolCalls(raw: unknown): ParsedToolCall[] {
  if (!Array.isArray(raw)) return [];
  const calls: ParsedToolCall[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const fn = record.function as Record<string, unknown> | undefined;
    const name = typeof fn?.name === "string" ? fn.name : "";
    const capability = capabilityForToolName(name);
    if (!capability) continue;
    let args: Record<string, unknown> = {};
    const rawArgs = fn?.arguments;
    if (typeof rawArgs === "string" && rawArgs.trim()) {
      try {
        const parsed: unknown = JSON.parse(rawArgs);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          args = parsed as Record<string, unknown>;
        }
      } catch {
        continue;
      }
    } else if (rawArgs && typeof rawArgs === "object" && !Array.isArray(rawArgs)) {
      args = rawArgs as Record<string, unknown>;
    }
    calls.push({
      id: typeof record.id === "string" && record.id ? record.id : capability,
      capability,
      args,
    });
  }
  return calls;
}

/* -------------------------------------------------------------------------
 * SUNUCU ARAÇLARI
 *
 * `tool-registry.ts` zaten YÜRÜTÜLEBİLİR araçlar taşıyor: her tanımda zod
 * `argsSchema`, `outputSchema` ve gerçek bir `execute()` var. Eksik olan tek
 * şey bunları modele SAĞLAYICININ araç mekanizmasıyla sunmak — bugüne kadar
 * model bu araçların varlığını yalnız prompt metninden biliyordu ve
 * çağıramıyordu.
 *
 * GÜVENLİK SINIRI: varsayılan olarak yalnız `permission: "read"` araçlar
 * sunulur. Yan etkili/yazan araçlar (bugün 4 tane) mevcut onay yolundan
 * geçmeye devam eder; modele doğrudan verilmeleri, onay kapısını atlatmak
 * anlamına gelirdi.
 * ---------------------------------------------------------------------- */

type ZodLike = {
  _def?: Record<string, unknown>;
  shape?: Record<string, unknown>;
};

/**
 * Zod şemasını JSON Schema'ya çevirir (araç argümanları için gereken alt küme).
 *
 * `zod-to-json-schema` bağımlılığı yok ve tek bir dönüşüm için eklemek
 * istemedik. Kapsam bilinçli olarak dar: object/string/number/boolean/enum/
 * array/optional/default/nullable. Tanınmayan tip `string`e düşer — model yine
 * çağırabilir, argüman doğrulaması zaten yürütme anında zod tarafından yapılır.
 */
function zodToJsonSchema(schema: unknown): Record<string, unknown> {
  const node = schema as ZodLike | undefined;
  const def = node?._def as Record<string, unknown> | undefined;
  const typeName = String(def?.typeName ?? "");

  switch (typeName) {
    case "ZodObject": {
      const shapeSource = def?.shape;
      const shape =
        typeof shapeSource === "function"
          ? (shapeSource as () => Record<string, unknown>)()
          : ((shapeSource ?? {}) as Record<string, unknown>);
      const properties: Record<string, unknown> = {};
      const required: string[] = [];
      for (const [key, value] of Object.entries(shape)) {
        properties[key] = zodToJsonSchema(value);
        const childDef = (value as ZodLike)?._def as
          | Record<string, unknown>
          | undefined;
        const childType = String(childDef?.typeName ?? "");
        if (childType !== "ZodOptional" && childType !== "ZodDefault") {
          required.push(key);
        }
      }
      return {
        type: "object",
        properties,
        ...(required.length > 0 ? { required } : {}),
        additionalProperties: false,
      };
    }
    case "ZodOptional":
    case "ZodNullable":
    case "ZodDefault":
      return zodToJsonSchema(def?.innerType);
    case "ZodArray":
      return { type: "array", items: zodToJsonSchema(def?.type) };
    case "ZodEnum":
      return { type: "string", enum: def?.values ?? [] };
    case "ZodNumber":
      return { type: "number" };
    case "ZodBoolean":
      return { type: "boolean" };
    default:
      return { type: "string" };
  }
}

/**
 * Kayıttaki bir sunucu aracının argüman şemasını JSON Schema olarak verir.
 *
 * Kayıt zod şeması tutuyor; sağlayıcı JSON Schema istiyor. Şema okunamazsa
 * `null` döner ve araç modele hiç sunulmaz — yanlış şemayla sunmak, modelin
 * dolduramayacağı bir aracı katalogda göstermek demektir.
 */
export function serverToolJsonSchema(
  toolName: string,
): ChatCompletionTool["function"]["parameters"] | null {
  const schema = serverToolArgsSchema(toolName);
  if (!schema) return null;
  const converted = zodToJsonSchema(schema);
  if (converted.type !== "object") return null;
  return {
    type: "object",
    properties: (converted.properties ?? {}) as Record<string, unknown>,
    ...(Array.isArray(converted.required) && converted.required.length > 0
      ? { required: converted.required as string[] }
      : {}),
    additionalProperties: false,
  };
}
