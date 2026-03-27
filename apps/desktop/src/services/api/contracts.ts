import { z } from "zod";

export const apiEnvelopeSchema = z.object({
  success: z.boolean(),
  error: z.string().optional(),
});

export const runSchema = z.object({
  run_id: z.string().optional(),
  id: z.string().optional(),
  intent: z.string().optional(),
  status: z.string().optional(),
  workflow_state: z.string().optional(),
  task_type: z.string().optional(),
  tool_call_count: z.number().optional(),
  step_count: z.number().optional(),
  completed_at: z.number().optional(),
  started_at: z.number().optional(),
  error_message: z.string().optional(),
  error: z.string().optional(),
  artifact_path: z.string().optional(),
  artifacts: z.array(z.record(z.any())).optional(),
  steps: z.array(z.record(z.any())).optional(),
  tool_calls: z.array(z.record(z.any())).optional(),
  review_report: z.record(z.any()).optional(),
  workflow_history: z.array(z.record(z.any())).optional(),
  assigned_agents: z.array(z.string()).optional(),
});

export const backendSchema = z.object({
  name: z.string(),
  language: z.string().optional(),
  configured: z.boolean().optional(),
  available: z.boolean().optional(),
  active: z.boolean().optional(),
  details: z.record(z.any()).optional(),
});

export const approvalSchema = z.object({
  request_id: z.string().optional(),
  id: z.string().optional(),
  action: z.string().optional(),
  priority: z.string().optional(),
  confidence: z.number().optional(),
});
