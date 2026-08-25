/**
 * MCP ARACINI BİRİNCİ SINIF CAPABILITY YAPMAK.
 *
 * NEDEN VAR
 * ---------
 * Bugün keşfedilen her MCP aracı `mcp_call_tool` generic yürütücüsünün altında
 * yaşıyor. O yürütücünün etkisi adında değil argümanında olduğu için — doğru
 * biçimde — hiç önceden yetki alamıyor ve her çağrıda ayrı onay istiyor.
 * Sonuç: MCP altyapısı kurulu ama pratikte kullanılamıyor.
 *
 * Çözüm generic yürütücüyü gevşetmek DEĞİL. Her aracı kendi dar adıyla
 * (`mcp:<sunucu>:<araç>`) tanıtmak: dar ad derlenebilir, dar yetki alabilir,
 * kanıt üretebilir. `mcp_call_tool` yalnız keşfedilmemiş araçlar için geri
 * düşüş olarak kalır.
 *
 * GÜVENLİK SINIRLARI
 * ------------------
 * 1. FAIL-CLOSED SINIFLANDIRMA. `readOnlyHint` yoksa araç salt-okuma
 *    SAYILMAZ. İpucu sunucunun beyanıdır, kanıt değildir; yokluğu "zararsız"
 *    anlamına gelmez.
 * 2. AÇIKLAMA TALİMAT DEĞİLDİR. `description` alanı sunucu sahibinin yazdığı
 *    serbest metindir ve prompt injection yüzeyidir. Burada yalnız VERİ
 *    olarak taşınır: kısaltılır, risk kararına HİÇ girmez.
 * 3. OTOMATİK ETKİNLEŞTİRME YOK. Bu modül tanım üretir; aracın kullanılabilir
 *    olması kullanıcının bağlantıyı onaylamasına bağlıdır.
 * 4. CİHAZ GENELİ CONTROL YOK. Üretilen tanım hiçbir zaman `control` etkisi
 *    ilan etmez; en fazla `write` olur ve kapsamı çağrı anında bağlanır.
 */

import { createHash } from "node:crypto";
import {
  ELEVATED_RISK_ARGUMENT_PATTERN,
  SEPARATE_APPROVAL_CAPABILITY_PATTERN,
} from "../tasks/capability-risk.js";

export const MCP_CAPABILITY_PREFIX = "mcp";

export type ProbedMcpTool = {
  name: string;
  description?: string;
  inputSchemaDigest?: string | null;
  annotations?: {
    readOnlyHint?: boolean;
    destructiveHint?: boolean;
    idempotentHint?: boolean;
    openWorldHint?: boolean;
  } | null;
  inputSchema?: Record<string, unknown> | null;
};

export type McpCapabilityDescriptor = {
  /** `mcp:<sunucu>:<araç>` — registry ve sözleşme bu adı görür. */
  capabilityId: string;
  serverSlug: string;
  toolName: string;
  sideEffectClass: "read" | "write" | "destructive";
  riskClass: "low" | "elevated";
  requiresApproval: boolean;
  /** Yetkinin bağlandığı şema özeti; şema değişirse yetki düşer. */
  inputContractHash: string;
  evidenceMode: "tool_result";
  argSlots: string[];
  /** Yalnız kullanıcıya gösterim için. Karar mantığına GİRMEZ. */
  displayDescription: string | null;
};

const SLUG_PATTERN = /[^a-z0-9]+/gu;

export function mcpServerSlug(serverName: string): string {
  const slug = String(serverName ?? "")
    .toLowerCase()
    .replace(SLUG_PATTERN, "_")
    .replace(/^_+|_+$/gu, "")
    .slice(0, 40);
  return slug || "server";
}

export function mcpCapabilityId(serverName: string, toolName: string): string {
  const tool = String(toolName ?? "")
    .toLowerCase()
    .replace(SLUG_PATTERN, "_")
    .replace(/^_+|_+$/gu, "")
    .slice(0, 60);
  return `${MCP_CAPABILITY_PREFIX}:${mcpServerSlug(serverName)}:${tool || "tool"}`;
}

