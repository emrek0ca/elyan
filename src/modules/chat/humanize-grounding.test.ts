import assert from "node:assert/strict";
import test from "node:test";
import {
  sanitizeHumanizedTerminalTaskContent,
  syncChatTaskLifecycle,
} from "./task-sync.js";

test("terminal task finalization preserves the authoritative answer verbatim", () => {
  const authoritativeAnswer =
    "4 e-posta bulundu: PayTR ödeme bildirimi ve ENUYGUN kampanyası.";

  assert.equal(
    sanitizeHumanizedTerminalTaskContent(authoritativeAnswer),
    authoritativeAnswer,
  );
});

test("task lifecycle finalization cannot invoke a second LLM humanizer", () => {
  const implementation = syncChatTaskLifecycle.toString();

  assert.doesNotMatch(implementation, /humanizeTerminalTaskContent/);
  assert.doesNotMatch(implementation, /generateGovernedSharedBrainReply/);
  assert.doesNotMatch(implementation, /task_result_humanize/);
});
