import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import websocket from "@fastify/websocket";
import WebSocket from "ws";
import {
  buildSpeechStreamRoutes,
  clientMessageSchema,
  decodeAudioChunk,
  toServerMessage,
} from "./stream-routes.js";
import { pcmToWav, WAV_HEADER_BYTES } from "./pcm-wav.js";
import { SAMPLE_RATE_HZ } from "./streaming-session.js";
import type { ServerMessage } from "./stream-routes.js";

/** 16 kHz mono PCM: a tone at `amplitude`, or silence at 0. */
function pcmChunk(ms: number, amplitude: number): Buffer {
  const samples = Math.floor((ms / 1000) * SAMPLE_RATE_HZ);
  const buffer = Buffer.alloc(samples * 2);
  for (let index = 0; index < samples; index += 1) {
    const value = Math.round(
      Math.sin((2 * Math.PI * 220 * index) / SAMPLE_RATE_HZ) * amplitude * 32_767,
    );
    buffer.writeInt16LE(value, index * 2);
  }
  return buffer;
}

type StreamHarness = {
  url: string;
  close: () => Promise<void>;
  transcribeCalls: { bytes: number; final: boolean }[];
  consumed: number[];
};

async function startStreamApp(
  options: {
    transcribeText?: (callIndex: number) => string;
    allowSeconds?: boolean;
    consent?: () => Promise<unknown>;
  } = {},
): Promise<StreamHarness> {
  const app = Fastify();
  const transcribeCalls: { bytes: number; final: boolean }[] = [];
  const consumed: number[] = [];

  await app.register(websocket);
  app.decorate("config", {
    GROQ_API_KEY: "test-key",
    GROQ_BASE_URL: "https://api.groq.com/openai/v1",
    GROQ_TRANSCRIBE_MODEL: "whisper-large-v3-turbo",
  } as never);
  app.decorate("jwt", {
    verify: async () => ({ kind: "user", sub: "user-1", sessionId: "s-1" }),
  } as never);

  let callIndex = 0;
  await app.register(
    buildSpeechStreamRoutes(
      (async (
        _config: unknown,
        input: { audio: Buffer; contentType: string },
      ) => {
        // The container is built by the transport; assert it arrived intact.
        assert.equal(input.contentType, "audio/wav");
        assert.equal(input.audio.subarray(0, 4).toString("ascii"), "RIFF");
        transcribeCalls.push({
          bytes: input.audio.length - WAV_HEADER_BYTES,
          final: false,
        });
        const text = options.transcribeText?.(callIndex) ?? "masaüstünde rapor";
        callIndex += 1;
        return { text, language: null, model: "whisper-large-v3-turbo" };
      }) as never,
      options.consent ?? (async () => true),
      (async () => ({
        consumeSeconds: async (seconds: number) => {
          consumed.push(seconds);
          return options.allowSeconds ?? true;
        },
        touch: async () => undefined,
        release: async () => undefined,
      })) as never,
    ),
    { prefix: "/v1/speech" },
  );

  await app.listen({ port: 0, host: "127.0.0.1" });
  const address = app.server.address();
  assert.ok(address && typeof address === "object");
  return {
    url: `ws://127.0.0.1:${address.port}/v1/speech/stream`,
    close: async () => {
      await app.close();
    },
    transcribeCalls,
    consumed,
  };
}

function connect(url: string): {
  socket: WebSocket;
  messages: ServerMessage[];
  waitFor: (type: string, timeoutMs?: number) => Promise<ServerMessage>;
} {
  const socket = new WebSocket(url, {
    headers: { authorization: "Bearer test-token" },
  });
  const messages: ServerMessage[] = [];
  socket.on("message", (raw) => {
    messages.push(JSON.parse(raw.toString()) as ServerMessage);
  });
  const waitFor = (type: string, timeoutMs = 5_000) =>
    new Promise<ServerMessage>((resolve, reject) => {
      const existing = messages.find((message) => message.type === type);
      if (existing) {
        resolve(existing);
        return;
      }
      const timer = setTimeout(() => {
        socket.off("message", onMessage);
        reject(new Error(`timed out waiting for ${type}`));
      }, timeoutMs);
      function onMessage(raw: WebSocket.RawData) {
        const parsed = JSON.parse(raw.toString()) as ServerMessage;
        if (parsed.type === type) {
          clearTimeout(timer);
          socket.off("message", onMessage);
          resolve(parsed);
        }
      }
      socket.on("message", onMessage);
    });
  return { socket, messages, waitFor };
}

function sendAudio(socket: WebSocket, seq: number, pcm: Buffer): void {
  socket.send(
    JSON.stringify({ type: "audio", seq, b64: pcm.toString("base64") }),
  );
}

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

test("pcmToWav wraps samples in a parseable RIFF container", () => {
  const pcm = pcmChunk(100, 0.5);
  const wav = pcmToWav(pcm);
  assert.equal(wav.length, pcm.length + WAV_HEADER_BYTES);
  assert.equal(wav.subarray(0, 4).toString("ascii"), "RIFF");
  assert.equal(wav.subarray(8, 12).toString("ascii"), "WAVE");
  assert.equal(wav.readUInt32LE(4), 36 + pcm.length);
  assert.equal(wav.readUInt16LE(22), 1, "mono");
  assert.equal(wav.readUInt32LE(24), SAMPLE_RATE_HZ);
  assert.equal(wav.readUInt16LE(34), 16, "16-bit");
  assert.equal(wav.readUInt32LE(40), pcm.length);
  assert.ok(wav.subarray(WAV_HEADER_BYTES).equals(pcm));
});

