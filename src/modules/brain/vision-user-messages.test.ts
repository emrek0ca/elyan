import assert from "node:assert/strict";
import test from "node:test";
import { buildVisionRecoveryMessage, detectVisionMessageLocale } from "./vision-user-messages.js";
import { classifyVisionTask } from "./vision-task-policy.js";

const localeCases = [
  ["Bu görseli açıkla", "tr"],
  ["Explain this image", "en"],
  ["Explica esta imagen", "es"],
  ["Expliquez cette image", "fr"],
  ["Erkläre dieses Bild", "de"],
  ["Spiega questa immagine", "it"],
  ["Explique esta imagem", "pt"],
  ["Объясни это изображение", "ru"],
  ["اشرح هذه الصورة", "ar"],
] as const;

for (const [prompt, locale] of localeCases) {
  test(`vision recovery detects ${locale}`, () => {
    assert.equal(detectVisionMessageLocale(prompt), locale);
  });
}

test("vision recovery keeps a Spanish retry in Spanish", () => {
  const prompt = "Lee el mensaje de error en esta pantalla";
  const task = classifyVisionTask({ prompt, imageCount: 1 });
  const message = buildVisionRecoveryMessage({ prompt, reason: "fine_detail", task });
  assert.match(message, /Envía|texto|nítido/u);
  assert.doesNotMatch(message, /Please send|Görsel/u);
});
