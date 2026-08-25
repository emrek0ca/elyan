/**
 * ÇIKTI HEDEFİ — "sonuç nereye iner" sorusunun TEK otoritesi.
 *
 * NEDEN VAR
 * ---------
 * Bu karar iki ayrı yerde, iki ayrı biçimde veriliyordu:
 *
 *   1. Sözleşmede üç kez kopyalanmış bir ifade:
 *      `artifactRequired ? (writeRoots.length > 0 ? "desktop" : "artifact") : "chat"`
 *      `writeRoots` neredeyse HER yazma görevinde dolu olduğu için hedef
 *      pratikte daima "desktop" çıkıyordu — masaüstü hiç bağlı olmasa bile.
 *
 *   2. Mobil tarafta `isMobileLocalExportMode`, altı farklı metadata alias'ını
 *      (`mobileDocumentExport`, `mobileLocalExport`, `documentExportReady`,
 *      `documentExportMode`, `outputMode`, `localExportMode`) okuyordu. Yani
 *      "çıktı nereye gidecek" kararını fiilen İSTEMCİ veriyordu.
 *
 * İkisi birlikte iki somut arızayı üretiyordu: masaüstü yokken kullanıcı
 * çıktısız kalıyor ("önce bilgisayar eşle"), ve istemcinin gönderdiği bir
 * bayrak sunucunun teslim kararını değiştirebiliyordu.
 *
 * Karar burada, sunucuda verilir. İstemci alanları yalnız İPUCUDUR.
 */

export type OutputTarget = "chat" | "artifact" | "desktop";

export type OutputTargetInput = {
  /** Bu tur bir dosya/artefakt üretmek zorunda mı? */
  artifactRequired: boolean;
  /** İş emrinin yazma kökleri. Tek başına masaüstü kanıtı DEĞİLDİR. */
  writeRoots?: string[];
  /** Tur gerçekten masaüstü çalışma zamanına mı gidiyor? */
  route?: string | null;
  /**
   * Kullanıcı çıktının YEREL DİSKTE olmasını açıkça istedi mi?
   * (`desired_outputs[].target === "desktop"` ya da "masaüstüne kaydet")
   */
  desktopDeliveryRequested?: boolean;
  /**
   * ADIMLARIN kendi bildirdiği somut yerel yollar.
   *
   * Varsayılan yazma kökleri her yazma görevinde açılır ve bu yüzden niyet
   * kanıtı değildir. Ama bir ADIM `~/Desktop/rapor.docx` yazacağını
   * söylüyorsa, o tur gerçekten yerel teslimdir — kapsam tavanı değil,
   * planın kendisi konuşuyor.
   */
  stepLocalPaths?: string[];
  /** İstemcinin tercih ipucu. Karar DEĞİL, yalnız eşitlik bozucu. */
  clientPreferredTarget?: OutputTarget | null;
};

/**
 * Hedefi çözer.
 *
 * `desktop` üç koşulu BİRDEN ister: artefakt gerekiyor, tur masaüstüne
 * gidiyor, ve kullanıcı yerel teslimi açıkça istedi. Üçü tutmuyorsa çıktı
 * `artifact` olur — sunucu üretir, mobil render eder. Böylece masaüstü yokken
 * kullanıcı elleri boş kalmaz.
 */
export function resolveOutputTarget(input: OutputTargetInput): OutputTarget {
  if (!input.artifactRequired) return "chat";

  const goesToDesktop = input.route === "desktop_runtime";
  const hasWriteScope = (input.writeRoots?.length ?? 0) > 0;
  const planWritesLocally = (input.stepLocalPaths ?? []).length > 0;
  if (
    goesToDesktop &&
    hasWriteScope &&
    (input.desktopDeliveryRequested === true || planWritesLocally)
  ) {
    return "desktop";
  }

  // İstemci ipucu yalnız `artifact` yönünde dinlenir: mobil "bunu bana ver"
  // diyebilir, ama "bunu kullanıcının diskine yaz" DİYEMEZ — yazma kararı
  // yetki üretir ve yetki istemciden gelmez.
  if (input.clientPreferredTarget === "chat" && !input.artifactRequired) return "chat";
  return "artifact";
}

const CLIENT_TARGET_HINT_KEYS = [
  "preferredTarget",
  "documentExportMode",
  "outputMode",
  "localExportMode",
  "documentOutputMode",
] as const;

/**
 * İstemcinin tercih İPUCUNU okur.
 *
 * Eski alias'lar geriye dönük okunur ama hiçbiri "desktop" üretemez:
 * istemci beyanı yazma yetkisine dönüşemez.
 */
export function readClientTargetHint(
  metadata: Record<string, unknown> | undefined,
): OutputTarget | null {
  if (!metadata) return null;
  if (
    metadata.mobileDocumentExport === true ||
    metadata.mobileLocalExport === true ||
    metadata.documentExportReady === true
  ) {
    return "artifact";
  }
  for (const key of CLIENT_TARGET_HINT_KEYS) {
    const raw = metadata[key];
    if (typeof raw !== "string") continue;
    const value = raw.trim().toLowerCase();
    if (!value) continue;
    if (
      value === "mobile_local" ||
      value === "local" ||
      value === "mobile_export" ||
      value === "on_device" ||
      value === "on_device_export" ||
      value === "artifact"
    ) {
      return "artifact";
    }
    if (value === "chat") return "chat";
    // "desktop" bilinçli olarak YOK SAYILIR.
  }
  return null;
}


const HOME_ANCHORED_PATH = /^(?:~\/|\/Users\/|\/home\/|[A-Za-z]:\\)/u;

/**
 * Plan adımlarının bildirdiği somut yerel yolları toplar.
 *
 * `workspace` gibi soyut kökler sayılmaz: onlar kapsam tavanıdır, teslim
 * niyeti değil. Yalnız ev dizinine çapalı gerçek yollar kanıttır.
 */
export function collectStepLocalPaths(workOrder: unknown): string[] {
  const preview = (workOrder as { planPreview?: { steps?: unknown } } | null | undefined)
    ?.planPreview?.steps;
  if (!Array.isArray(preview)) return [];
  const paths: string[] = [];
  for (const value of preview) {
    if (!value || typeof value !== "object") continue;
    const step = value as Record<string, unknown>;
    const scope = Array.isArray(step.resourceScope) ? step.resourceScope : [];
    for (const root of scope) {
      if (typeof root === "string" && HOME_ANCHORED_PATH.test(root)) paths.push(root);
    }
    const args = (step.args ?? {}) as Record<string, unknown>;
    for (const key of ["outputPath", "output_path", "path", "targetPath", "destination"]) {
      const candidate = args[key];
      if (typeof candidate === "string" && HOME_ANCHORED_PATH.test(candidate)) {
        paths.push(candidate);
      }
    }
    if (paths.length >= 16) break;
  }
  return [...new Set(paths)].slice(0, 16);
}
