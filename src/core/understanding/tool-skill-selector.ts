import type { SharedBrainWorkload } from "../../modules/brain/workloads.js";
import {
  compileOutputContract,
  workloadFromOutputContract,
  type OutputContract,
} from "./output-contract.js";

export type ToolSkillCandidate = {
  id: string;
  surface:
    | "chat"
    | "document"
    | "spreadsheet"
    | "chart"
    | "image"
    | "desktop";
  workload: SharedBrainWorkload | null;
  score: number;
  reasons: string[];
};

export type ToolSkillSelection = {
  outputContract: OutputContract;
  selected: ToolSkillCandidate;
  candidates: ToolSkillCandidate[];
};

function candidate(
  id: string,
  surface: ToolSkillCandidate["surface"],
  workload: SharedBrainWorkload | null,
  score: number,
  reasons: string[],
): ToolSkillCandidate {
  return {
    id,
    surface,
    workload,
    score: Math.max(0, Math.min(1, Number(score.toFixed(3)))),
    reasons,
  };
}

export function selectToolSkillForTurn(input: {
  message: string;
  title?: string | null;
  metadata?: Record<string, unknown> | null;
}): ToolSkillSelection {
  const outputContract = compileOutputContract(input);
  const contractWorkload = workloadFromOutputContract(outputContract);
  const candidates = [
    candidate(
      "chat.reply",
      "chat",
      null,
      outputContract.requiresArtifact ? 0.25 : 0.74,
      ["default_chat_surface"],
    ),
    candidate(
      "document.write",
      "document",
      "document_generate",
      outputContract.outputKind === "document"
        ? 0.62 + outputContract.confidence * 0.35
        : 0.12,
      ["document_artifact_surface", ...outputContract.reasons],
    ),
    candidate(
      "spreadsheet.write",
      "spreadsheet",
      "table_generate",
      outputContract.outputKind === "table"
        ? 0.62 + outputContract.confidence * 0.35
        : 0.1,
      ["spreadsheet_table_surface", ...outputContract.reasons],
    ),
    candidate(
      "chart.generate",
      "chart",
      "mobile_chat_balanced",
      outputContract.outputKind === "chart"
        ? 0.58 + outputContract.confidence * 0.32
        : 0.1,
      ["chart_surface", ...outputContract.reasons],
    ),
    candidate(
      "image.generate",
      "image",
      "image_analyze",
      outputContract.outputKind === "image" || outputContract.outputKind === "svg"
        ? 0.55 + outputContract.confidence * 0.34
        : 0.08,
      ["image_surface", ...outputContract.reasons],
    ),
  ];
  const selected =
    candidates
      .filter((item) => (contractWorkload ? item.workload === contractWorkload : true))
      .sort((left, right) => right.score - left.score)[0] ??
    candidates.sort((left, right) => right.score - left.score)[0]!;
  return {
    outputContract,
    selected,
    candidates: candidates.sort((left, right) => right.score - left.score),
  };
}
