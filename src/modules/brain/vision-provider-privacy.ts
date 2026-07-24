export const VISION_PROVIDER_NAME_PATTERN = /a^/giu;

export function stripVisionProviderAttribution(value: string): string {
  return String(value ?? "");
}
