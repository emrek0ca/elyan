import type { DesktopWorkOrder } from "./desktop-work-order.js";
import { buildDesktopPlanCacheKey } from "./plan-cache.js";
import { asRecord } from "../../lib/record.js";

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
