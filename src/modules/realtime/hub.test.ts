import assert from "node:assert/strict";
import test from "node:test";
import WebSocket from "ws";
import { RealtimeHub } from "./hub.js";

type FakeSocket = {
  readyState: number;
  closeCalls: Array<{ code: number; reason: string }>;
  sent: string[];
  close: (code: number, reason: string) => void;
  send: (message: string) => void;
};

function createSocket(readyState = WebSocket.OPEN): FakeSocket {
  return {
    readyState,
    closeCalls: [],
    sent: [],
    close(code: number, reason: string) {
      this.closeCalls.push({ code, reason });
      this.readyState = WebSocket.CLOSED;
    },
    send(message: string) {
      this.sent.push(message);
    },
  };
}

test("RealtimeHub ignores stale detach calls after a runtime replacement", () => {
  const hub = new RealtimeHub();
  const oldSocket = createSocket();
  const newSocket = createSocket();

  hub.attachRuntime({
    socket: oldSocket as never,
    userId: "user-1",
    deviceId: "device-1",
  });
  hub.attachRuntime({
    socket: newSocket as never,
    userId: "user-1",
    deviceId: "device-1",
  });

  assert.deepEqual(oldSocket.closeCalls, [{ code: 4001, reason: "replaced" }]);

  hub.detachRuntime("device-1", oldSocket as never);

  assert.equal(hub.sendToRuntime("device-1", { type: "task.dispatch" }), true);
  assert.equal(newSocket.sent.length, 1);
});

test("RealtimeHub closes and detaches the active runtime socket explicitly", () => {
  const hub = new RealtimeHub();
  const socket = createSocket();

  hub.attachRuntime({
    socket: socket as never,
    userId: "user-1",
    deviceId: "device-1",
  });

  hub.closeRuntime("device-1", 4000, "runtime_disconnect");

  assert.deepEqual(socket.closeCalls, [{ code: 4000, reason: "runtime_disconnect" }]);
  assert.equal(hub.sendToRuntime("device-1", { type: "heartbeat" }), false);
});
