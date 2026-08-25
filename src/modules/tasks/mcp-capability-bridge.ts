/**
 * MCP ARACINI DERLEYİCİYE BAĞLAR.
 *
 * NEDEN VAR
 * ---------
 * `describeMcpTool` her MCP aracını dar bir capability adına çeviriyor
 * (`mcp:<sunucu>:<araç>`) ve yoklama bunu kayda yazıyor. Ama derleyici bu
 * adları TANIMIYORDU: capability manifesti derleme zamanında sabit bir liste
 * ve `mcp:*` adları orada yok. Sonuç, sözleşme doğrulaması onları "bilinmeyen
 * araç" diye düşürüyor ve MCP araçları yine `mcp_call_tool` generic
 * yürütücüsünün altında kalıyordu — yani dar yetki alamıyor, her çağrıda
 * ayrı onay istiyor, pratikte kullanılamıyordu.
 *
 * Bu köprü, yoklamada saklanan araç tanımlarını manifest girdisine çevirir.
 * Kaynak SUNUCUNUN BEYANI değil, backend'in fail-closed sınıflandırmasıdır:
 * `requiresApproval` alanı yoklama anında hesaplanmış ve kayda yazılmıştır.
 *
 * NE YAPMAZ: aracı etkinleştirmez ve yetki üretmez. Yalnız "bu ad geçerli bir
 * capability'dir ve şu etkiye sahiptir" der.
 */

import type { DesktopCapabilityManifestEntry } from "./desktop-capability-manifest.js";
import { isMcpCapabilityId } from "../integrations/mcp-capability.js";

export type StoredMcpToolDescriptor = {
  capabilityId: string;
  toolName?: string;
  sideEffectClass?: string;
  riskClass?: string;
  requiresApproval?: boolean;
  inputContractHash?: string;
  argSlots?: string[];
  description?: string | null;
};

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/**
 * Sunucu kayıtlarındaki yoklama sonuçlarından araç tanımlarını toplar.
 *
 * Yalnız `status === "revoked"` OLMAYAN sunucular sayılır: kullanıcının
 * kapattığı bir sunucunun araçları derleyiciye görünmemeli.
 */
export function collectStoredMcpTools(servers: unknown): StoredMcpToolDescriptor[] {
  if (!Array.isArray(servers)) return [];
  const tools: StoredMcpToolDescriptor[] = [];
  const seen = new Set<string>();
  for (const value of servers) {
    const server = readRecord(value);
    if (!server) continue;
    if (String(server.status ?? "") === "revoked") continue;
    const probe = readRecord(readRecord(server.metadata)?.probe);
    const list = probe?.tools;
    if (!Array.isArray(list)) continue;
    for (const item of list) {
      const tool = readRecord(item);
      if (!tool) continue;
      const capabilityId = typeof tool.capabilityId === "string" ? tool.capabilityId : "";
      if (!capabilityId || !isMcpCapabilityId(capabilityId) || seen.has(capabilityId)) {
        continue;
      }
      seen.add(capabilityId);
      tools.push({
        capabilityId,
        toolName: typeof tool.toolName === "string" ? tool.toolName : undefined,
        sideEffectClass:
          typeof tool.sideEffectClass === "string" ? tool.sideEffectClass : undefined,
        riskClass: typeof tool.riskClass === "string" ? tool.riskClass : undefined,
        requiresApproval: tool.requiresApproval === true,
        inputContractHash:
          typeof tool.inputContractHash === "string" ? tool.inputContractHash : undefined,
        argSlots: Array.isArray(tool.argSlots)
          ? tool.argSlots.filter((slot): slot is string => typeof slot === "string")
          : undefined,
        description: typeof tool.description === "string" ? tool.description : null,
      });
      if (tools.length >= 128) return tools;
    }
  }
  return tools;
}

/**
 * Araç tanımını manifest girdisine çevirir.
 *
 * FAIL-CLOSED: sınıf bilinmiyorsa araç `write` + onay gerektirir sayılır.
 * Bilinmeyen bir aracı salt-okuma saymak, kullanıcının görmediği bir yan
 * etkiye kapı açmaktır.
 */
export function mcpToolManifestEntry(
  tool: StoredMcpToolDescriptor,
): DesktopCapabilityManifestEntry {
  const sideEffectClass: DesktopCapabilityManifestEntry["sideEffectClass"] =
    tool.sideEffectClass === "read"
      ? "read"
      : tool.sideEffectClass === "destructive"
        ? "destructive"
        : "write";
  return {
    name: tool.capabilityId,
    // Onay bilgisi yoklama anında hesaplanmıştır; burada yeniden yorumlanmaz.
    requiresApproval: tool.requiresApproval !== false,
    mutatesPath: false,
    sideEffectClass,
  } as DesktopCapabilityManifestEntry;
}

/**
 * Derleyicinin göreceği MCP capability haritası.
 *
 * `knownCapability` bu haritayı manifestin YANINDA sorar; manifest sabit
 * kalır, MCP araçları tura özgü olarak eklenir.
 */
export function buildMcpCapabilityIndex(
  tools: StoredMcpToolDescriptor[],
): Map<string, DesktopCapabilityManifestEntry> {
  return new Map(tools.map((tool) => [tool.capabilityId, mcpToolManifestEntry(tool)]));
}