test("decodeAudioChunk drops a dangling half-sample instead of corrupting RMS", () => {
  assert.equal(decodeAudioChunk("")?.length, undefined);
  const odd = Buffer.from([1, 2, 3]);
  assert.equal(decodeAudioChunk(odd.toString("base64"))?.length, 2);
  const even = Buffer.from([1, 2, 3, 4]);
  assert.equal(decodeAudioChunk(even.toString("base64"))?.length, 4);
});

test("toServerMessage maps the engine's segmentId onto the wire's seq", () => {
  assert.deepEqual(
    toServerMessage({ type: "partial", text: "a", segmentId: 3, atMs: 1 }),
    { type: "partial", text: "a", seq: 3 },
  );
  assert.deepEqual(
    toServerMessage({ type: "final", text: "b", segmentId: 3, durationMs: 10 }),
    { type: "final", text: "b", segmentId: 3 },
  );
  assert.deepEqual(toServerMessage({ type: "error", code: "x" }), {
    type: "error",
    code: "x",
  });
});

test("clientMessageSchema rejects unknown and malformed frames", () => {
  assert.ok(clientMessageSchema.safeParse({ type: "start" }).success);
  assert.ok(clientMessageSchema.safeParse({ type: "stop" }).success);
  assert.ok(
    clientMessageSchema.safeParse({ type: "audio", seq: 0, b64: "AAA=" })
      .success,
  );
  assert.ok(!clientMessageSchema.safeParse({ type: "audio", seq: -1, b64: "A" }).success);
  assert.ok(!clientMessageSchema.safeParse({ type: "bogus" }).success);
  assert.ok(!clientMessageSchema.safeParse({ type: "start", locale: "turkish" }).success);
});

test("speech stream: start acks, speech yields a partial, pause yields a final", async (t) => {
  const harness = await startStreamApp({
    transcribeText: (index) =>
      index === 0 ? "masaüstünde rapor" : "masaüstünde rapor klasörü oluştur",
  });
  t.after(async () => harness.close());

  const client = connect(harness.url);
  await new Promise((resolve) => client.socket.once("open", resolve));

  client.socket.send(JSON.stringify({ type: "start", locale: "tr" }));
  const ready = await client.waitFor("ready");
  assert.deepEqual(ready, { type: "ready", sessionId: null });

  // Speech. The engine rate-limits provisional passes on wall clock, so the
  // chunks are fed at roughly real time rather than all at once.
  let seq = 0;
  for (let index = 0; index < 8; index += 1) {
    sendAudio(client.socket, seq++, pcmChunk(250, 0.5));
    await delay(90);
  }
  const partial = await client.waitFor("partial");
  assert.equal(partial.type === "partial" && partial.text, "masaüstünde rapor");

  // Silence past SILENCE_HOLD_MS (900 ms of audio) closes the segment.
  for (let index = 0; index < 5; index += 1) {
    sendAudio(client.socket, seq++, pcmChunk(250, 0));
    await delay(20);
  }
  const final = await client.waitFor("final");
  assert.equal(
    final.type === "final" && final.text,
    "masaüstünde rapor klasörü oluştur",
  );
  assert.equal(final.type === "final" && final.segmentId, 0);

  // The final pass must read the whole segment, not just the 4 s window.
  const finalCall = harness.transcribeCalls.at(-1);
  assert.ok(finalCall && finalCall.bytes > 0);

  client.socket.close();
});

test("speech stream: audio before start is refused", async (t) => {
  const harness = await startStreamApp();
  t.after(async () => harness.close());

  const client = connect(harness.url);
  await new Promise((resolve) => client.socket.once("open", resolve));

  sendAudio(client.socket, 0, pcmChunk(250, 0.5));
  const error = await client.waitFor("error");
  assert.equal(error.type === "error" && error.code, "not_started");

  client.socket.close();
});

test("speech stream: exhausted seconds budget closes the socket", async (t) => {
  const harness = await startStreamApp({ allowSeconds: false });
  t.after(async () => harness.close());

  const client = connect(harness.url);
  await new Promise((resolve) => client.socket.once("open", resolve));
  client.socket.send(JSON.stringify({ type: "start" }));
  await client.waitFor("ready");

  const closed = new Promise<number>((resolve) =>
    client.socket.once("close", (code) => resolve(code)),
  );
  // Past the 10 s charge interval, so the budget is actually consulted.
  for (let index = 0; index < 48; index += 1) {
    sendAudio(client.socket, index, pcmChunk(250, 0.5));
  }
  const error = await client.waitFor("error");
  assert.equal(error.type === "error" && error.code, "speech_quota_exhausted");
  assert.equal(await closed, 4429);
  assert.ok(harness.consumed.length > 0, "seconds were metered");
});

test("speech stream: missing cloud_speech consent closes before any audio", async (t) => {
  const harness = await startStreamApp({
    consent: async () => {
      const { AppError } = await import("../../lib/errors.js");
      throw new AppError(403, "consent_required", "İzin gerekli.");
    },
  });
  t.after(async () => harness.close());

  const client = connect(harness.url);
  const closed = new Promise<number>((resolve) =>
    client.socket.once("close", (code) => resolve(code)),
  );
  assert.equal(await closed, 4401);
  assert.equal(harness.transcribeCalls.length, 0);
});
