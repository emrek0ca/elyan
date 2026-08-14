import assert from "node:assert/strict";
import test from "node:test";
import {
  buildMobileQuickActions,
  MOBILE_QUICK_ACTION_ICONS,
} from "./quick-actions.js";

const baseDevice = {
  type: "desktop",
  canReceiveTasks: false,
  targetStatus: "offline",
  runtime: { isConnected: false },
};

test("mobile quick actions are additive, bounded, and use only supported icons", () => {
  const actions = buildMobileQuickActions([]);

  assert.ok(Array.isArray(actions));
  assert.ok(actions.length <= 6);
  for (const action of actions) {
    assert.deepEqual(Object.keys(action).sort(), [
      "hint",
      "icon",
      "id",
      "label",
      "prompt",
      "route",
    ]);
    assert.ok(MOBILE_QUICK_ACTION_ICONS.includes(action.icon));
    assert.ok(action.label.length <= 32);
    assert.ok(action.hint.length <= 64);
    assert.ok(["auto", "server", "desktop"].includes(action.route));
  }
  assert.equal(actions.some((action) => action.route === "desktop"), false);
});

test("desktop quick action appears only for a connected ready runtime", () => {
  const offline = buildMobileQuickActions([baseDevice]);
  assert.equal(offline.some((action) => action.route === "desktop"), false);

  const connectedButNotReady = buildMobileQuickActions([{
    ...baseDevice,
    canReceiveTasks: true,
    runtime: { isConnected: true },
    targetStatus: "runtime_stale",
  }]);
  assert.equal(
    connectedButNotReady.some((action) => action.route === "desktop"),
    false,
  );

  const ready = buildMobileQuickActions([{
    ...baseDevice,
    canReceiveTasks: true,
    runtime: { isConnected: true },
    targetStatus: "ready",
  }]);
  const desktopAction = ready.find((action) => action.route === "desktop");
  assert.ok(desktopAction);
  assert.equal(desktopAction.id, "search_local_files");
});
