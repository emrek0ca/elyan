import assert from "node:assert/strict";
import test from "node:test";
import {
  capabilityAllowsSpeechActExecution,
  decideLocalExecution,
} from "./local-execution-decision.js";

// ---------------------------------------------------------------------------
// KANIT UZLAŞMASI. Tek sinyal yetmiyor — ikisi de ölçüldü:
//   yetenek eşleşmesi  korpus %98.1 → tutulan %57.5 (ezber)
//   konuşma eylemi     korpus %96.2 → tutulan %66.7
// Birlikte (eval:local-execution, 38 vaka):
//   korpus  %76.9   tutulan %91.7   YANLIŞ YÜRÜTME 0 / 0
//
// Bu testler ağsız çalışır: e5 yoksa karar `evidence_unavailable` döner ve
// sonuç FAIL-CLOSED olmalıdır. Asıl güvence budur.
// ---------------------------------------------------------------------------

test("without warm semantics the decision fails closed", async () => {
  // Test sürecinde yetenek vektör önbelleği ısınmamıştır.
  const decision = await decideLocalExecution({ message: "Chrome'u kapat" });
  assert.equal(decision.requiresLocalExecution, false);
  assert.equal(decision.reason, "evidence_unavailable");
});

test("an empty message never unlocks execution", async () => {
  for (const message of ["", "   "]) {
    const decision = await decideLocalExecution({ message });
    assert.equal(decision.requiresLocalExecution, false);
    assert.equal(decision.capability, null);
  }
});

test("the decision shape always carries its reason", async () => {
  const decision = await decideLocalExecution({ message: "Chrome nedir" });
  assert.ok(
    [
      "speech_act_and_capability_agree",
      "speech_act_blocks",
      "capability_not_local_action",
      "evidence_unavailable",
    ].includes(decision.reason),
  );
  assert.equal(typeof decision.requiresLocalExecution, "boolean");
});

test("fallback questions require private-local evidence; confirmed desktop routes may use safe observations", () => {
  assert.equal(
    capabilityAllowsSpeechActExecution("question", "directory_tree"),
    true,
  );
  for (const capability of ["desktop_os.processes", "sys_info"]) {
    assert.equal(
      capabilityAllowsSpeechActExecution("question", capability),
      false,
      `${capability} model rotası olmadan fallback yürütmeye açıldı`,
    );
    assert.equal(
      capabilityAllowsSpeechActExecution("question", capability, {
        desktopRouteConfirmed: true,
      }),
      true,
      `${capability} doğrulanmış masaüstü rotasında salt-okumaya açılmadı`,
    );
  }

  for (const capability of ["close_app", "shell_run", "get_weather"]) {
    assert.equal(
      capabilityAllowsSpeechActExecution("question", capability),
      false,
      `${capability} soru biçiminde yanlışlıkla yürütmeye açıldı`,
    );
  }
  assert.equal(
    capabilityAllowsSpeechActExecution("question", "shell_session_open", {
      desktopRouteConfirmed: true,
    }),
    false,
    "soru kalıcı shell oturumu açabildi",
  );
});

test("commands still require a real desktop execution capability", () => {
  assert.equal(capabilityAllowsSpeechActExecution("command", "close_app"), true);
  assert.equal(
    capabilityAllowsSpeechActExecution("command", "directory_tree"),
    true,
  );
  assert.equal(capabilityAllowsSpeechActExecution("command", "get_weather"), false);
  assert.equal(capabilityAllowsSpeechActExecution("command", "sys_info"), false);
  assert.equal(
    capabilityAllowsSpeechActExecution("command", "sys_info", {
      desktopRouteConfirmed: true,
    }),
    true,
  );
  assert.equal(capabilityAllowsSpeechActExecution("statement", "close_app"), false);
  assert.equal(
    capabilityAllowsSpeechActExecution("confirmation", "close_app"),
    false,
  );
  assert.equal(
    capabilityAllowsSpeechActExecution("confirmation", "close_app", {
      desktopRouteConfirmed: true,
    }),
    true,
  );
});
