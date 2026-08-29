import { foldTurkishDiacritics } from "../../lib/text.js";
import type { OutputContract } from "../../core/understanding/output-contract.js";
import type { IntentClassification } from "../../core/understanding/types.js";

export const KNOWLEDGE_NEED_CONTRACT = "elyan.knowledge_need.v2" as const;

export type KnowledgeNeedSource =
  | "none"
  | "conversation"
  | "memory"
  | "provider"
  | "corpus"
  | "web";

export type KnowledgeNeedFallback = "none" | "model" | "web" | "abstain";

export type KnowledgeNeed = {
  contract: typeof KNOWLEDGE_NEED_CONTRACT;
  source: KnowledgeNeedSource;
  freshness: "none" | "stable" | "current";
  evidenceRequired: boolean;
  fallback: KnowledgeNeedFallback;
  query: {
    subject: string | null;
    entities: string[];
    subquestions: string[];
  };
  reason: string;
};

type KnowledgeClassification = Pick<
  IntentClassification,
  "primaryIntent" | "requiresRetrieval" | "requiresCitation" | "reason"
>;

/**
 * KİŞİSEL DURUM İHTİYACI — hafıza katmanının kendi sınıflandırması.
 *
 * `isCurrentUserIdentityQuery` bilerek `^...$` ile çapalıdır: o desen bir
 * İSTEM DİREKTİFİ sürüyor ("kullanıcıyı doğrulanmış hafızadan anlat") ve
 * yanlış pozitifi pahalı. Yönlendirme kararı ise farklı bir soruya cevap
 * verir — "bu turun cevabı kullanıcının KENDİ durumunda mı yatıyor?" —
 * ve orada çapa fazla dardır: "beni nasıl tanıyorsun", "tercihlerimi
 * hatırlıyor musun", "dünkü görevi sürdür" turları hafıza yerine sağlayıcı
 * kısa listesine ve oradan web'e düşüyordu.
 *
 * Üç ayrı ihtiyaç var ve üçü de AYNI katmandan (özel durum) beslenir:
 *   identity      kullanıcının kim olduğu
 *   preference    kullanıcının nasıl çalışmak istediği
 *   continuation  önceki turda/günde bırakılan işin durumu
 *
 * Desenler aksansız yazıma indirgenmiş metne uygulanır; `foldTurkishDiacritics`
 * olmadan "tercihlerimi" yakalanırken "tercihlerimi" yazımının aksansız hâli
 * sessizce kaçıyordu (bkz. `lib/text.ts` başlığı).
 */
export type PersonalStateNeed = "identity" | "preference" | "continuation";

/**
 * Desenler `foldTurkishDiacritics` çıktısına — yani DÜZ ASCII'ye — uygulanır.
 * Bu yüzden burada `ı/ç/ş/ğ/ü/ö` YOKTUR ve olmamalıdır; çift yazım tutmak
 * (`gorev|görev`) tam da `lib/text.ts` başlığındaki bakım tuzağıdır.
 */
const PERSONAL_IDENTITY_PATTERN =
  /(?<!\p{L})(ben kimim|beni (?:ne kadar )?tani|beni nasil tani|benim hakkimda ne|hakkimda ne bil|kim oldugumu bil|who am i|know about me|describe me|do you know me)/iu;

const PERSONAL_PREFERENCE_PATTERN =
  /(?<!\p{L})(tercihim|tercihlerim|ayarlarim|aliskanligim|aliskanliklarim|nasil calis[mt]|benim stilim|benim tarzim|benim dilim|bana nasil hitap|bana hangi dilde|my preference|my settings|how i work|remember about me)/iu;

/**
 * DAR TUTULDU — VE BU BİLİNÇLİ.
 *
 * "devam ettir" gibi bağlam-içi devamlar BİLEREK dışarıda: onların cevabı
 * konuşma bağlamında yatar ve katman 1 zaten oraya bakar. Buraya alınsalardı
 * her ikinci tur hafıza aramasına gider, hafıza boş dönerse de tur çıkmaza
 * girerdi. Burada yalnız KAYITLI durumu adıyla isteyen ifadeler var.
 */
