import type { DesktopWorkOrder } from "./desktop-work-order.js";
import { buildDesktopPlanCacheKey } from "./plan-cache.js";

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function isStoredPlanBindingStale(input: {
  workOrder: DesktopWorkOrder;
  allowedCapabilities: string[];
  planPreview: Record<string, unknown>;
}): boolean {
  if (input.planPreview.planSource !== "server_materialized") return false;
  const planCache = asRecord(input.planPreview.planCache);
  const storedKeyHash =
    typeof planCache?.keyHash === "string" ? planCache.keyHash : null;
  const currentKeyHash = buildDesktopPlanCacheKey(
    input.workOrder,
    input.allowedCapabilities,
  ).keyHash;
  return (
    storedKeyHash !== currentKeyHash &&
    (storedKeyHash !== null ||
      input.workOrder.semanticGoal?.contract ===
        "elyan.semantic_task_contract.v1")
  );
}
