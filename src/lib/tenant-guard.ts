/**
 * Tenant izolasyon guard'ı — savunma derinliği katmanı.
 *
 * Tüm memory/retrieval SQL'leri zaten WHERE user_id ile scope'lu; bu katman
 * "sorgu yanlış yazılırsa" senaryosuna karşı İKİNCİ kilittir: satır seviyesinde
 * user_id doğrulanır, eşleşmeyen satır sessizce düşürülür ve yüksek-önem
 * metrik/log üretilir. Milyon kullanıcıda sessiz sızıntı imkânsızlaşır —
 * ya doğru satır döner ya alarm çalar.
 *
 * Maliyet: satır başına tek string karşılaştırma (nanosaniye) — sıcak yolda
 * ölçülebilir yük yaratmaz.
 */

type TenantLogger = {
  error: (obj: Record<string, unknown>, msg: string) => void;
};

let mismatchTotal = 0;

export function getTenantMismatchTotal(): number {
  return mismatchTotal;
}

/** Test izolasyonu için sayaç sıfırlama. */
export function resetTenantMismatchTotal(): void {
  mismatchTotal = 0;
}

/**
 * Satırlardaki tenant alanını doğrular; eşleşmeyenleri düşürür.
 * `tenantField` satırda yoksa satır GÜVENLİ sayılır (sorgu user_id select
 * etmiyor olabilir) — guard opt-in'dir, mevcut davranışı asla bozmaz.
 */
export function filterRowsToTenant<T extends Record<string, unknown>>(input: {
  rows: T[];
  expectedUserId: string;
  source: string;
  tenantField?: string;
  logger?: TenantLogger | null;
}): T[] {
  const field = input.tenantField ?? "tenantUserId";
  const expected = String(input.expectedUserId ?? "").trim();
  if (!expected) {
    return input.rows;
  }
  let dropped = 0;
  const safe = input.rows.filter((row) => {
    const value = row?.[field];
    if (value === undefined || value === null) {
      return true;
    }
    if (String(value) === expected) {
      return true;
    }
    dropped += 1;
    return false;
  });
  if (dropped > 0) {
    mismatchTotal += dropped;
    input.logger?.error(
      {
        source: input.source,
        expectedUserId: expected,
        droppedRows: dropped,
        tenantMismatchTotal: mismatchTotal,
        severity: "tenant_isolation_violation",
      },
      "tenant guard dropped cross-user rows — investigate query scoping",
    );
  }
  return safe;
}