const PERSONAL_CONTINUATION_PATTERN =
  /(?<!\p{L})(dunku (?:gorev|is\b|calisma)|dun (?:baslad|birakt|konustug)|kaldig(?:imiz|in|im) yer|onceki gorevi (?:surdur|devam)|yarim kalan (?:gorev|is\b)|resume (?:the )?task|continue where we left|pending task)/iu;

/**
 * Sıra ÖNEMLİ: "dünkü görev tercihlerim" gibi bir karma istekte bırakılan iş
 * daha dar ve daha bilgilendirici sinyaldir, önce o denenir.
 */
export function classifyPersonalStateNeed(prompt: string): PersonalStateNeed | null {
  const folded = foldTurkishDiacritics(prompt).replace(/\s+/g, " ").trim();
  if (!folded || folded.length > 400) return null;
  if (PERSONAL_CONTINUATION_PATTERN.test(folded)) return "continuation";
  if (PERSONAL_IDENTITY_PATTERN.test(folded)) return "identity";
  if (PERSONAL_PREFERENCE_PATTERN.test(folded)) return "preference";
  return null;
}

export function resolveKnowledgeEvidenceState(input: {
  knowledgeNeed: KnowledgeNeed;
  referenceAvailable: boolean;
  memoryResultCount: number;
  providerEvidenceSufficient: boolean;
  retrievalEvidenceState: "none" | "verified" | "insufficient";
  webEvidenceSufficient: boolean;
}): "none" | "verified" | "insufficient" {
  const sourceSatisfied =
    input.knowledgeNeed.source === "conversation"
      ? input.referenceAvailable
      : input.knowledgeNeed.source === "memory"
        ? input.memoryResultCount > 0
        : input.knowledgeNeed.source === "provider"
          ? input.providerEvidenceSufficient
          : input.knowledgeNeed.source === "corpus"
            ? input.retrievalEvidenceState === "verified"
            : input.knowledgeNeed.source === "web"
              ? input.webEvidenceSufficient
              : true;
  if (input.knowledgeNeed.source === "none") return "none";
  if (sourceSatisfied) return "verified";
  return input.knowledgeNeed.evidenceRequired ? "insufficient" : "none";
}

function compact(value: unknown, max = 500): string {
  const text = typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
  return text.slice(0, max);
}

function unique(values: readonly unknown[], max: number): string[] {
  return [...new Set(values.map((value) => compact(value, 240)).filter(Boolean))].slice(0, max);
}

function result(input: {
  source: KnowledgeNeedSource;
  freshness: KnowledgeNeed["freshness"];
  evidenceRequired: boolean;
  fallback: KnowledgeNeedFallback;
  query: KnowledgeNeed["query"];
  reason: string;
}): KnowledgeNeed {
  return { contract: KNOWLEDGE_NEED_CONTRACT, ...input };
}

export type KnowledgeNeedInput = {
  query: string;
  subject?: string | null;
  entities?: readonly string[];
  subquestions?: readonly string[];
  classification?: KnowledgeClassification | null;
  outputContract?: OutputContract | null;
  referenceAvailable: boolean;
  socialTurn: boolean;
  freshPublicDataRequired: boolean;
  publicWebExplicitlyRequired: boolean;
  attachmentContextUsed: boolean;
  providerAvailable?: boolean;
  corpusAvailable?: boolean;
  multiSourceResearch?: boolean;
  /**
   * ANLAMSAL ARAÇ İPUCU — TİPLİ BİR GEREKSİNİM DEĞİL.
   *
   * `semanticWebToolSelected` bir transformer tahminidir; `skillWebGroundingRequired`
   * ya da istemdeki URL gibi TİPLİ bir sinyalle aynı ağırlıkta değildir.
   * Eskiden ikisi tek bayrakta (`publicWebExplicitlyRequired`) toplanıyordu ve
   * bunun iki ölçülebilir sonucu vardı:
   *
   *   1. "Az önce verdiğin tabloyu özetle" turunda ipucu `web.search` derse
   *      YETKİLİ KONUŞMA REFERANSI atlanıyor ve tur web'e gidiyordu.
   *   2. Tazelik gerekmeyen Elyan sorularında ipucu, korpus/sağlayıcı
   *      katmanlarını atlatıp açık web'i açabiliyordu.
   *
   * İpucu artık yalnız DİĞER HİÇBİR KATMAN CEVAP VEREMİYORSA web'i açar.
   */
  webToolHint?: boolean;
  personalStateNeed?: PersonalStateNeed | null;
  /**
   * Turda YETKİLİ bir yerel referans var (önceki cevap/eser) ve kullanıcı
   * açıkça tazeleme istemedi. `sourceReference` her zaman `previous_answer`
   * olarak derlenmeyebilir; bu bayrak konuşma katmanının ikinci kapısıdır.
   */
  localReferenceAuthoritative?: boolean;
};

