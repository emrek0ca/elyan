import { getDesktopCapabilityOntology } from "./desktop-capability-ontology.js";
import { trStemPattern } from "../../lib/tr-word-boundary.js";
import path from "node:path";
import {
  DESKTOP_CAPABILITY_MANIFEST,
  type DesktopCapabilityManifestEntry,
} from "./desktop-capability-manifest.js";
import { DESKTOP_SKILL_MANIFEST } from "./desktop-skill-manifest.js";
import type {
  DesktopWorkOrder,
  DesktopWorkOrderStep,
} from "./desktop-work-order.js";

const CAPABILITY_MANIFEST_BY_NAME = new Map(
  DESKTOP_CAPABILITY_MANIFEST.map((entry) => [entry.name, entry] as const),
);
const SKILL_MANIFEST_BY_ID = new Map(
  DESKTOP_SKILL_MANIFEST.map((entry) => [entry.id, entry] as const),
);
const STEP_TEMPLATE_RE = /\{\{\s*steps\.([A-Za-z0-9_-]+)/g;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function templateStepReferences(value: unknown): Set<string> {
  const refs = new Set<string>();
  if (Array.isArray(value)) {
    for (const item of value) {
      for (const ref of templateStepReferences(item)) refs.add(ref);
    }
    return refs;
  }
  const record = asRecord(value);
  if (record) {
    for (const item of Object.values(record)) {
      for (const ref of templateStepReferences(item)) refs.add(ref);
    }
    return refs;
  }
  if (typeof value !== "string" || !value.includes("{{")) return refs;
  for (const match of value.matchAll(STEP_TEMPLATE_RE)) {
    const id = String(match[1] ?? "").trim();
    if (id) refs.add(id);
  }
  return refs;
}

/**
 * DIŞARI MESAJ GÖNDERMEK, İSTENMEDİKÇE YAPILMAZ.
 *
 * CANLI ARIZA (görev 4d1a9de6 ve 18eef3db — "masaüstündeki son raporu bul ve
 * telefonuma gönder"): planlayıcı ikinci adım olarak `send_whatsapp_message`
 * seçti. Kullanıcı WhatsApp'tan HİÇ söz etmemişti; "telefonuma gönder" sonucun
 * kendi uygulamasına dönmesi demekti — ki görev sonucu zaten oraya döner.
 *
 * İki görevde de aynı seçim yapıldı; prompt kuralı eklemek YETMEDİ. Model
 * "gönder" fiilini görünce elindeki tek gönderme aracına uzanıyor.
 *
 * Bu bir yetenek TAHMİNİ meselesi değil, RIZA meselesidir: kullanıcının
 * istemediği bir kişiye/kanala mesaj gitmesi geri alınamaz bir yan etkidir.
 * Bu yüzden kanal açıkça anılmadıkça giden-mesaj yetenekleri yasaklı sayılır.
 *
 * Alıcı adı geçip kanal geçmiyorsa ("Ali'ye gönder") yine yasaklıdır: doğru
 * davranış kanalı TAHMİN etmek değil, sormaktır.
 */
const OUTBOUND_MESSAGING_CAPABILITIES = new Set([
  "send_whatsapp_message",
  "save_whatsapp_contact",
  "email_send",
  // `email_draft` İLK SÜRÜMDE UNUTULMUŞTU — kapı yarım kaldı.
  //
  // Canlı arıza (2026-08-22 23:25, aynı istek): WhatsApp kapatıldıktan sonra
  // planlayıcı bu sefer "Raporu ekleyerek e-posta taslağı oluştur" + "Mail
  // uygulamasını aç" adımlarını kurdu. Kullanıcı yine hiçbir kanal
  // söylememişti. Bir yeteneği kapatıp kardeşini açık bırakmak, kapıyı hiç
  // koymamakla aynı sonucu veriyor.
  "email_draft",
]);

const EXPLICIT_CHANNEL_PATTERN = trStemPattern([
  "whatsapp",
  "wp",
  "mail",
  "e-posta",
  "eposta",
  "posta",
  "sms",
  "telegram",
  "mesaj",
  "ileti",
]);

const EMAIL_ADDRESS_PATTERN = /[\w.+-]+@[\w-]+\.[a-z]{2,}/i;

export function namesExplicitOutboundChannel(goalText: string): boolean {
  const text = String(goalText ?? "");
  if (!text.trim()) return false;
  return EXPLICIT_CHANNEL_PATTERN.test(text) || EMAIL_ADDRESS_PATTERN.test(text);
}

export function buildAllowedCapabilities(
  workOrder: DesktopWorkOrder,
): string[] {
  const required = new Set(
    (Array.isArray(workOrder.requiredCapabilities)
      ? workOrder.requiredCapabilities
      : []
    )
      .map((capability) => String(capability ?? "").trim())
      .filter(Boolean),
  );
  const forbidden = new Set(
    workOrder.semanticGoal?.forbiddenCapabilities ?? [],
  );
  const autonomyAllowed = workOrder.autonomy
    ? new Set(workOrder.autonomy.allowedCapabilities)
    : null;
  const authorization = asRecord(workOrder.capabilityAuthorization);
  const allowPrivateRead = authorization
    ? authorization.allowPrivateRead === true
    : true;
  // `requiredCapabilities` bir İPUCUDUR, beyaz liste DEĞİL.
  //
  // Eskiden planlayıcı YALNIZ bu listedeki yetenekleri kullanabiliyordu. O
  // liste yukarıdaki sezgisel katmanın TAHMİNİ; tahmin yanlışsa görev komple
  // çöküyordu. Canlı kanıt (2026-08-08): "Chrome'u kapat" turunda sezgi
  // "Chrome" kelimesini görüp tarayıcı işi sandı ve
  // `["browser_control","browser_session.goto"]` üretti. Uygulama kapatmak
  // `close_app` ister; o listede olmadığı için planlayıcı geçerli TEK bir adım
  // bile üretemedi, plan `null` döndü ve kullanıcı "güvenilir yürütme planı
  // hazırlanamadı" cevabını aldı.
  //
  // Sistem önce tahmin edip sonra kendini o tahminin içine kilitlememeli:
  // planlayıcı, cihazın güvenli yetenek manifestinden DOĞRU aracı seçebilmeli.
  // Güvenlik daralmaz — yasaklı liste, gözetimsiz çalışma zarfı ve gizlilik
  // kapısı aynen uygulanır; ayrıca her adım masaüstünde kendi izin kapısından
  // ayrıca geçer.
  const preferred = required;
  // Kanal açıkça anılmadıysa giden-mesaj yetenekleri kapalıdır (yukarıdaki not).
  const outboundAllowed = namesExplicitOutboundChannel(
    [
      workOrder.goal?.summary ?? "",
      workOrder.semanticGoal?.objective ?? "",
    ].join(" "),
  );
  const allowed = DESKTOP_CAPABILITY_MANIFEST.filter((entry) => {
    if (forbidden.has(entry.name)) return false;
    if (!outboundAllowed && OUTBOUND_MESSAGING_CAPABILITIES.has(entry.name)) {
      return false;
    }
    if (autonomyAllowed && !autonomyAllowed.has(entry.name)) return false;
    if (
      authorization &&
      !allowPrivateRead &&
      entry.privacyClass.includes("_read")
    ) {
      return false;
    }
    return true;
  }).map((entry) => entry.name);
  // İpucu olarak verilenler başa alınır: planlayıcı önce en olası araçları
  // görür, ama gerektiğinde doğru olanı seçmekte serbesttir.
  return [
    ...allowed.filter((name) => preferred.has(name)),
    ...allowed.filter((name) => !preferred.has(name)),
  ];
}

function hasConcreteArgument(
  args: Record<string, unknown>,
  key: string,
): boolean {
  const value = args[key];
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

function isGroundedPlanPath(value: string): boolean {
  const candidate = value.trim();
  return (
    candidate.includes("{{steps.") ||
    candidate === "workspace" ||
    candidate.startsWith("workspace/") ||
    candidate.startsWith("workspace\\") ||
    candidate.startsWith("~/") ||
    candidate.startsWith("/") ||
    /^[A-Za-z]:[\\/]/.test(candidate) ||
    candidate.startsWith("\\\\")
  );
}

function validateGroundedPaths(
  value: unknown,
  location: string,
  issues: string[],
): void {
  const record = asRecord(value);
  if (!record) return;
  for (const [key, nestedValue] of Object.entries(record)) {
    const nestedLocation = `${location}.${key}`;
    if (
      /path$/i.test(key) &&
      typeof nestedValue === "string" &&
      nestedValue.trim() &&
      !isGroundedPlanPath(nestedValue)
    ) {
      issues.push(
        `${nestedLocation} must use an explicit root such as ~/Desktop, workspace/, an absolute path, or a prior-step reference`,
      );
    }
    if (Array.isArray(nestedValue)) {
      nestedValue.forEach((item, index) =>
        validateGroundedPaths(item, `${nestedLocation}[${index}]`, issues),
      );
    } else {
      validateGroundedPaths(nestedValue, nestedLocation, issues);
    }
  }
}

function enumValuesFor(
  manifest: DesktopCapabilityManifestEntry,
  argument: string,
): string[] | null {
  const properties = asRecord(manifest.inputContract.properties);
  const schema = properties ? asRecord(properties[argument]) : null;
  const values = schema?.enum;
  if (!Array.isArray(values) || values.length === 0) return null;
  return values.map((value) => String(value));
}

/**
 * Kapalı değer kümesi olan argümanlarda uydurulmuş değeri reddeder.
 *
 * Canlıda planlayıcı `browser_control{action:"close_tab"}` üretmişti: böyle
 * bir eylem yok, iş "Geçersiz tarayıcı eylemi." ile ölüyordu. Geçerli
 * değerler yalnız argüman açıklamasının düzyazısında sayıldığı için hiçbir
 * katman bunu yakalayamıyordu.
 *
 * Hata metni geçerli listeyi TAŞIR — replan bunu okuyup kendini düzeltebilsin
 * diye. Reddetmek tek başına yetmez; modele neyin mümkün olduğunu söylemek
 * gerekir.
 */
function validateEnumArguments(
  step: DesktopWorkOrderStep,
  manifest: DesktopCapabilityManifestEntry,
  issues: string[],
): void {
  for (const [argument, rawValue] of Object.entries(step.args ?? {})) {
    if (typeof rawValue !== "string") continue;
    const value = rawValue.trim();
    if (!value) continue;
    const allowed = enumValuesFor(manifest, argument);
    if (!allowed) continue;
    if (allowed.some((candidate) => candidate.toLowerCase() === value.toLowerCase())) {
      continue;
    }
    issues.push(
      `${step.id}: ${step.capability} args.${argument}="${value}" is not a valid value; use one of: ${allowed.join(", ")}`,
    );
  }
}

/**
 * BİR ADIM KALICI ÇIKTI ÜRETEBİLİR Mİ — manifestten türetilir, elle liste yok.
 *
 * `outputContract.primary` "artifact"/"image_artifact" ise ya da
 * `artifactContract.artifactTypes` doluysa o yetenek dosya/artefakt üretir.
 * `desktop_operator.observe_screen` için ikisi de boştur (`primary:
 * "observation"`) — yani ekranı GÖZLEMLER, hiçbir yere KAYDETMEZ.
 */
let sideEffectByCapability: Map<string, string> | null = null;

/** Ontolojinin yan etki sınıfı — tek kaynak, elle liste yok. */
function sideEffectClassForCapability(capability: string): string {
  if (!sideEffectByCapability) {
    sideEffectByCapability = new Map(
      getDesktopCapabilityOntology().map((entry) => [
        entry.canonicalId,
        entry.sideEffectClass,
      ]),
    );
  }
  return sideEffectByCapability.get(capability) ?? "none";
}

function producesPersistentOutput(
  manifest: DesktopCapabilityManifestEntry,
): boolean {
  const output = asRecord(manifest.outputContract);
  const primary = typeof output?.primary === "string" ? output.primary : "";
  if (primary.toLowerCase().includes("artifact")) return true;
  const artifact = asRecord(manifest.artifactContract);
  const types = artifact?.artifactTypes;
  if (Array.isArray(types) && types.length > 0) return true;
  // ARTEFAKT ÜRETMEYEN AMA DURUMU DEĞİŞTİREN YETENEKLER DE SAYILIR.
  //
  // Kendi kapımın yanlış-pozitifi: `make_directory` hiçbir artefakt üretmez
  // ama kullanıcının "klasör oluştur" isteğini TAM OLARAK karşılar. İş emri o
  // turda `file_update: required` beyan ediyor; yalnız artefakt üreticilerini
  // saysaydım DOĞRU planı reddedip gereksiz replan'a sokardım.
  // Yan etki sınıfı (ontoloji) bu ayrımın doğru sahibi.
  const sideEffect = sideEffectClassForCapability(manifest.name);
  return sideEffect === "write" || sideEffect === "destructive";
}

/**
 * SONUÇ KAPSAMI: plan, kullanıcının İSTEDİĞİ her zorunlu çıktıyı üretmeli.
 *
 * Canlı arıza (2026-08-22, görev 3834eb15) "Ekran görüntüsü al ve masaüstüne
 * kaydet": iş emri `expectedOutputs` içinde
 * `{"kind":"file_update","required":true}` BEYAN ETMİŞTİ — yani sistem dosya
 * çıktısı gerektiğini BİLİYORDU. Üretilen plan ise tek adımdı:
 * `desktop_operator.observe_screen`. O yetenek hiçbir dosya üretmez; görev
 * çalıştırıldı ve düştü.
 *
 * Bu, tek bir göreve özgü bir yama değil GENEL bir eksikti: planlayıcı istemi
 * "eksik ÖN KOŞUL olmasın" diyordu ama "istenen her SONUÇ üretilsin"
 * demiyordu. Bileşik istekler ("X yap VE Y'ye kaydet") bu yüzden tek adıma
 * çöküyordu — aynı sınıf "Safariden youtube u aç" turunda da görülmüştü.
 *
 * Mekanik ve dilden bağımsız: iş emrinin kendi beyanı ile manifestin kendi
 * beyanı karşılaştırılır. Hata metni replan'a NE eksik olduğunu söyler.
 *
 * Kapsam dar tutuldu: yalnız kalıcı çıktı (artifact/file_update) denetlenir.
 * `chat_result` cevabın kendisidir; diğer türlerde manifest tarafında net bir
 * sinyal olmadığı için yanlış-pozitif üretmemek adına denetlenmez.
 */
export function validateOutcomeCoverage(
  steps: DesktopWorkOrderStep[],
  expectedOutputs: ReadonlyArray<{ kind?: unknown; required?: unknown }> | undefined,
): string[] {
  if (!Array.isArray(expectedOutputs) || expectedOutputs.length === 0) return [];
  const needsPersistentOutput = expectedOutputs.some((output) => {
    const kind = typeof output?.kind === "string" ? output.kind : "";
    return (
      output?.required === true &&
      (kind === "file_update" || kind === "artifact")
    );
  });
  if (!needsPersistentOutput) return [];

  const covered = steps.some((step) => {
    const manifest = CAPABILITY_MANIFEST_BY_NAME.get(step.capability);
    return manifest ? producesPersistentOutput(manifest) : false;
  });
  if (covered) return [];

  const producers = [...CAPABILITY_MANIFEST_BY_NAME.values()]
    .filter((manifest) => producesPersistentOutput(manifest))
    .map((manifest) => manifest.name)
    .slice(0, 12);
  return [
    "plan: the request requires a saved file/artifact but no step produces one; " +
      `add a step with a capability that writes output, for example: ${producers.join(", ")}`,
  ];
}

export function validateMaterializedPlanContracts(
  steps: DesktopWorkOrderStep[],
): string[] {
  const issues: string[] = [];
  const priorStepIds = new Set<string>();
  for (const step of steps) {
    for (const dependency of step.dependsOn ?? []) {
      if (!priorStepIds.has(dependency)) {
        issues.push(
          `${step.id}: dependsOn must reference an earlier step; invalid dependency id`,
        );
      }
    }
    const manifest = CAPABILITY_MANIFEST_BY_NAME.get(step.capability);
    if (!manifest) {
      issues.push(
        `${step.id}: capability ${step.capability} is not in the desktop manifest`,
      );
      continue;
    }
    for (const requiredArg of manifest.requiredArgs) {
      const hasInlineDocumentText =
        step.capability === "document_read" &&
        requiredArg === "path" &&
        hasConcreteArgument(step.args, "text");
      if (hasInlineDocumentText) continue;
      if (!hasConcreteArgument(step.args, requiredArg)) {
        issues.push(
          `${step.id}: ${step.capability} requires args.${requiredArg}`,
        );
      }
    }
    validateEnumArguments(step, manifest, issues);
    validateGroundedPaths(step.args, `${step.id}: args`, issues);
    if (step.capability === "run_skill") {
      const skillId =
        typeof step.args.skillId === "string" ? step.args.skillId.trim() : "";
      const skill = SKILL_MANIFEST_BY_ID.get(skillId);
      if (!skill) {
        issues.push(
          `${step.id}: run_skill requires an exact args.skillId from the desktop skill manifest`,
        );
        continue;
      }
      const payload = asRecord(step.args.payload);
      if (!payload) {
        issues.push(`${step.id}: run_skill requires args.payload as an object`);
        continue;
      }
      const allowedParameters = new Set(skill.parameters);
      for (const key of Object.keys(payload)) {
        if (!allowedParameters.has(key)) {
          issues.push(
            `${step.id}: skill ${skill.id} does not accept payload.${key}`,
          );
        }
      }
      for (const requiredParameter of skill.requiredParameters) {
        if (!hasConcreteArgument(payload, requiredParameter)) {
          issues.push(
            `${step.id}: skill ${skill.id} requires payload.${requiredParameter}`,
          );
        }
      }
      for (const capability of skill.stepCapabilities) {
        if (!CAPABILITY_MANIFEST_BY_NAME.has(capability)) {
          issues.push(
            `${step.id}: skill ${skill.id} references unknown desktop capability ${capability}`,
          );
        }
      }
    }
    priorStepIds.add(step.id);
  }
  return issues;
}

function effectivePlanCapabilities(
  steps: DesktopWorkOrderStep[],
): Set<string> {
  const capabilities = new Set<string>();
  for (const step of steps) {
    capabilities.add(step.capability);
    if (step.capability !== "run_skill") continue;
    const skillId =
      typeof step.args.skillId === "string" ? step.args.skillId.trim() : "";
    const skill = SKILL_MANIFEST_BY_ID.get(skillId);
    for (const capability of skill?.stepCapabilities ?? []) {
      capabilities.add(capability);
    }
  }
  return capabilities;
}

function collectPlanPaths(
  value: unknown,
  paths: string[] = [],
): string[] {
  const record = asRecord(value);
  if (!record) return paths;
  for (const [key, nested] of Object.entries(record)) {
    const isPathField = /paths?$/iu.test(key);
    if (
      isPathField &&
      typeof nested === "string" &&
      nested.trim() &&
      !nested.includes("{{steps.")
    ) {
      paths.push(nested.trim());
    }
    if (Array.isArray(nested)) {
      for (const item of nested) {
        if (
          isPathField &&
          typeof item === "string" &&
          item.trim() &&
          !item.includes("{{steps.")
        ) {
          paths.push(item.trim());
        } else {
          collectPlanPaths(item, paths);
        }
      }
    } else {
      collectPlanPaths(nested, paths);
    }
  }
  return paths;
}

function pathIsWithinRoot(pathValue: string, rootValue: string): boolean {
  const normalize = (value: string) => {
    const portable = value.trim().replaceAll("\\", "/");
    if (/^[A-Za-z]:\//u.test(portable) || portable.startsWith("//")) {
      return path.win32
        .normalize(portable.replaceAll("/", "\\"))
        .replaceAll("\\", "/")
        .replace(/\/+$/u, "")
        .toLocaleLowerCase("en-US");
    }
    return path.posix.normalize(portable).replace(/\/+$/u, "");
  };
  const candidatePath = normalize(pathValue);
  const root = normalize(rootValue);
  return candidatePath === root || candidatePath.startsWith(`${root}/`);
}

function publicQueryContainsPrivateMaterial(
  query: string,
  workOrder: DesktopWorkOrder,
): boolean {
  if (workOrder.semanticGoal?.risk.localPrivate !== true) return false;
  const value = query.trim();
  if (!value || value.length > 280) return true;
  const approvedQueries = new Set(
    (workOrder.planPreview.steps ?? [])
      .filter((step) => step.capability === "web_research")
      .map((step) =>
        typeof step.args.query === "string"
          ? step.args.query.replace(/\s+/gu, " ").trim()
          : "",
      )
      .filter(Boolean),
  );
  if (!approvedQueries.has(value.replace(/\s+/gu, " ").trim())) return true;
  if (
    /(?:[A-Z]:[\\/]|\\\\|~\/|\/Users\/|\/home\/|workspace[\\/])/u.test(
      value,
    ) ||
    /[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/u.test(value) ||
    /\b[0-9a-f]{8}-[0-9a-f-]{27,}\b/iu.test(value) ||
    /\b\d{7,}\b/u.test(value)
  ) {
    return true;
  }
  const normalizeWords = (text: string) =>
    text
      .toLocaleLowerCase("tr-TR")
      .replace(/[^\p{L}\p{N}]+/gu, " ")
      .trim()
      .split(/\s+/u)
      .filter(Boolean);
  const queryWords = normalizeWords(value);
  if (queryWords.length < 8) return false;
  const goalWords = normalizeWords(
    workOrder.contextPack?.conversationState &&
      typeof workOrder.contextPack.conversationState.currentGoal === "string"
      ? workOrder.contextPack.conversationState.currentGoal
      : workOrder.goal.summary,
  );
  const goalText = ` ${goalWords.join(" ")} `;
  for (let index = 0; index <= queryWords.length - 8; index += 1) {
    const fragment = ` ${queryWords.slice(index, index + 8).join(" ")} `;
    if (goalText.includes(fragment)) return true;
  }
  return false;
}

/**
 * Yetenek adını yazım farklarından bağımsız tek anahtara indirger.
 *
 * Manifest noktalı yazımı kullanır (`desktop_operator.run`); router zinciri
 * ve bazı istemci yolları alt çizgili yazımı üretiyor
 * (`desktop_operator_run`). Küme karşılaştırmaları bunu görmediği sürece
 * hem meşru adımlar reddedilir hem de yasaklı bir yetenek diğer yazımla
 * kapıdan geçebilir.
 */
function capabilityKey(value: string): string {
  return value.trim().toLocaleLowerCase("en-US").replaceAll(".", "_");
}

export function validateMaterializedPlanAgainstWorkOrder(
  steps: DesktopWorkOrderStep[],
  workOrder: DesktopWorkOrder,
): string[] {
  const issues = validateMaterializedPlanContracts(steps);
  const effectiveCapabilities = effectivePlanCapabilities(steps);
  const allowed = new Set(buildAllowedCapabilities(workOrder));
  const forbidden = new Set(
    workOrder.semanticGoal?.forbiddenCapabilities ?? [],
  );
  const autonomyAllowed = workOrder.autonomy
    ? new Set(workOrder.autonomy.allowedCapabilities.map(capabilityKey))
    : null;
  const allowedKeys = new Set([...allowed].map(capabilityKey));
  const forbiddenKeys = new Set([...forbidden].map(capabilityKey));
  for (const capability of effectiveCapabilities) {
    // Aynı yetenek iki yazımla dolaşıyor: manifest `desktop_operator.run`,
    // router zinciri yer yer `desktop_operator_run`. Karşılaştırma bunu
    // görmediği için hem yetkili bir adım "kapsam dışı" sayılabiliyor hem de
    // YASAKLI bir yetenek alt çizgili yazımla kapıdan geçebiliyordu — ikincisi
    // sessiz bir güvenlik boşluğu.
    const key = capabilityKey(capability);
    if (!allowedKeys.has(key)) {
      issues.push(
        `capability ${capability} is outside the semantic authorization scope`,
      );
    }
    if (forbiddenKeys.has(key)) {
      issues.push(`capability ${capability} is forbidden by the semantic goal`);
    }
    if (autonomyAllowed && !autonomyAllowed.has(key)) {
      issues.push(
        `capability ${capability} exceeds the unattended autonomy ceiling`,
      );
    }
  }
  if (workOrder.resourceScope?.contract === "elyan.resource_scope.v1") {
    for (const step of steps) {
      const manifest = CAPABILITY_MANIFEST_BY_NAME.get(step.capability);
      const isWrite =
        manifest?.mutatesPath === true ||
        manifest?.privacyClass.includes("_write") === true ||
        asRecord(manifest?.outputContract)?.primary === "artifact";
      const roots = isWrite
        ? workOrder.resourceScope.writeRoots
        : workOrder.resourceScope.readRoots;
      for (const candidatePath of collectPlanPaths(step.args)) {
        if (!roots.some((root) => pathIsWithinRoot(candidatePath, root))) {
          issues.push(
            `${step.id}: path is outside the authorized WorkOrder resource scope`,
          );
        }
      }
    }
  }
  // `semanticGoal.requiredCapabilities` BİR TAHMİNDİR, plan şartı DEĞİL.
  //
  // Eskiden buradaki döngü, planın bu listedeki her yeteneği birebir
  // içermesini şart koşuyordu. Canlı kanıt (2026-08-10, task 6a7ef5fb):
  // "Chrome u kapat" turunda router isteği `app_control` sanmış, o da
  // `desktop_operator.run`a eşlenmiş. Planlayıcı DOĞRU planı kurdu
  // (`close_app`), ama bu kontrol "iş emri desktop_operator_run istiyordu"
  // deyip planı komple çöpe attı; kullanıcı iki kez üst üste "Görevin
  // güvenilir yürütme planı hazırlanamadı" gördü.
  //
  // Bu, `buildAllowedCapabilities` içinde zaten çözülmüş olan hatanın
  // ikinci kopyasıydı: sistem önce tahmin ediyor, sonra kendini o tahminin
  // içine kilitliyor. Tahmin yanlışsa doğru plan bile geçemiyor.
  //
  // Teslimat garantisi KAYBOLMUYOR; daha sağlam bir yerde duruyor: aşağıdaki
  // `expectedOutputs` kontrolü, kullanıcının BEYAN EDİLEN çıktısına bakar
  // (artifact isteyen bir görev artifact üreten bir adım olmadan geçemez).
  // O kontrol tahmine değil isteğe dayanır. Güvenlik de daralmaz: yasaklı
  // liste, otonomi tavanı, kaynak kapsamı ve gizlilik yukarıda aynen
  // uygulanıyor, ayrıca her adım masaüstünde kendi izin kapısından geçiyor.
  const hasSemanticContract =
    workOrder.semanticGoal?.contract === "elyan.semantic_task_contract.v1";
  const requiresArtifact = workOrder.expectedOutputs.some(
    (output) => output.required && output.kind === "artifact",
  );
  if (
    hasSemanticContract &&
    requiresArtifact &&
    ![...effectiveCapabilities].some((capability) => {
      const manifest = CAPABILITY_MANIFEST_BY_NAME.get(capability);
      return (
        Object.keys(manifest?.artifactContract ?? {}).length > 0 ||
        asRecord(manifest?.outputContract)?.primary === "artifact"
      );
    })
  ) {
    issues.push("required artifact has no artifact-producing capability");
  }
  const stepById = new Map(steps.map((step) => [step.id, step] as const));
  for (const step of steps) {
    if (step.capability !== "web_research") continue;
    const query =
      typeof step.args.query === "string" ? step.args.query.trim() : "";
    if (templateStepReferences(query).size > 0) {
      issues.push(
        `${step.id}: public web query cannot consume prior-step or private context`,
      );
    }
    if (publicQueryContainsPrivateMaterial(query, workOrder)) {
      issues.push(
        `${step.id}: public web query contains unapproved private task material`,
      );
    }
    for (const dependency of step.dependsOn ?? []) {
      const producer = stepById.get(dependency);
      const privacyClass = producer
        ? CAPABILITY_MANIFEST_BY_NAME.get(producer.capability)?.privacyClass
        : null;
      if (privacyClass?.startsWith("local_private")) {
        issues.push(
          `${step.id}: public web query cannot depend on local-private capability output`,
        );
      }
    }
  }
  return [...new Set(issues)];
}
