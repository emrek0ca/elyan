/**
 * Turun TÜRETİLMİŞ olguları — her biri tek yerde hesaplanır.
 *
 * NEDEN VAR: "bu tur yan etkili mi?" sorusu kod tabanında yedi yerde
 * soruluyordu ve HER YERDE FARKLI CEVAPLANABİLİYORDU. Ölçüldü:
 *
 *   inference.ts:1230          3 kaynak (onay ‖ gizlilik sınıfı ‖ zarf riski)
 *   inference.ts:6367, :6412   3 kaynak
 *   inference.ts:6251          1 kaynak — yalnız gizlilik sınıfı
 *   desktop-work-order.ts:2927 2 kaynak — onayı hiç saymıyor
 *   desktop-work-order.ts:3020 2 kaynak
 *   task-execution-contract.ts 2 kaynak
 *
 * Sonuç: yalnız `requiresApproval: true` taşıyan bir tur, `inference.ts`'e
 * göre YAN ETKİLİ, `desktop-work-order.ts`'e göre DEĞİL. İki modül aynı tur
 * hakkında farklı şey biliyordu ve hangisinin haklı olduğu, kodu okuyarak
 * anlaşılamıyordu.
 *
 * Bu dosya yeni bir katman değil: dağılmış bir hesabın toplandığı yer.
 * Yeni bir türetilmiş olgu eklenecekse yeri burasıdır — çağıranın içinde
 * tekrar yazılacak yer değil.
 */

type SideEffectSources = {
  /** Yönlendirme kararı — gizlilik sınıfı ve onay gerekliliği buradan gelir. */
  routeDecision?:
    | {
        privacyClass?: string | null;
        requiresApproval?: boolean | null;
      }
    | null
    | undefined;
  /** Anlama zarfı — modelin turu nasıl okuduğu. */
  understandingEnvelope?:
    | { risk?: { side_effect?: boolean | null } | null }
    | null
    | undefined;
};

/**
 * Bu tur dış dünyada bir şey DEĞİŞTİRİYOR mu?
 *
 * Üç kaynağın BİRLEŞİMİ alınır; herhangi biri "evet" diyorsa cevap evettir.
 * Yön kasıtlı olarak temkinlidir: yan etkiyi fazladan işaretlemek turu onay
 * kapısına sokar, eksik işaretlemek ise onay kapısını atlatır. İkisi
 * simetrik hatalar değil.
 *
 * `requiresApproval` bu birleşime DAHİLDİR: bir turun onay istemesi, o turun
 * yan etkili sayılmasının en doğrudan kanıtıdır. Onu dışarıda bırakan iki
 * çağrı yeri bu yüzden düzeltildi.
 */
export function isSideEffectTurn(sources: SideEffectSources): boolean {
  const route = sources.routeDecision;
  if (route?.privacyClass === "side_effect") return true;
  if (route?.requiresApproval === true) return true;
  if (sources.understandingEnvelope?.risk?.side_effect === true) return true;
  return false;
}