/**
 * FAZ 1 — GÖMME MALİYETİ ÖDENMEDEN ÖNCE KARAR.
 *
 * Yönlendirmenin ilk üç katmanı (konuşma, kendi kendine yeterli tur, kişisel
 * durum) hiçbir dış kaynağa bakmadan kapanabilir. Eskiden bu turlar da
 * sorgu gömmesini ve İKİ anlamsal seçiciyi (sağlayıcı + korpus) ödüyordu;
 * ikisi de ONNX işçisine gidiyor ve ilk token'ın önünde duruyordu.
 *
 * `probeTypedSources` false döndüğünde çağıran taraf gömmeyi ve seçicileri
 * hiç başlatmaz. Karar aynı, yol kısa.
 */
export type KnowledgeRoutePlan = {
  settled: KnowledgeNeed | null;
  probeTypedSources: boolean;
  probeCorpus: boolean;
};

function buildQueryShape(input: KnowledgeNeedInput): KnowledgeNeed["query"] {
  const query = compact(input.query);
  return {
    subject: compact(input.subject, 300) || null,
    entities: unique(input.entities ?? [], 8),
    subquestions: unique(input.subquestions?.length ? input.subquestions : [query], 4),
  };
}

/**
 * Katman sırası — kullanıcı isteğinin sırası:
 *   1. konuşma + tipli blok durumu
 *   2. kişisel hafıza (kimlik / tercih / bırakılan iş)
 *   3. tipli sağlayıcı kaydı
 *   4. stabil korpus
 *   5. açık web (yalnız son çare)
 */
function planLocalLayers(input: KnowledgeNeedInput): KnowledgeNeed | null {
  const queryShape = buildQueryShape(input);
  const output = input.outputContract;
  const sourceReference = output?.sourceReference ?? "none";
  const referencedTurn =
    input.referenceAvailable &&
    (sourceReference === "previous_answer" || sourceReference === "latest_artifact");
  // KATMAN 1. Yalnız TİPLİ bir tazelik/web gereksinimi bu katmanı geçebilir;
  // anlamsal araç ipucu geçemez.
  if (referencedTurn && !input.freshPublicDataRequired && !input.publicWebExplicitlyRequired) {
    return result({
      source: "conversation",
      freshness: "none",
      evidenceRequired: true,
      fallback: "abstain",
      query: queryShape,
      reason: "authoritative_conversation_reference",
    });
  }
  if (input.localReferenceAuthoritative && !input.freshPublicDataRequired) {
    return result({
      source: "conversation",
      freshness: "none",
      evidenceRequired: false,
      fallback: "model",
      query: queryShape,
      reason: "local_reference_is_authority",
    });
  }
  if (input.socialTurn || input.attachmentContextUsed) {
    return result({
      source: "none",
      freshness: "none",
      evidenceRequired: false,
      fallback: "model",
      query: queryShape,
      reason: input.socialTurn ? "social_turn" : "attachment_is_authority",
    });
  }
  const selfContainedStructuredInput =
    sourceReference === "current_prompt" &&
    (output?.outputKind === "table" || output?.outputKind === "chart") &&
    !input.freshPublicDataRequired &&
    !input.publicWebExplicitlyRequired;
  if (selfContainedStructuredInput) {
    return result({
      source: "none",
      freshness: "none",
      evidenceRequired: false,
      fallback: "model",
      query: queryShape,
      reason: "self_contained_structured_input",
    });
  }
  // KATMAN 2. Kullanıcının kendi durumu hiçbir koşulda web'den okunamaz;
  // taze veri isteyen bir tur bile burayı açmaz.
  const personalStateNeed =
    input.personalStateNeed ??
    (input.classification?.reason === "user_identity_query" ? "identity" : null) ??
    classifyPersonalStateNeed(input.query);
  if (personalStateNeed) {
    // Kimlik turunda kanıt ZORUNLU: kullanıcıyı tahmin ederek anlatmak
    // (mevcut davranış) kabul edilemez. Tercih ve bırakılan-iş turlarında
    // ise boş hafıza bir çıkmaz değildir — model "kayıtlı bir şey bulamadım"
    // diyebilmelidir; `abstain` orada turu gereksiz yere öldürüyordu.
    const identityTurn = personalStateNeed === "identity";
    return result({
      source: "memory",
      freshness: "stable",
      evidenceRequired: identityTurn,
      fallback: identityTurn ? "abstain" : "model",
      query: queryShape,
      reason:
        personalStateNeed === "identity"
          ? "current_user_memory_required"
          : personalStateNeed === "preference"
            ? "user_preference_memory_required"
            : "prior_task_state_required",
    });
  }
  return null;
}

