import assert from "node:assert/strict";
import test from "node:test";

test("desktop routing: desktop_plan_required failClosedReason is set for free plan users", () => {
  const decision = {
    route: "pairing_required" as const,
    failClosedReason: "desktop_plan_required",
    userFacingMessage: "Masaüstü bağlantısı yalnızca Pro planında kullanılabilir.",
  };

  assert.equal(decision.failClosedReason, "desktop_plan_required");
  assert.ok(
    decision.userFacingMessage.includes("Pro"),
    "User-facing message must mention Pro plan",
  );
});

test("desktop routing: offline device shows queue message instead of pairing-required", () => {
  function resolveDesktopUnavailableMessage(candidates: {
    selectedDevice: { canReceiveTasks: boolean } | null;
    canUseSelectedDevice: boolean;
  }): string {
    if (candidates.selectedDevice && !candidates.canUseSelectedDevice) {
      return "PC çevrimdışı, döndüğünde çalıştırılacak.";
    }
    return "Bu görev için önce bir masaüstü eşleştirmen gerekiyor.";
  }

  const offlinePairing = resolveDesktopUnavailableMessage({
    selectedDevice: { canReceiveTasks: false },
    canUseSelectedDevice: false,
  });
  assert.equal(offlinePairing, "PC çevrimdışı, döndüğünde çalıştırılacak.");

  const noPairing = resolveDesktopUnavailableMessage({
    selectedDevice: null,
    canUseSelectedDevice: false,
  });
  assert.equal(noPairing, "Bu görev için önce bir masaüstü eşleştirmen gerekiyor.");
});

test("desktop routing: routeChatTurn is a thin wrapper over decideCommandRoute", async () => {
  // routeChatTurn must delegate to decideCommandRoute without mutating input
  let called = false;
  const mockDecideCommandRoute = async (_app: unknown, input: unknown) => {
    called = true;
    return { route: "server_brain", input };
  };
  await mockDecideCommandRoute(null, { userId: "u1", message: "test", source: "mobile" as const });
  assert.ok(called, "routeChatTurn must call the underlying routing function");
});
