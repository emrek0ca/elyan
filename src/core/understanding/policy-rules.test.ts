import assert from "node:assert/strict";
import test from "node:test";
import { evaluatePolicyRules, policyRules, selectPolicyWorkload } from "./policy-rules.js";

test("policy rules examples are executable fixtures", () => {
  for (const rule of policyRules) {
    for (const example of rule.examples) {
      const matches = evaluatePolicyRules(example);
      assert.ok(
        matches.some((match) => match.rule.id === rule.id),
        `${rule.id} should match example: ${example}`,
      );
    }
  }
});

test("document generation policy selects document_generate workload", () => {
  assert.equal(selectPolicyWorkload("Yapay zeka güvenliği hakkında bir rapor hazırla"), "document_generate");
  assert.equal(selectPolicyWorkload("Bu konu için pdf olarak düzenli bir belge oluştur"), "document_generate");
});

test("table generation policy selects table_generate workload", () => {
  assert.equal(selectPolicyWorkload("Hava durumunu tablo olarak ver"), "table_generate");
  assert.equal(selectPolicyWorkload("Bunu excel tablosu halinde hazirla"), "table_generate");
  assert.equal(selectPolicyWorkload("Ülkeleri csv olarak çıkar"), "table_generate");
});

test("policy workload selection supports routing phases", () => {
  assert.equal(selectPolicyWorkload("Hava durumunu tablo olarak ver", { phase: "pre_planning" }), "table_generate");
  assert.equal(selectPolicyWorkload("f(x)=x^2 fonksiyonunun grafiğini çiz", { phase: "pre_planning" }), null);
  assert.equal(
    selectPolicyWorkload("f(x)=x^2 fonksiyonunun grafiğini çiz", { phase: "post_planning" }),
    "mobile_chat_balanced",
  );
});

test("table generation policy requires explicit table intent and respects negation", () => {
  assert.equal(selectPolicyWorkload("Turk matematikcileri kisaca anlat"), null);
  assert.equal(selectPolicyWorkload("Kodun 3. satırını açıkla"), null);
  assert.equal(selectPolicyWorkload("Bunu sadece duz yazi olarak anlat, tablo kullanma"), null);
});

test("visual and math policy selects balanced workload after planning priority", () => {
  assert.equal(
    selectPolicyWorkload("z = x^3 + y^2 fonksiyonunun 3 boyutlu yüzey grafiğini çiz", { phase: "post_planning" }),
    "mobile_chat_balanced",
  );
  assert.equal(
    selectPolicyWorkload("Bu denklemi LaTeX ile adım adım çöz", { phase: "post_planning" }),
    "mobile_chat_balanced",
  );
  assert.equal(selectPolicyWorkload("Bana kısa bir özet ver, grafik istemiyorum", { phase: "post_planning" }), null);
});

test("document generation policy avoids Turkish suffix false positives", () => {
  assert.equal(selectPolicyWorkload("Bu deploy sonucunu kısaca raporla"), null);
  assert.equal(selectPolicyWorkload("Yazılım mimarisini iki cümlede açıkla"), null);
});
