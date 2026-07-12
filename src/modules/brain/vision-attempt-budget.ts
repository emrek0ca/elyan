export const VISION_TOTAL_PROVIDER_CALL_BUDGET = 2;

export function selectVisionModelAttempts(input: {
  preferredModels: string[];
  providerCount: number;
}): string[] {
  const unique = input.preferredModels.filter((model, index, values) =>
    Boolean(model) && values.indexOf(model) === index);
  return unique.slice(0, input.providerCount > 1 ? 1 : VISION_TOTAL_PROVIDER_CALL_BUDGET);
}

export function canStartVisionProviderCall(callsUsed: number): boolean {
  return Math.max(0, Math.floor(callsUsed)) < VISION_TOTAL_PROVIDER_CALL_BUDGET;
}

export function selectVisionRequestAttempt<T extends { path: string }>(attempts: T[]): T[] {
  const imageCapable = attempts.filter((attempt) => attempt.path !== "/api/generate");
  return (imageCapable.length > 0 ? imageCapable : attempts).slice(0, 1);
}

export function shouldRunVisionSecondaryReview(input: {
  callsUsed: number;
  fallbackUsed: boolean;
}): boolean {
  return !input.fallbackUsed && canStartVisionProviderCall(input.callsUsed);
}
