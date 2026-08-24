import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const service = readFileSync(
  new URL("./service.ts", import.meta.url).pathname.replace(/\/dist\//, "/src/"),
  "utf8",
);

test("desktop capability refinement happens before work order materialization", () => {
  const refinement = service.indexOf("await refineDesktopCapabilityHints({");
  const workOrder = service.indexOf("const desktopWorkOrderBase =");
  assert.ok(refinement > -1, "capability refinement çağrısı bulunamadı");
  assert.ok(workOrder > -1, "desktop work order çağrısı bulunamadı");
  assert.ok(
    refinement < workOrder,
    "capability listesi work order adımları dondurulduktan sonra değiştiriliyor",
  );
});

test("materialized work order capability scope is not patched afterwards", () => {
  assert.equal(
    service.includes(
      "desktopWorkOrder.requiredCapabilities = await refineDesktopCapabilityHints",
    ),
    false,
    "post-workorder capability patch geri gelmiş",
  );
});

test("embedding refinement cannot expand a structured model capability decision", () => {
  assert.ok(service.includes("allowExpansion: !structuredRouteDecision"));
  assert.ok(
    service.includes("routeDecision.taskRoute?.semanticDecision?.source === \"structured_model\""),
  );
});

test("refinement keeps the route contract immutable and only feeds planner hints", () => {
  assert.equal(service.includes("routeDecision.capabilities ="), false);
  assert.equal(service.includes("routeDecision.taskRoute ="), false);
  assert.ok(service.includes("routeDecision: workOrderRouteDecision"));
  assert.ok(service.includes("requestedCapabilities: plannerCapabilityHints"));
  assert.ok(service.includes("...contractCapabilities"));
  assert.ok(service.includes("!policy.fallbackExecutionEligible"));
});
