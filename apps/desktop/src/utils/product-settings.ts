import type {
  ProductAutomationLevel,
  ProductPrivacyMode,
  ProductProviderStrategy,
  ProductResponseMode,
  ProductSettings,
  ProductTone,
} from "@/types/domain";

export const defaultProductSettings: ProductSettings = {
  responseMode: "adaptive",
  providerStrategy: "local_first",
  privacyMode: "balanced",
  automationLevel: "assisted",
  tone: "natural",
};

export const responseModeOptions: Array<{ label: string; value: ProductResponseMode }> = [
  { label: "Denge", value: "adaptive" },
  { label: "Kisa", value: "concise" },
  { label: "Detay", value: "detailed" },
];

export const providerStrategyOptions: Array<{ label: string; value: ProductProviderStrategy }> = [
  { label: "Yerel", value: "local_first" },
  { label: "Denge", value: "balanced" },
  { label: "Kanit", value: "verified" },
];

export const privacyModeOptions: Array<{ label: string; value: ProductPrivacyMode }> = [
  { label: "Denge", value: "balanced" },
  { label: "Maks", value: "maximum" },
];

export const automationLevelOptions: Array<{ label: string; value: ProductAutomationLevel }> = [
  { label: "El", value: "manual" },
  { label: "Yardim", value: "assisted" },
  { label: "Oto", value: "operator" },
];

export const toneOptions: Array<{ label: string; value: ProductTone }> = [
  { label: "Dogal", value: "natural" },
  { label: "Sicak", value: "warm" },
  { label: "Resmi", value: "formal" },
];
