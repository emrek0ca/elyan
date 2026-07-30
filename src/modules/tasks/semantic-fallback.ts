const SEMANTIC_FALLBACK_CAPABILITIES = new Set([
  "web_research",
  "document_read",
  "math_solve",
  "text_analyze",
  "document_write",
  "spreadsheet_write",
  "presentation_write",
  "canvas_write",
]);

export function isSemanticFallbackCapability(capability: string): boolean {
  return SEMANTIC_FALLBACK_CAPABILITIES.has(capability);
}
