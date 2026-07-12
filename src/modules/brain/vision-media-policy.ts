import type { ClientImageAttachment } from "./document-types.js";
import type { VisionTaskDecision } from "./vision-task-policy.js";

export type VisionMediaProfile = "fast" | "balanced" | "detail" | "restricted";
export type VisionMediaResolution = "low" | "medium" | "high";
export type VisionCropStrategy = "full_frame" | "text_regions" | "detail_regions";

export type VisionMediaDecision = {
  schemaVersion: "elyan.vision_media.v1";
  profile: VisionMediaProfile;
  resolution: VisionMediaResolution;
  cropStrategy: VisionCropStrategy;
  preserveImageCoverage: boolean;
  maxImages: number;
  maxDecodedBytesPerImage: number;
  preferredMaxEdge: number;
  allowCloud: boolean;
  sensitivity: "none" | "personal" | "sensitive" | "restricted";
  reasons: string[];
};

const RESTRICTED_TEXT_PATTERN =
  /(?<!\p{L})(şifre|sifre|parola|password|otp|doğrulama kodu|dogrulama kodu|kredi kartı|kredi karti|cvv|kimlik no|tc kimlik|pasaport\p{L}*|passport|pasaporte|api key|secret key|private key|seed phrase|contraseña|contrasena|código de verificación|codigo de verificacion|tarjeta de crédito|tarjeta de credito|mot de passe|code de vérification|code de verification|carte de crédit|carte de credit|kennwort|passwort|bestätigungscode|bestatigungscode|kreditkarte|passaporto|senha|cartão de crédito|cartao de credito|пароль|код подтверждения|кредитная карта|паспорт|كلمة المرور|رمز التحقق|بطاقة ائتمان|جواز سفر)(?!\p{L})/iu;

const SENSITIVE_TEXT_PATTERN =
  /(?<!\p{L})(sağlık|saglik|teşhis|teshis|reçete|recete|tahlil|banka|hesap no|iban|özel mesaj|ozel mesaj|çocuk fotoğrafı|cocuk fotografi|private message|medical|diagnosis|prescription|bank statement|child photo|photo of a child|underage person|minor child|niño|menor de edad|médico|medico|diagnóstico|diagnostico|bancario|enfant|personne mineure|médical|medical|diagnostic|bancaire|minderjährig|minderjahrig|medizinisch|diagnose|bankauszug|bambino|minorenne|medico|diagnosi|bancario|criança|crianca|menor de idade|médico|medico|diagnóstico|diagnostico|bancário|bancario|ребенок|несовершеннолетний|медицинский|медицинская|диагноз|банковская выписка|банковский|طفل|قاصر|طبي|تشخيص|مصرفي)(?!\p{L})/iu;

const PERSONAL_TEXT_PATTERN =
  /(?<!\p{L})(yüz|yuz|selfie|portre|portrait|face|family photo|aile fotoğrafı|aile fotografi|adres|address|signature|imza|rostro|retrato|familia|dirección|direccion|firma|visage|famille|adresse|gesicht|familie|anschrift|volto|famiglia|indirizzo|rosto|família|familia|endereço|endereco|лицо|семья|адрес|وجه|عائلة|عنوان)(?!\p{L})/iu;

export function calculateVisionVariantBudget(input: {
  imageCount: number;
  fineDetail: boolean;
}): number {
  const physicalImages = Math.max(0, Math.floor(input.imageCount));
  if (physicalImages === 0) return 0;
  const variantsPerImage = input.fineDetail ? 2 : 1;
  return Math.min(4, Math.max(1, physicalImages * variantsPerImage));
}

export function classifyVisionSensitivity(input: {
  prompt: string;
  images: ClientImageAttachment[];
}): "none" | "personal" | "sensitive" | "restricted" {
  const text = [input.prompt, ...input.images.flatMap((image) => [image.fileName, image.ocrText])]
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  if (RESTRICTED_TEXT_PATTERN.test(text)) return "restricted";
  if (SENSITIVE_TEXT_PATTERN.test(text)) return "sensitive";
  if (PERSONAL_TEXT_PATTERN.test(text)) return "personal";
  return input.images.some((image) => image.imageCategory === "screenshot" || image.imageCategory === "document")
    ? "personal"
    : "none";
}