export function planKnowledgeRoute(input: KnowledgeNeedInput): KnowledgeRoutePlan {
  const settled = planLocalLayers(input);
  if (settled) {
    return { settled, probeTypedSources: false, probeCorpus: false };
  }
  return {
    settled: null,
    probeTypedSources: true,
    // Taze veri isteyen tur stabil korpusla cevaplanamaz; seçiciyi hiç
    // çalıştırmamak hem doğru hem bir ONNX turu daha ucuz.
    probeCorpus: !input.freshPublicDataRequired,
  };
}

export function deriveKnowledgeNeed(input: KnowledgeNeedInput): KnowledgeNeed {
  const settled = planLocalLayers(input);
  if (settled) return settled;
  const queryShape = buildQueryShape(input);
  // KATMAN 3 — tipli sağlayıcı. Genel web aramasından hem hızlı hem doğru.
  if (input.providerAvailable) {
    return result({
      source: "provider",
      freshness: input.freshPublicDataRequired ? "current" : "stable",
      evidenceRequired: true,
      fallback: input.freshPublicDataRequired ? "web" : "abstain",
      query: queryShape,
      reason: "typed_provider_selected",
    });
  }
  // KATMAN 4 — stabil korpus. Ürün/onboarding/destek bilgisi web'e gitmez.
  if (input.corpusAvailable && !input.freshPublicDataRequired) {
    return result({
      source: "corpus",
      freshness: "stable",
      evidenceRequired: false,
      fallback: "model",
      query: queryShape,
      reason: "stable_corpus_selected",
    });
  }
  // KATMAN 5 — açık web, SON ÇARE.
  //
  // İpucu (`webToolHint`) buraya kadar hiçbir katmanı atlatamadı; yalnızca
  // burada, tipli kaynak kalmadığında konuşabilir. Tazelik gerekmiyorsa ve
  // tipli bir istek yoksa web KAPALI kalır — bu, "freshness_required olmayan
  // sorularda web'i tamamen kapat" kuralının tek uygulama noktasıdır.
  if (
    input.freshPublicDataRequired ||
    input.publicWebExplicitlyRequired ||
    input.multiSourceResearch ||
    input.webToolHint === true
  ) {
    return result({
      source: "web",
      freshness: input.freshPublicDataRequired ? "current" : "stable",
      evidenceRequired: true,
      fallback: "abstain",
      query: queryShape,
      reason: input.multiSourceResearch
        ? "multi_source_research_required"
        : input.freshPublicDataRequired || input.publicWebExplicitlyRequired
          ? "public_web_evidence_required"
          : "semantic_web_tool_hint",
    });
  }
  return result({
    source: "none",
    freshness: "none",
    evidenceRequired: false,
    fallback: "model",
    query: queryShape,
    reason: "self_contained_or_model_knowledge",
  });
}
