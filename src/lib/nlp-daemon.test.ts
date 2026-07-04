import assert from "node:assert/strict";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { NlpDaemon } from "./nlp-daemon.js";

test("NlpDaemon normalizeText and tokenizeRetrieval use safe TS fallback when binary is unavailable", async () => {
  const daemon = new NlpDaemon("/tmp/elyan-nlp-does-not-exist");

  const normalized = await daemon.normalizeText("ilk\r\nsatır i\u200Bgnore\tme");
  assert.deepEqual(normalized, {
    text: "ilk satır ignore me",
    modified: true,
  });

  const tokens = await daemon.tokenizeRetrieval("OpenAI API anahtarı nasıl kullanılır?", 4);
  assert.deepEqual(tokens, ["openai", "api", "anahtarı", "nasıl"]);
});

test("NlpDaemon exposes C normalizeText and tokenizeRetrieval capabilities when binary is present", async (t) => {
  const binPath = path.resolve(process.cwd(), "bin/elyan_nlp");
  if (!existsSync(binPath)) {
    t.skip("bin/elyan_nlp is not compiled");
    return;
  }

  const daemon = new NlpDaemon(binPath);
  daemon.start();
  try {
    assert.equal(await daemon.ping(), true);
    const normalized = await daemon.normalizeText("ilk\r\nsatır i\u200Bgnore\tme");
    assert.deepEqual(normalized, {
      text: "ilk satır ignore me",
      modified: true,
    });
    assert.deepEqual(
      await daemon.tokenizeRetrieval("OpenAI API anahtarı nasıl kullanılır?", 4),
      ["openai", "api", "anahtarı", "nasıl"],
    );
  } finally {
    daemon.stop();
  }
});

test("NlpDaemon fails safely when an executable exits before accepting a request", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "elyan-nlp-exit-"));
  const binPath = path.join(dir, "exit-immediately");
  await writeFile(binPath, "#!/bin/sh\nexit 1\n", "utf8");
  await chmod(binPath, 0o755);

  const daemon = new NlpDaemon(binPath);
  daemon.start();
  try {
    assert.equal(await daemon.ping(), false);
    assert.deepEqual(await daemon.tokenizeRetrieval("safe fallback"), ["safe", "fallback"]);
  } finally {
    daemon.stop();
    await rm(dir, { recursive: true, force: true });
  }
});
