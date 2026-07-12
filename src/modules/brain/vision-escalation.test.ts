import assert from "node:assert/strict";
import test from "node:test";
import { assessVisionAnswerEscalation, chooseVisionAnswer } from "./vision-escalation.js";
import { classifyVisionTask } from "./vision-task-policy.js";
import { decideVisionMediaPolicy } from "./vision-media-policy.js";

const task = classifyVisionTask({ prompt: "Belgedeki küçük yazıyı oku", imageCount: 1 });
const media = decideVisionMediaPolicy({ task, images: [], prompt: "Belgedeki küçük yazıyı oku", explicitCloudConsent: true });

test("uncertain thin detail answer requests one secondary analysis", () => {
  const decision = assessVisionAnswerEscalation({
    text: "Yazı net değil, okuyamıyorum.",
    task,
    media,
    hasSecondaryCandidate: true,
  });
  assert.equal(decision.shouldEscalate, true);
});

test("strong primary answer is not replaced by a weaker secondary refusal", () => {
  const chosen = chooseVisionAnswer({
    primary: "Belgedeki hata kodu E104. Bu kod bağlantı zaman aşımını gösteriyor; ağı kontrol edip işlemi yeniden deneyin.",
    secondary: "Bunu okuyamıyorum.",
    task,
  });
  assert.equal(chosen.usedSecondary, false);
  assert.match(chosen.text, /E104/);
});

test("useful independent review can replace an uncertain primary", () => {
  const chosen = chooseVisionAnswer({
    primary: "Yazı net değil.",
    secondary: "Ekrandaki kod E104. Bağlantı zaman aşımını işaret ediyor; önce internet bağlantısını kontrol edin.",
    task,
  });
  assert.equal(chosen.usedSecondary, true);
  assert.match(chosen.text, /E104/);
});

test("multilingual uncertainty requests a secondary analysis", () => {
  const spanishTask = classifyVisionTask({ prompt: "Lee el texto de este documento", imageCount: 1 });
  const spanishMedia = decideVisionMediaPolicy({ task: spanishTask, images: [], prompt: "Lee el texto de este documento", explicitCloudConsent: true });
  const decision = assessVisionAnswerEscalation({
    text: "El texto está borroso y no se lee.",
    task: spanishTask,
    media: spanishMedia,
    hasSecondaryCandidate: true,
  });
  assert.equal(decision.shouldEscalate, true);
  assert.ok(decision.reasons.includes("explicit_uncertainty"));
});

test("multilingual refusal cannot replace a useful primary answer", () => {
  const chosen = chooseVisionAnswer({
    primary: "Код ошибки E104 означает тайм-аут соединения. Проверьте сеть и повторите попытку.",
    secondary: "Не могу помочь.",
    task,
  });
  assert.equal(chosen.usedSecondary, false);
  assert.match(chosen.text, /E104/);
});

test("provider-leaking secondary answer cannot replace a clean answer", () => {
  const chosen = chooseVisionAnswer({
    primary: "Belgedeki kod E104 ve görünür açıklaması bağlantı zaman aşımıdır.",
    secondary: "Claude provider üzerinden analiz ettim ve kod E104 olabilir; ayrıntılar kesin değil.",
    task,
  });
  assert.equal(chosen.usedSecondary, false);
  assert.doesNotMatch(chosen.text, /Claude|provider/iu);
});

test("conflicting critical codes prevent either pass from becoming authoritative", () => {
  const chosen = chooseVisionAnswer({
    primary: "Ekrandaki hata kodu `E104`; bağlantıyı kontrol edin.",
    secondary: "Ekrandaki hata kodu `E105`; uygulamayı yeniden başlatın.",
    task,
  });
  assert.equal(chosen.usedSecondary, false);
  assert.equal(chosen.conflictDetected, true);
});
