import { z } from "zod";

export const proceduralMemoryCandidateSchema = z.object({
  version: z.literal("procedural_memory_candidate.v1"),
  id: z.string().uuid(),
  ownerUserId: z.string().uuid().nullable(),
  capability: z.string().trim().min(1).max(120),
  trigger: z.object({
    intent: z.string().trim().min(1).max(120),
    requiredInputs: z.array(z.string().trim().min(1).max(120)).max(32),
  }),
  steps: z.array(z.object({
    ordinal: z.number().int().nonnegative(),
    capability: z.string().trim().min(1).max(120),
    inputBindings: z.record(z.string()),
    expectedOutput: z.record(z.unknown()),
  })).min(1).max(64),
  evidenceTraceIds: z.array(z.string().max(160)).max(64),
  status: z.literal("draft"),
  createdAt: z.string().datetime({ offset: true }),
});

export type ProceduralMemoryCandidate = z.output<typeof proceduralMemoryCandidateSchema>;
