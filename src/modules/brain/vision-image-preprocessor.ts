import { createHash } from "node:crypto";
import type { EphemeralVisionCarrier } from "./ephemeral-vision.js";
import type { VisionMediaDecision } from "./vision-media-policy.js";

type EphemeralVariant = EphemeralVisionCarrier["images"][number];

export type PreparedVisionVariant = Omit<EphemeralVariant, "base64Data" | "mimeType" | "width" | "height" | "contentHash"> & {
  base64Data: string;
  mimeType: "image/jpeg" | "image/png" | "image/webp";
  width: number;
  height: number;
  contentHash: string;
  qualityScore: number;
  entropy: number;
  sharpness: number;
  enhancedForFineText: boolean;
};

export type VisionPreprocessingResult = {
  variants: PreparedVisionVariant[];
  warnings: string[];
  rejectedCount: number;
  totalEncodedChars: number;
  qualityScore: number;
  enhancedCount: number;
  derivedCropCount: number;
};

const MAX_INPUT_PIXELS = 16_000_000;
const MAX_TOTAL_ENCODED_CHARS = 680_000;
const MIN_RESERVED_ENCODED_CHARS_PER_PHYSICAL_IMAGE = 100_000;

export function calculateVisionVariantEncodedBudget(input: {
  totalEncodedChars: number;
  remainingPhysicalImages: number;
}): number {
  return Math.max(
    0,
    MAX_TOTAL_ENCODED_CHARS - Math.max(0, input.totalEncodedChars) -
      Math.max(0, Math.floor(input.remainingPhysicalImages)) * MIN_RESERVED_ENCODED_CHARS_PER_PHYSICAL_IMAGE,
  );
}

function boundedMetric(value: number, max: number): number {
  return Math.max(0, Math.min(1, value / max));
}

function variantPriority(kind: EphemeralVariant["kind"], strategy: VisionMediaDecision["cropStrategy"]): number {
  const order = strategy === "text_regions"
    ? ["text_crop", "detail_crop", "full_frame"]
    : strategy === "detail_regions"
      ? ["detail_crop", "text_crop", "full_frame"]
      : ["full_frame", "detail_crop", "text_crop"];
  return order.indexOf(kind);
}

export function shouldApplyFineTextEnhancement(input: {
  media: VisionMediaDecision;
  kind: EphemeralVariant["kind"];
  width: number;
  height: number;
}): boolean {
  if (input.media.profile !== "detail" || input.media.cropStrategy !== "text_regions") return false;
  if (input.kind === "detail_crop") return false;
  const shortEdge = Math.min(input.width, input.height);
  const longEdge = Math.max(input.width, input.height);
  if (shortEdge < 256 || longEdge < 512) return false;
  return input.kind === "text_crop" || longEdge >= 768;
}

export function shouldDeriveFineTextCrop(input: {
  media: VisionMediaDecision;
  kind: EphemeralVariant["kind"];
  width: number;
  height: number;
  hasExistingCrop: boolean;
  currentVariantCount: number;
}): boolean {
  if (input.media.profile !== "detail" || input.media.cropStrategy !== "text_regions") return false;
  if (input.kind !== "full_frame" || input.hasExistingCrop) return false;
  if (input.currentVariantCount >= input.media.maxImages) return false;
  return Math.min(input.width, input.height) >= 480 && Math.max(input.width, input.height) >= 720;
}