/** JSON Schema'nın birinci seviye özellik adları — argüman slotları. */
export function mcpArgSlots(schema: Record<string, unknown> | null | undefined): string[] {
  if (!schema || typeof schema !== "object") return [];
  const properties = (schema as Record<string, unknown>).properties;
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) return [];
  return Object.keys(properties as Record<string, unknown>)
    .map((key) => String(key ?? "").trim())
    .filter(Boolean)
    .slice(0, 24);
}

function contractHash(tool: ProbedMcpTool, slots: string[]): string {
  const digest = tool.inputSchemaDigest?.trim();
  if (digest) return digest.slice(0, 64);
  return createHash("sha256")
    .update(`${tool.name}|${[...slots].sort().join(",")}`)
    .digest("hex")
    .slice(0, 64);
}

/**
 * Bir MCP aracını capability tanımına çevirir.
 *
 * Sınıflandırma yalnız YAPISAL sinyallere bakar: araç adı, argüman slot adları
 * ve sunucunun `annotations` ipuçları. Serbest metin açıklaması bilinçli
 * olarak dışarıda tutulur — orada yazan "bu araç güvenlidir" cümlesi bir
 * güvenlik kararı üretmemelidir.
 */
export function describeMcpTool(input: {
  serverName: string;
  tool: ProbedMcpTool;
}): McpCapabilityDescriptor {
  const { tool } = input;
  const capabilityId = mcpCapabilityId(input.serverName, tool.name);
  const argSlots = mcpArgSlots(tool.inputSchema);
  const structuralSignal = `${tool.name} ${argSlots.join(" ")}`;

  const destructive =
    tool.annotations?.destructiveHint === true ||
    SEPARATE_APPROVAL_CAPABILITY_PATTERN.test(structuralSignal);
  // FAIL-CLOSED: ipucu YOKSA salt-okuma sayılmaz.
  const readOnly = tool.annotations?.readOnlyHint === true && !destructive;

  const sideEffectClass: McpCapabilityDescriptor["sideEffectClass"] = destructive
    ? "destructive"
    : readOnly
      ? "read"
      : "write";

  const riskClass: McpCapabilityDescriptor["riskClass"] =
    destructive || ELEVATED_RISK_ARGUMENT_PATTERN.test(structuralSignal)
      ? "elevated"
      : readOnly
        ? "low"
        : "elevated";

  return {
    capabilityId,
    serverSlug: mcpServerSlug(input.serverName),
    toolName: String(tool.name ?? "").slice(0, 120),
    sideEffectClass,
    riskClass,
    // Salt-okuma ve düşük riskli araç dışında her şey onay ister.
    requiresApproval: !(readOnly && riskClass === "low"),
    inputContractHash: contractHash(tool, argSlots),
    evidenceMode: "tool_result",
    argSlots,
    displayDescription:
      typeof tool.description === "string" && tool.description.trim()
        ? tool.description.replace(/\s+/gu, " ").trim().slice(0, 240)
        : null,
  };
}

export function describeMcpTools(input: {
  serverName: string;
  tools: ProbedMcpTool[];
}): McpCapabilityDescriptor[] {
  const seen = new Set<string>();
  const descriptors: McpCapabilityDescriptor[] = [];
  for (const tool of input.tools) {
    if (!tool || typeof tool.name !== "string" || !tool.name.trim()) continue;
    const descriptor = describeMcpTool({ serverName: input.serverName, tool });
    if (seen.has(descriptor.capabilityId)) continue;
    seen.add(descriptor.capabilityId);
    descriptors.push(descriptor);
    if (descriptors.length >= 128) break;
  }
  return descriptors;
}

export function isMcpCapabilityId(capability: string): boolean {
  return String(capability ?? "").startsWith(`${MCP_CAPABILITY_PREFIX}:`);
}
