import assert from "node:assert/strict";
import test from "node:test";
import { selectInformationNeed } from "./information-need.js";

test("selectInformationNeed chooses one high-impact contextual question", () => {
  const need = selectInformationNeed({
    questions: ["Rapor hangi tarih aralığını kapsasın?", "Hangi klasöre kaydedeyim?"],
    goalId: "goal-1",
    stepId: "write",
  });
  assert.equal(need?.contract, "elyan.information_need.v1");
  assert.equal(need?.field, "target");
  assert.equal(need?.question, "Hangi klasöre kaydedeyim?");
  assert.equal(need?.goalId, "goal-1");
  assert.equal(need?.stepId, "write");
});

test("selectInformationNeed rejects generic clarification templates", () => {
  assert.equal(selectInformationNeed({ questions: ["Netleştireyim: tam olarak neyi yapmamı istiyorsun?"] }), null);
});
