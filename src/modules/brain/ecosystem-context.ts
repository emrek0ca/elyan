import {
  DESKTOP_CAPABILITY_MANIFEST,
  type DesktopCapabilityManifestEntry,
} from "../tasks/desktop-capability-manifest.js";

/**
 * Ekosistem farkındalığı bloğu.
 *
 * NEDEN
 * -----
 * Model kendini genel bir sohbet asistanı sanıyordu: Elyan'ın mobil + backend +
 * masaüstü olarak TEK sistem olduğunu, bilgisayarda gerçekten iş yapabildiğini
 * ve elinde hangi araçların bulunduğunu bilmiyordu. Sonuç: kaçamak cevaplar
 * ("bunu yapamam"), yanlış araç seçimi ve yapılan işi anlatmak yerine kendini
 * anlatan robotik metinler.
 *
 * TASARIM
 * -------
 * 1. **Yetenekler manifest'ten türetilir**, elle listelenmez. Elle liste
 *    tutmak sürüklenme (drift) üretir: yeni yetenek eklenince prompt yalan
 *    söylemeye başlar. Tek kaynak `DESKTOP_CAPABILITY_MANIFEST`.
 * 2. **Ton için "samimi ol" DENMEZ.** Böyle talimatlar yapmacıklığı artırır
 *    ("Harika bir soru!"). Onun yerine davranış kısıtı verilir: kısa konuş,
 *    işi yap, kendini anlatma, yapmadığını yaptım deme. İnsan gibi hissettiren
 *    şey sıcak sıfatlar değil, kısalık ve gerçekten iş bitirmektir.
 * 3. Blok **sınırlı** tutulur; prompt bütçesini yemez.
 */

/** Her yetenek ailesinden prompt'a konacak örnek sayısı. */
const PER_FAMILY_SAMPLE = 5;

/** Yetenek adından okunabilir aile etiketi çıkarır (ör. "desktop_operator.run" → "masaüstü kontrolü"). */
function familyOf(name: string): string {
  const value = name.toLowerCase();
  if (value.startsWith("desktop_operator") || value.startsWith("desktop_os")) {
    return "ekran ve pencere kontrolü";
  }
  if (value.startsWith("shell_session") || value === "shell_run") {
    return "terminal";
  }
  if (value.startsWith("file_") || value === "directory_tree" || value === "make_directory") {
    return "dosya sistemi";
  }
  if (value.includes("write") || value.includes("generate") || value.includes("canvas")) {
    return "belge ve görsel üretimi";
  }
  if (value.includes("read") || value.includes("ocr") || value.includes("analyze")) {
    return "okuma ve analiz";
  }
  if (value.includes("calendar") || value.includes("reminder")) {
    return "takvim ve hatırlatıcı";
  }
  if (value.includes("mail") || value.includes("email") || value.includes("whatsapp")) {
    return "mesajlaşma";
  }
  if (value.includes("web") || value.includes("browser") || value.includes("research")) {
    return "web";
  }
  if (value.includes("quantum") || value.includes("math") || value.includes("chart")) {
    return "hesaplama ve modelleme";
  }
  if (value.includes("speech") || value.includes("tts") || value.includes("voice")) {
    return "ses";
  }
  return "diğer";
}

/** Manifest'ten aile → yetenek adları eşlemesi. */
export function summarizeCapabilityFamilies(
  manifest: readonly DesktopCapabilityManifestEntry[] = DESKTOP_CAPABILITY_MANIFEST,
): Map<string, string[]> {
  const families = new Map<string, string[]>();
  for (const entry of manifest) {
    const name = String(entry?.name ?? "").trim();
    if (!name) {
      continue;
    }
    const family = familyOf(name);
    const bucket = families.get(family) ?? [];
    if (bucket.length < 10) {
      bucket.push(name);
    }
    families.set(family, bucket);
  }
  return families;
}

/**
 * Sistem prompt'una eklenecek ekosistem bloğu.
 *
 * `desktopPaired` false ise masaüstü işleri yapılamayacağı DÜRÜSTÇE söylenir —
 * model "yaptım" diyemesin, ama "yapabilirim, cihazı bağla" diyebilsin.
 */
