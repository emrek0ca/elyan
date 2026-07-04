import { estimateTextTokens } from "../billing/token-metering.js";

export function estimateTokens(text: string): number {
  return estimateTextTokens(text);
}
