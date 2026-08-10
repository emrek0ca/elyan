import test from "node:test";
import assert from "node:assert/strict";
import {
  evaluateGoalEvidence,
  type GoalEvidence,
} from "./goal-verification.js";

function evidence(overrides: Partial<GoalEvidence> = {}): GoalEvidence {
  return {
    successCriteria: ["Belge artifact olarak teslim edilir."],
    resultText: "Rapor hazırlandı ve masaüstüne kaydedildi.",
    artifactRequired: true,
    artifactProduced: true,
    executedStepCount: 2,
    ...overrides,
  };
}

test("a declared artifact that never appeared is a missed goal, not a completed task", () => {
  // Bugüne kadar bu görev `completed` sayılıyordu: adımlar hatasız koştu.
  // Kullanıcı için ise hiçbir şey teslim edilmedi.
  const result = evaluateGoalEvidence(
    evidence({ artifactProduced: false }),
  );
  assert.equal(result?.verdict, "missed");
  assert.equal(result?.reason, "declared_artifact_missing");
});

test("a task that executed no step cannot have met its goal", () => {
  const result = evaluateGoalEvidence(evidence({ executedStepCount: 0 }));
  assert.equal(result?.verdict, "missed");
  assert.equal(result?.reason, "no_step_executed");
});

test("no declared criteria yields unknown, never a free pass", () => {
  // "Ölçüt yoktu" ile "hedef tuttu" aynı şey değil. İkincisini yazmak
  // öğrenme verisini sessizce şişirirdi.
  const result = evaluateGoalEvidence(evidence({ successCriteria: [] }));
  assert.equal(result?.verdict, "unknown");
  assert.equal(result?.reason, "no_success_criteria_declared");
});

test("blank criteria strings count as no criteria", () => {
  const result = evaluateGoalEvidence(
    evidence({ successCriteria: ["  ", ""] }),
  );
  assert.equal(result?.verdict, "unknown");
});

test("a result with neither text nor artifact is missed", () => {
  const result = evaluateGoalEvidence(
    evidence({
      artifactRequired: false,
      artifactProduced: false,
      resultText: "   ",
    }),
  );
  assert.equal(result?.verdict, "missed");
  assert.equal(result?.reason, "no_result_evidence");
});

test("structurally clean tasks defer to the semantic judge instead of self-approving", () => {
  // Kritik: yapısal katman "met" DEMEZ. Kriterin gerçekten karşılanıp
  // karşılanmadığına ancak anlam bakabilir; burada erken "met" yazmak
  // tam da düzeltmeye çalıştığımız gürültülü etiketi geri getirirdi.
  assert.equal(evaluateGoalEvidence(evidence()), null);
  assert.equal(
    evaluateGoalEvidence(
      evidence({ artifactRequired: false, artifactProduced: false }),
    ),
    null,
  );
});

test("an artifact that was never promised does not block the verdict", () => {
  // "Chrome'u kapat" gibi işler dosya üretmez; artefakt yokluğu hata değil.
  assert.equal(
    evaluateGoalEvidence(
      evidence({
        successCriteria: ["Uygulama kapatılır."],
        artifactRequired: false,
        artifactProduced: false,
        resultText: "Google Chrome kapatıldı.",
      }),
    ),
    null,
  );
});