export function decideVisionMediaPolicy(input: {
  task: VisionTaskDecision;
  images: ClientImageAttachment[];
  prompt: string;
  explicitCloudConsent: boolean;
  declaredSensitivity?: "none" | "personal" | "sensitive" | "restricted";
  imageCount?: number;
}): VisionMediaDecision {
  const imageCount = Math.max(0, input.imageCount ?? input.images.length);
  const classifiedSensitivity = classifyVisionSensitivity(input);
  const inferredSensitivity = imageCount > 0 && classifiedSensitivity === "none"
    ? "personal"
    : classifiedSensitivity;
  const sensitivityOrder = ["none", "personal", "sensitive", "restricted"] as const;
  const declaredSensitivity = input.declaredSensitivity ?? "none";
  const sensitivity = sensitivityOrder.indexOf(declaredSensitivity) > sensitivityOrder.indexOf(inferredSensitivity)
    ? declaredSensitivity
    : inferredSensitivity;
  const reasons = [`task:${input.task.primary}`, `sensitivity:${sensitivity}`];
  const preserveImageCoverage = input.task.primary === "visual_comparison" ||
    input.task.secondary.includes("visual_comparison");
  if (!input.explicitCloudConsent || sensitivity === "restricted") {
    reasons.push(input.explicitCloudConsent ? "restricted_data_fail_closed" : "cloud_consent_missing");
    return {
      schemaVersion: "elyan.vision_media.v1",
      profile: "restricted",
      resolution: "low",
      cropStrategy: "full_frame",
      preserveImageCoverage: false,
      maxImages: 0,
      maxDecodedBytesPerImage: 0,
      preferredMaxEdge: 0,
      allowCloud: false,
      sensitivity,
      reasons,
    };
  }

  if (input.task.requiresFineText || input.task.requiresStructuredOutput) {
    reasons.push("fine_detail_required");
    return {
      schemaVersion: "elyan.vision_media.v1",
      profile: "detail",
      resolution: "high",
      cropStrategy: "text_regions",
      preserveImageCoverage,
      maxImages: calculateVisionVariantBudget({ imageCount, fineDetail: true }),
      maxDecodedBytesPerImage: 3 * 1024 * 1024,
      preferredMaxEdge: 2048,
      allowCloud: true,
      sensitivity,
      reasons,
    };
  }

  if (input.task.requiresSpatialReasoning || imageCount > 1) {
    reasons.push("spatial_or_multi_image");
    return {
      schemaVersion: "elyan.vision_media.v1",
      profile: "balanced",
      resolution: "medium",
      cropStrategy: "detail_regions",
      preserveImageCoverage,
      maxImages: calculateVisionVariantBudget({ imageCount, fineDetail: false }),
      maxDecodedBytesPerImage: 2 * 1024 * 1024,
      preferredMaxEdge: 1280,
      allowCloud: true,
      sensitivity,
      reasons,
    };
  }

  reasons.push("simple_visual_question");
  return {
    schemaVersion: "elyan.vision_media.v1",
    profile: "fast",
    resolution: "medium",
    cropStrategy: "full_frame",
    preserveImageCoverage: false,
    maxImages: 1,
    maxDecodedBytesPerImage: 1024 * 1024,
    preferredMaxEdge: 1024,
    allowCloud: true,
    sensitivity,
    reasons,
  };
}

export function selectVisionImages<T extends { documentId: string }>(
  images: T[],
  decision: VisionMediaDecision,
): T[] {
  if (!decision.allowCloud || decision.maxImages <= 0) return [];
  const seen = new Set<string>();
  return images.filter((image) => {
    if (seen.has(image.documentId)) return false;
    seen.add(image.documentId);
    return true;
  }).slice(0, decision.maxImages);
}
