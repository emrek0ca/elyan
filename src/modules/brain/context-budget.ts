import { estimateTokens } from "./text-metrics.js";

/**
 * Bir turda bağlama giden token'ların kaynak bazında kırılımı.
 *
 * Neden var: "prompt şişti" tek başına bir teşhis değildir. Hangi bloğun
 * büyüdüğünü ve hangisinin karşılığını verdiğini görmeden yapılan her
 * kısaltma tahmindir. Aynı körlüğü sağlayıcı hatalarında yaşadık — hata
 * gövdesi telemetriye taşınana kadar bütün 4xx'ler tek tip görünüyordu,
 * taşınınca kök neden ilk turda çıktı.
 *
 * Ölçüm ucuzdur (yalnız metin uzunluğu); yanlış kısaltma pahalıdır.
 */
export type ContextBudgetBreakdown = {
  /** Kaynak → token. Boş bloklar hiç görünmez. */
  parts: Record<string, number>;
  /** Tüm bağlam bloklarının toplamı. */
  totalTokens: number;
  /** En pahalı kaynak — hangi bloğun budanacağı sorusunun ilk cevabı. */
  largestPart: string | null;
  /** Bu turda gerçekten kullanılan kaynak sayısı. */
  activePartCount: number;
};

export function summarizeContextBudget(
  blocks: Record<string, string | null | undefined>,
): ContextBudgetBreakdown {
  const parts: Record<string, number> = {};
  let totalTokens = 0;
  let largestPart: string | null = null;
  let largestTokens = 0;

  for (const [name, value] of Object.entries(blocks)) {
    const text = typeof value === "string" ? value.trim() : "";
    if (!text) continue;
    const tokens = estimateTokens(text);
    if (tokens <= 0) continue;
    parts[name] = tokens;
    totalTokens += tokens;
    if (tokens > largestTokens) {
      largestTokens = tokens;
      largestPart = name;
    }
  }

  return {
    parts,
    totalTokens,
    largestPart,
    activePartCount: Object.keys(parts).length,
  };
}
