import assert from "node:assert/strict";
import test from "node:test";
import { canonicalTaskTitle, shapeTaskFeedItem } from "./service.js";

test("canonicalTaskTitle derives a bounded single-line title from the prompt", () => {
  const title = canonicalTaskTitle({
    title: "   ",
    prompt: "  Çok   satırlı\nve   uzun bir görev başlığı oluştur  ",
  });

  assert.equal(title, "Çok satırlı ve uzun bir görev başlığı oluştur");
});

test("canonicalTaskTitle falls back safely when both title and prompt are empty", () => {
  assert.equal(canonicalTaskTitle({ title: "", prompt: "" }), "Yeni görev");
});

test("shapeTaskFeedItem normalizes legacy blank titles", () => {
  const item = shapeTaskFeedItem({
    id: "task-1",
    title: " ",
    status: "queued",
    targetDeviceId: "desktop-1",
    queuePosition: 1,
    payload: {
      metadata: {
        chat: {
          sessionId: "session-1",
        },
      },
    },
    createdAt: new Date("2030-01-01T00:00:00.000Z"),
    updatedAt: new Date("2030-01-01T00:00:00.000Z"),
  });

  assert.equal(item.title, "Yeni görev");
  assert.equal(item.chatSessionId, "session-1");
});
