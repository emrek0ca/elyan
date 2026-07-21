import assert from "node:assert/strict";
import test from "node:test";
import {
  TERMINAL_CHAT_STREAM_STATUS_RANK,
  chatMessageStatusRank,
  chatStreamEventStatusRank,
  isAssistantMessageTerminallyFenced,
  isTerminalChatMessageStatus,
  isTerminalChatStreamEvent,
  markAssistantMessageTerminal,
  resetAssistantMessageTerminalFenceForTests,
} from "./stream-authority.js";

test("terminal stream events always outrank transient events", () => {
  // Mobil'deki geri dönüş bug'ının sözleşmesi: completed'dan sonra gelen her
  // delta/heartbeat/ACK snapshot'ı daha düşük rank'te olmalı ki yok sayılsın.
  for (const transient of [
    "heartbeat",
    "message.created",
    "message.delta",
    "block.preview",
    "usage.final",
  ]) {
    assert.ok(
      chatStreamEventStatusRank(transient) < TERMINAL_CHAT_STREAM_STATUS_RANK,
      transient,
    );
    assert.equal(isTerminalChatStreamEvent(transient), false, transient);
  }
  for (const terminal of ["message.completed", "message.error"]) {
    assert.equal(
      chatStreamEventStatusRank(terminal),
      TERMINAL_CHAT_STREAM_STATUS_RANK,
      terminal,
    );
    assert.equal(isTerminalChatStreamEvent(terminal), true, terminal);
  }
});

test("unknown stream events rank as transient, never terminal", () => {
  assert.ok(
    chatStreamEventStatusRank("some.future.event") <
      TERMINAL_CHAT_STREAM_STATUS_RANK,
  );
  assert.equal(isTerminalChatStreamEvent("some.future.event"), false);
});

test("chat message status ranks mirror the stream contract", () => {
  for (const status of ["completed", "failed", "canceled"]) {
    assert.equal(
      chatMessageStatusRank(status),
      TERMINAL_CHAT_STREAM_STATUS_RANK,
      status,
    );
    assert.equal(isTerminalChatMessageStatus(status), true, status);
  }
  assert.ok(chatMessageStatusRank("queued") < chatMessageStatusRank("running"));
  assert.ok(
    chatMessageStatusRank("running") <
      chatMessageStatusRank("waiting_approval"),
  );
  assert.equal(isTerminalChatMessageStatus("running"), false);
  assert.equal(isTerminalChatMessageStatus("queued"), false);
});

test("terminal fence blocks volatile publishes only after the final write", () => {
  resetAssistantMessageTerminalFenceForTests();
  assert.equal(isAssistantMessageTerminallyFenced("msg-1"), false);
  markAssistantMessageTerminal("msg-1");
  assert.equal(isAssistantMessageTerminallyFenced("msg-1"), true);
  assert.equal(isAssistantMessageTerminallyFenced("msg-2"), false);
  resetAssistantMessageTerminalFenceForTests();
  assert.equal(isAssistantMessageTerminallyFenced("msg-1"), false);
});

test("terminal fence ignores empty message ids", () => {
  resetAssistantMessageTerminalFenceForTests();
  markAssistantMessageTerminal("");
  assert.equal(isAssistantMessageTerminallyFenced(""), false);
});
