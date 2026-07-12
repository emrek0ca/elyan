import assert from "node:assert/strict";
import test from "node:test";
import { classifyVisionTask } from "./vision-task-policy.js";
import {
  assessVisionResponseCoverage,
  getVisionResponseContract,
} from "./vision-response-contract.js";

test("screen debugging contract rewards visible error plus actionable fix", () => {
  const task = classifyVisionTask({ prompt: "Bu ekran görüntüsündeki hatayı çöz", imageCount: 1 });
  const contract = getVisionResponseContract(task);
  const weak = assessVisionResponseCoverage({ text: "Bir sorun var gibi görünüyor.", contract });
  const strong = assessVisionResponseCoverage({
    text: "Ekranda `E104 Connection timeout` hatası görünüyor. Önce bağlantıyı kontrol et, ardından işlemi yeniden dene; sürerse uygulamayı yeniden başlat.",
    contract,
  });
  assert.ok(strong.score > weak.score);
  assert.equal(strong.missing.length, 0);
});

test("chart contract detects missing axes and trend", () => {
  const task = classifyVisionTask({ prompt: "Bu grafiği yorumla", imageCount: 1 });
  const contract = getVisionResponseContract(task);
  const result = assessVisionResponseCoverage({ text: "Grafik genel olarak dikkat çekici.", contract });
  assert.ok(result.missing.includes("axes"));
  assert.ok(result.missing.includes("trend"));
});

test("chart contract recognizes a complete Spanish explanation", () => {
  const task = classifyVisionTask({ prompt: "Interpreta este gráfico", imageCount: 1 });
  const contract = getVisionResponseContract(task);
  const result = assessVisionResponseCoverage({
    text: "El eje X muestra los meses y el eje Y usa euros como unidad. La tendencia aumenta hasta junio, alcanza un pico y después disminuye.",
    contract,
  });
  assert.equal(result.missing.length, 0);
});

test("comparison contract recognizes stable German image labels", () => {
  const task = classifyVisionTask({ prompt: "Vergleiche diese beiden Bilder", imageCount: 2 });
  const contract = getVisionResponseContract(task);
  const result = assessVisionResponseCoverage({
    text: "Das erste Bild links ist heller, während das zweite Bild rechts deutlich mehr Kontrast zeigt. Der Unterschied liegt vor allem in Helligkeit und Farbe.",
    contract,
  });
  assert.equal(result.missing.length, 0);
});