export function buildEcosystemContextBlock(input: {
  /** true: bağlı · false: bağlı değil · null: bilinmiyor (iddia edilmez). */
  desktopPaired: boolean | null;
  manifest?: readonly DesktopCapabilityManifestEntry[];
}): string {
  const families = summarizeCapabilityFamilies(
    input.manifest ?? DESKTOP_CAPABILITY_MANIFEST,
  );
  // Her aileden SABİT sayıda örnek al. Toplam bütçeyi sırayla tüketmek ilk
  // aileleri şişirip sonrakileri tamamen düşürüyordu (terminal ailesi hiç
  // görünmüyordu) — model o yeteneğin varlığından habersiz kalırdı.
  const familyLines: string[] = [];
  for (const [family, names] of families) {
    if (family === "diğer" || names.length === 0) {
      continue;
    }
    const shown = names.slice(0, PER_FAMILY_SAMPLE);
    const suffix = names.length > shown.length ? ", …" : "";
    familyLines.push(`- ${family}: ${shown.join(", ")}${suffix}`);
  }

  // Bilinmiyorsa hiçbir şey iddia edilmez: yanlış bir "bağlı/değil" cümlesi
  // modeli ya yapamayacağı işi vaat etmeye ya da yapabileceğini reddetmeye iter.
  const desktopLine =
    input.desktopPaired === true
      ? "Bu kullanıcının masaüstü cihazı BAĞLI: bilgisayarında iş yapabilirsin."
      : input.desktopPaired === false
        ? "Bu kullanıcının masaüstü cihazı şu an BAĞLI DEĞİL: bilgisayar " +
          "işlerini yapamazsın. Yapabileceğini söyleyebilirsin ama YAPTIĞINI " +
          "söyleyemezsin."
        : "";

  return [
    // NOT: Başlık bilinçli olarak "sen kimsin" DEĞİL. İlk sürüm "SEN KİMSİN —
    // ELYAN:" diye başlıyordu ve model bunu konu sanıp belirsiz sorulara
    // kendini tanıtarak cevap vermeye başladı ("Ben Elyan. ... sistemiyim.").
    // Blok kimlik değil ÇALIŞMA ORTAMI anlatır; kimlik yalnız açıkça
    // sorulduğunda konudur.
    "ÇALIŞMA ORTAMIN:",
    "Mobil uygulama, sunucu ve masaüstü çalışma zamanı tek bir sistemdir. " +
      "Sohbet burada geçer; bilgisayar işleri kullanıcının eşleşmiş " +
      "masaüstünde yürür.",
    ...(desktopLine ? [desktopLine] : []),
    "",
    "ELİNDEKİ YETENEK AİLELERİ (masaüstünde çalışır):",
    ...familyLines,
    "",
    "NASIL DAVRANIRSIN:",
    "- Kısa konuş. Cevabı ver, işi yap. Ne yapacağını duyurma, sonunda özet " +
      "cümlesi ekleme.",
    "- KENDİNİ ANLATMA. Kullanıcı açıkça 'sen kimsin/nesin' diye sormadıkça " +
      "kim olduğundan, neler yapabildiğinden, nasıl çalıştığından BAHSETME. " +
      "Belirsiz bir soruya kendini tanıtarak cevap vermek yanlıştır; ya işi " +
      "yap ya da tek net soru sor.",
    "- Yapabileceğin bir işi 'yapamam' diye geçiştirme; yeteneğin varsa yap.",
    "- YAPMADIĞIN bir şeyi yaptım deme. Aracı çağırmadan 'okudum/gönderdim/" +
      "oluşturdum' demek yasak.",
    "- Kullanıcının kendi verisi gerekiyorsa (dosyası, notu) ve elinde yoksa " +
      "tek net soru sor. Kamuya açık bilgiyi ise sormadan araştır.",
    "- Emin olmadığında tahmini gerçek gibi sunma; neyi bilmediğini söyle.",
  ].join("\n");
}
