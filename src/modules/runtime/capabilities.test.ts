import assert from "node:assert/strict";
import test from "node:test";
import {
  normalizeRuntimeCapabilityHandshake,
  normalizeRuntimeCapabilities,
  preflightRequestedRuntimeCapabilities,
  summarizeRuntimeCapabilities,
  unrunnableRuntimeCapabilityIds,
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

test("koşamayan yetenek ayıklanır, izin bekleyen yetenek KORUNUR", () => {
  // CANLI ARIZA (2026-08-12, görev 8899d79b): planlayıcı `browser_agent.run`
  // seçti, o yetenek hedef cihazda yapısal olarak ölüydü ve dört adımlı görevin
  // tamamı ilk adımda iptal edildi. Cihaz durumu şunu bildiriyordu:
  //
  //   browser_agent.run    ready=false available=FALSE  no_decision_provider
  //   local_files.index    ready=false available=true   permission_required
  //   desktop_operator.run ready=false available=true   (kod yok)
  //
  // İkinci ve üçüncüsü ÇALIŞIR, yalnız izin/onay bekler. `ready`'ye göre
  // ayıklamak onları da katalogdan atıp kullanıcıya izin sorusu hiç sorulmadan
  // ekran operatörünü kaybettirirdi — ölçtüm, tam bu iki tanesi.
  const blocked = unrunnableRuntimeCapabilityIds({
    "browser_agent.run": {
      ready: false,
      available: false,
      errorCode: "no_decision_provider",
    },
    "local_files.index": { ready: false, available: true, errorCode: "permission_required" },
    "desktop_operator.run": { ready: false, available: true, errorCode: "" },
    web_research: { ready: true, available: true, errorCode: "" },
  });

  assert.deepEqual(blocked, [
    { capability: "browser_agent.run", errorCode: "no_decision_provider" },
  ]);
});

test("yetenek durumu hiç gelmezse hiçbir şey ayıklanmaz", () => {
  // Eksik telemetri yüzünden planlamayı imkânsız hâle getirmek, düşebilecek bir
  // adımı denemekten daha kötü.
  assert.deepEqual(unrunnableRuntimeCapabilityIds(null), []);
  assert.deepEqual(unrunnableRuntimeCapabilityIds({}), []);
  assert.deepEqual(unrunnableRuntimeCapabilityIds("bozuk"), []);
  assert.deepEqual(unrunnableRuntimeCapabilityIds({ web_research: { ready: true } }), []);
});
