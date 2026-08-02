import assert from "node:assert/strict";
import test from "node:test";
import {
  normalizeRuntimeCapabilityHandshake,
  normalizeRuntimeCapabilities,
  preflightRequestedRuntimeCapabilities,
  summarizeRuntimeCapabilities,
} from "./capabilities.js";

test("runtime capability summary classifies professional desktop tools", () => {
  const normalized = normalizeRuntimeCapabilities([
    "document_read",
    "document_write",
    "spreadsheet_write",
    "presentation_write",
    "text_analyze",
    "web_research",
    "math_solve",
  ]);

  assert.deepEqual(normalized, [
    "document.read",
    "document.write",
    "spreadsheet.write",
    "presentation.write",
    "text.analyze",
    "web.research",
    "math.solve",
  ]);

  const summary = summarizeRuntimeCapabilities(normalized);
  assert.equal(summary.total, 7);
  assert.equal(summary.categories.document, 6);
  assert.equal(summary.categories.quantum, 1);
  assert.equal(summary.categories.other, 0);
});

test("runtime capability handshake normalizes structured descriptors into readiness states", () => {
  const normalized = normalizeRuntimeCapabilityHandshake({
    capabilities: ["runtime.status"],
    capabilityHandshake: [
      {
        canonicalCapabilityId: "browser_control",
        adapter: "browser.control",
        ready: true,
        dependencyReady: true,
        permissionReady: false,
        aliases: ["browser.control", "tarayıcı"],
        version: "1.2.3",
        inputContractHash: "hash-browser-v1",
      },
    ],
  });

  assert.deepEqual(normalized.capabilities, [
    "runtime.status",
    "browser.control",
    "tarayıcı",
  ]);
  assert.deepEqual(normalized.descriptors[0], {
    canonicalCapabilityId: "browser.control",
    adapter: "browser.control",
    ready: true,
    dependencyReady: true,
    permissionReady: false,
    aliases: ["browser.control", "tarayıcı"],
    version: "1.2.3",
    inputContractHash: "hash-browser-v1",
  });
  assert.deepEqual(normalized.capabilityStates["browser.control"], {
    canonicalCapabilityId: "browser.control",
    adapter: "browser.control",
    ready: true,
    dependencyReady: true,
    permissionReady: false,
    aliases: ["browser.control", "tarayıcı"],
    version: "1.2.3",
    inputContractHash: "hash-browser-v1",
    handshakeContract: "elyan.runtime_capability_handshake.v1",
  });
});

test("runtime capability preflight blocks online capabilities with missing permission", () => {
  const normalized = normalizeRuntimeCapabilityHandshake({
    capabilityHandshake: [
      {
        canonicalCapabilityId: "browser_control",
        adapter: "browser.control",
        ready: true,
        dependencyReady: true,
        permissionReady: false,
        aliases: [],
        version: null,
        inputContractHash: "hash-browser-v1",
      },
    ],
  });

  const preflight = preflightRequestedRuntimeCapabilities({
    availableCapabilities: normalized.capabilities,
    capabilityStates: normalized.capabilityStates,
    requestedCapabilities: ["browser_control"],
  });

  assert.equal(preflight.ok, false);
  assert.deepEqual(preflight.missingCapabilities, []);
  assert.equal(preflight.blockedCapabilities[0]?.name, "browser.control");
  assert.equal(
    preflight.blockedCapabilities[0]?.reason,
    "permission_unavailable",
  );
});