export async function preprocessVisionVariants(input: {
  variants: EphemeralVariant[];
  media: VisionMediaDecision;
}): Promise<VisionPreprocessingResult> {
  if (input.variants.length === 0 || !input.media.allowCloud) {
    return { variants: [], warnings: [], rejectedCount: 0, totalEncodedChars: 0, qualityScore: 0, enhancedCount: 0, derivedCropCount: 0 };
  }
  const { default: sharp } = await import("sharp");
  const variants = [...input.variants];
  let derivedCropCount = 0;
  for (const sourceVariant of input.variants) {
    if (sourceVariant.kind !== "full_frame") continue;
    const hasExistingCrop = variants.some((candidate) =>
      candidate.imageId === sourceVariant.imageId && candidate.kind !== "full_frame");
    if (
      input.media.profile !== "detail" ||
      input.media.cropStrategy !== "text_regions" ||
      hasExistingCrop ||
      variants.length >= input.media.maxImages
    ) continue;
    try {
      const raw = Buffer.from(sourceVariant.base64Data, "base64");
      if (raw.byteLength < 32 || raw.byteLength > input.media.maxDecodedBytesPerImage) continue;
      const cropSource = sharp(raw, {
        failOn: "warning",
        limitInputPixels: MAX_INPUT_PIXELS,
      });
      const cropMetadata = await cropSource.metadata();
      const sourceWidth = cropMetadata.width ?? 0;
      const sourceHeight = cropMetadata.height ?? 0;
      if (sourceWidth <= 0 || sourceHeight <= 0) continue;
      const swapsAxes = [5, 6, 7, 8].includes(cropMetadata.orientation ?? 1);
      const orientedWidth = swapsAxes ? sourceHeight : sourceWidth;
      const orientedHeight = swapsAxes ? sourceWidth : sourceHeight;
      if (!shouldDeriveFineTextCrop({
        media: input.media,
        kind: sourceVariant.kind,
        width: orientedWidth,
        height: orientedHeight,
        hasExistingCrop,
        currentVariantCount: variants.length,
      })) continue;
      const landscape = orientedWidth >= orientedHeight;
      const xRatio = landscape ? 0.08 : 0.06;
      const yRatio = 0.1;
      const widthRatio = 1 - xRatio * 2;
      const heightRatio = 0.8;
      const left = Math.floor(orientedWidth * xRatio);
      const top = Math.floor(orientedHeight * yRatio);
      const width = Math.max(1, Math.floor(orientedWidth * widthRatio));
      const height = Math.max(1, Math.floor(orientedHeight * heightRatio));
      const crop = await cropSource.clone()
        .rotate()
        .extract({ left, top, width, height })
        .webp({ quality: 88, smartSubsample: true, effort: 4 })
        .toBuffer({ resolveWithObject: true });
      variants.push({
        imageId: sourceVariant.imageId,
        kind: "text_crop",
        mimeType: "image/webp",
        base64Data: crop.data.toString("base64"),
        width: crop.info.width,
        height: crop.info.height,
        box: { x: xRatio, y: yRatio, w: widthRatio, h: heightRatio },
      });
      derivedCropCount += 1;
    } catch {
      // Full-frame processing remains available when optional crop derivation fails.
    }
  }
  const prepared: PreparedVisionVariant[] = [];
  const sourceOrder = new Map<string, number>();
  for (const variant of variants) {
    if (!sourceOrder.has(variant.imageId)) sourceOrder.set(variant.imageId, sourceOrder.size);
  }
  const warnings: string[] = [];
  const seenHashes = new Set<string>();
  const acceptedPhysicalImageIds = new Set<string>();
  let rejectedCount = 0;
  let totalEncodedChars = 0;

  for (const [variantIndex, variant] of variants.entries()) {
    try {
      const raw = Buffer.from(variant.base64Data, "base64");
      if (raw.byteLength < 32 || raw.byteLength > input.media.maxDecodedBytesPerImage) {
        rejectedCount += 1;
        warnings.push("invalid_byte_budget");
        continue;
      }
      const source = sharp(raw, { failOn: "warning", limitInputPixels: MAX_INPUT_PIXELS });
      const metadata = await source.metadata();
      const actualWidth = metadata.width ?? 0;
      const actualHeight = metadata.height ?? 0;
      if (actualWidth <= 0 || actualHeight <= 0) {
        rejectedCount += 1;
        warnings.push("missing_dimensions");
        continue;
      }
      if (
        Math.abs(actualWidth - variant.width) / actualWidth > 0.15 ||
        Math.abs(actualHeight - variant.height) / actualHeight > 0.15
      ) warnings.push("declared_dimension_mismatch");

      const enhancedForFineText = shouldApplyFineTextEnhancement({
        media: input.media,
        kind: variant.kind,
        width: actualWidth,
        height: actualHeight,
      });
      const renderVariant = async (pass: 0 | 1 | 2) => {
        const preferredEdge = input.media.preferredMaxEdge || Math.max(actualWidth, actualHeight);
        const maxEdge = pass === 0 ? preferredEdge : Math.min(preferredEdge, pass === 1 ? 1280 : 960);
        let pipeline = source.clone().rotate().resize({
          width: maxEdge || undefined,
          height: maxEdge || undefined,
          fit: "inside",
          withoutEnlargement: true,
        });
        if (enhancedForFineText) {
          pipeline = pipeline
            .normalize({ lower: 1, upper: 99 })
            .sharpen({ sigma: 0.65 });
        }
        if (pass > 0) {
          return {
            output: await pipeline.webp({
              quality: pass === 1 ? 82 : 72,
              smartSubsample: true,
              effort: 4,
            }).toBuffer({ resolveWithObject: true }),
            mimeType: "image/webp" as const,
          };
        }
        if (variant.mimeType === "image/png" && variant.kind !== "full_frame") {
          return {
            output: await pipeline.png({ compressionLevel: 9, adaptiveFiltering: true }).toBuffer({ resolveWithObject: true }),
            mimeType: "image/png" as const,
          };
        }
        if (variant.mimeType === "image/webp") {
          return {
            output: await pipeline.webp({ quality: 88, smartSubsample: true }).toBuffer({ resolveWithObject: true }),
            mimeType: "image/webp" as const,
          };
        }
        return {
          output: await pipeline.jpeg({ quality: variant.kind === "text_crop" ? 90 : 84, mozjpeg: true }).toBuffer({ resolveWithObject: true }),
          mimeType: "image/jpeg" as const,
        };
      };
      const remainingPhysicalImages = input.media.preserveImageCoverage
        ? new Set(
            variants
              .slice(variantIndex + 1)
              .filter((item) =>
                item.imageId !== variant.imageId &&
                !acceptedPhysicalImageIds.has(item.imageId))
              .map((item) => item.imageId),
          ).size
        : 0;
      const availableEncodedChars = calculateVisionVariantEncodedBudget({
        totalEncodedChars,
        remainingPhysicalImages,
      });
      let rendered = await renderVariant(0);
      let encoded = rendered.output.data.toString("base64");
      for (const pass of [1, 2] as const) {
        if (encoded.length <= availableEncodedChars) break;
        rendered = await renderVariant(pass);
        encoded = rendered.output.data.toString("base64");
        warnings.push("adaptive_compression_applied");
      }
      const { output, mimeType } = rendered;
      const contentHash = createHash("sha256").update(output.data).digest("hex");
      const deduplicationKey = input.media.preserveImageCoverage
        ? `${variant.imageId}:${contentHash}`
        : contentHash;
      if (seenHashes.has(deduplicationKey)) {
        rejectedCount += 1;
        warnings.push("duplicate_pixels");
        continue;
      }
      if (encoded.length > availableEncodedChars || totalEncodedChars + encoded.length > MAX_TOTAL_ENCODED_CHARS) {
        rejectedCount += 1;
        warnings.push("total_budget_exceeded");
        continue;
      }
      const stats = await sharp(output.data, { limitInputPixels: MAX_INPUT_PIXELS }).stats();
      const edgeScore = boundedMetric(Math.max(output.info.width, output.info.height), Math.max(640, input.media.preferredMaxEdge));
      const sharpnessScore = boundedMetric(stats.sharpness, input.media.profile === "detail" ? 4 : 2.5);
      const entropyScore = boundedMetric(stats.entropy, 5);
      const qualityScore = Math.max(0, Math.min(1, edgeScore * 0.45 + sharpnessScore * 0.35 + entropyScore * 0.2));
      if (stats.entropy < 0.08 || Math.max(output.info.width, output.info.height) < 128) {
        rejectedCount += 1;
        warnings.push(stats.entropy < 0.08 ? "near_blank_image" : "insufficient_resolution");
        continue;
      }
      if (stats.entropy < 0.2) warnings.push("near_blank_image");
      if (input.media.profile === "detail" && stats.sharpness < 0.8) warnings.push("low_sharpness");
      seenHashes.add(deduplicationKey);
      acceptedPhysicalImageIds.add(variant.imageId);
      totalEncodedChars += encoded.length;
      prepared.push({
        imageId: variant.imageId,
        kind: variant.kind,
        box: variant.box,
        base64Data: encoded,
        mimeType,
        width: output.info.width,
        height: output.info.height,
        contentHash,
        qualityScore,
        entropy: stats.entropy,
        sharpness: stats.sharpness,
        enhancedForFineText,
      });
    } catch {
      rejectedCount += 1;
      warnings.push("decode_or_processing_failed");
    }
  }

  prepared.sort((a, b) => input.media.preserveImageCoverage
    ? (sourceOrder.get(a.imageId) ?? 0) - (sourceOrder.get(b.imageId) ?? 0) ||
      (a.kind === "full_frame" ? -1 : 0) - (b.kind === "full_frame" ? -1 : 0) ||
      variantPriority(a.kind, input.media.cropStrategy) - variantPriority(b.kind, input.media.cropStrategy) ||
      b.qualityScore - a.qualityScore
    : variantPriority(a.kind, input.media.cropStrategy) - variantPriority(b.kind, input.media.cropStrategy) ||
      b.qualityScore - a.qualityScore,
  );
  const selected = prepared.slice(0, input.media.maxImages);
  const qualityScore = selected.length > 0
    ? selected.reduce((sum, item) => sum + item.qualityScore, 0) / selected.length
    : 0;
  const enhancedCount = selected.filter((item) => item.enhancedForFineText).length;
  return {
    variants: selected,
    warnings: [...new Set(warnings)].slice(0, 12),
    rejectedCount,
    totalEncodedChars,
    qualityScore,
    enhancedCount,
    derivedCropCount,
  };
}

export function buildVisionPreprocessingPromptBlock(result: VisionPreprocessingResult): string | null {
  if (result.variants.length === 0 && result.warnings.length === 0) return null;
  return [
    "Visual input quality (internal):",
    `- accepted=${result.variants.length}; rejected=${result.rejectedCount}; quality=${result.qualityScore.toFixed(2)}`,
    `- fine_text_enhanced=${result.enhancedCount}`,
    `- auto_text_crops=${result.derivedCropCount}`,
    `- warnings=${result.warnings.join(",") || "none"}`,
    result.variants.length === 0
      ? "- no verified image variant is available; do not claim to see the image"
      : "- use only verified variants; if fine detail is still unclear, identify the exact unreadable area instead of guessing",
    "- never expose these diagnostics or internal image processing",
  ].join("\n");
}
