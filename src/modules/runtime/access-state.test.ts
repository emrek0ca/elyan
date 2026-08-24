import assert from "node:assert/strict";
import test from "node:test";
import {
  applyRuntimeAccessAck,
  clearPendingRuntimeAccessCommand,
  emptyRuntimeAccessState,
  readRuntimeAccessState,
  RUNTIME_ACCESS_STATE_KEY,
  stripServerOwnedCapabilityStates,
  withPendingRuntimeAccessCommand,
} from "./access-state.js";

const NOW = new Date("2026-08-24T20:00:00.000Z");

test("an ack for a command the server never issued cannot open access", () => {
  const decision = applyRuntimeAccessAck(emptyRuntimeAccessState(NOW), {
    commandId: "fabricated-command",
    action: "grant_session",
    state: "applied",
    expiresAt: new Date(NOW.getTime() + 3_600_000).toISOString(),
    now: NOW,
  });

  assert.equal(decision.applied, false);
  if (!decision.applied) assert.equal(decision.reason, "no_pending_command");
});

test("a late grant ack cannot reopen access after a revoke was issued", () => {
  const granted = withPendingRuntimeAccessCommand(emptyRuntimeAccessState(NOW), {
    commandId: "grant-1",
    action: "grant_session",
    now: NOW,
  });
  const revoked = withPendingRuntimeAccessCommand(granted.next, {
    commandId: "revoke-1",
    action: "revoke",
    now: new Date(NOW.getTime() + 1_000),
  });

  const stale = applyRuntimeAccessAck(revoked.next, {
    commandId: "grant-1",
    action: "grant_session",
    state: "applied",
    expiresAt: new Date(NOW.getTime() + 3_600_000).toISOString(),
    now: new Date(NOW.getTime() + 2_000),
  });

  assert.equal(stale.applied, false);
  if (!stale.applied) assert.equal(stale.reason, "command_id_mismatch");
});

test("the runtime cannot extend the session beyond the server ceiling", () => {
  const issued = withPendingRuntimeAccessCommand(emptyRuntimeAccessState(NOW), {
    commandId: "grant-1",
    action: "grant_session",
    now: NOW,
  });

  const decision = applyRuntimeAccessAck(issued.next, {
    commandId: "grant-1",
    action: "grant_session",
    state: "applied",
    // Runtime bir haftalık süre iddia ediyor.
    expiresAt: new Date(NOW.getTime() + 7 * 24 * 3_600_000).toISOString(),
    now: NOW,
  });

  assert.equal(decision.applied, true);
  if (decision.applied) {
    assert.equal(decision.next.active, true);
    assert.equal(
      decision.next.expiresAt,
      new Date(NOW.getTime() + 3_600_000).toISOString(),
    );
    assert.equal(decision.next.pending, null);
    assert.equal(decision.next.revision, 1);
  }
});

test("a runtime-reported shorter expiry is honoured", () => {
  const issued = withPendingRuntimeAccessCommand(emptyRuntimeAccessState(NOW), {
    commandId: "grant-1",
    action: "grant_session",
    now: NOW,
  });
  const shorter = new Date(NOW.getTime() + 600_000).toISOString();

  const decision = applyRuntimeAccessAck(issued.next, {
    commandId: "grant-1",
    action: "grant_session",
    state: "applied",
    expiresAt: shorter,
    now: NOW,
  });

  assert.equal(decision.applied, true);
  if (decision.applied) assert.equal(decision.next.expiresAt, shorter);
});

test("an expired stored grant never reads back as active", () => {
  const stored = {
    contract: "elyan.runtime_access_state.v1",
    mode: "session",
    active: true,
    revision: 3,
    commandId: "grant-1",
    action: "grant_session",
    state: "applied",
    expiresAt: new Date(NOW.getTime() - 1_000).toISOString(),
    updatedAt: NOW.toISOString(),
    pending: null,
  };

  const state = readRuntimeAccessState(stored, NOW);

  assert.equal(state.active, false);
  assert.equal(state.mode, "off");
  assert.equal(state.expiresAt, null);
  assert.equal(state.revision, 3);
});

test("the runtime handshake cannot declare its own access state", () => {
  const declared = {
    "sys_info": { ready: true },
    [RUNTIME_ACCESS_STATE_KEY]: { active: true, mode: "session" },
  };

  const filtered = stripServerOwnedCapabilityStates(declared);

  assert.equal(filtered[RUNTIME_ACCESS_STATE_KEY], undefined);
  assert.deepEqual(filtered["sys_info"], { ready: true });
});

test("an undelivered command drops its pending record", () => {
  const issued = withPendingRuntimeAccessCommand(emptyRuntimeAccessState(NOW), {
    commandId: "grant-1",
    action: "grant_session",
    now: NOW,
  });

  const cleared = clearPendingRuntimeAccessCommand(issued.next, "grant-1", NOW);

  assert.equal(cleared.pending, null);
  assert.equal(cleared.active, false);
});
