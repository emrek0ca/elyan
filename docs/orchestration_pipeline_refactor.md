# Elyan Orchestration Pipeline Refactor (Autonomy + Speed + Reliability)

## Feature-Flagged Upgrade Surface

Default behavior remains unchanged. New logic is additive and controlled by flags under `runtime_policy.feature_flags.*` (or `agent.flags.*`):

- `upgrade_intent_hardening`
- `upgrade_intent_json_envelope`
- `upgrade_attachment_indexer`
- `upgrade_planning_split_cache`
- `upgrade_orchestration_policy`
- `upgrade_typed_tool_io`
- `typed_tools_strict`
- `upgrade_fallback_ladder`
- `upgrade_verify_mandatory_gates`
- `upgrade_performance_routing`
- `upgrade_telemetry_autotune`
- `upgrade_workspace_isolation`

## Updated Architecture Diagram

```mermaid
flowchart TD
    A[Normalize Input] --> B[Intent/Action]
    B --> B1[Deterministic Intent Scorer]
    B --> B2[Attachment Indexer]
    B --> B3[LLM Intent Rescue JSON Envelope - Last Resort]

    B3 --> C[Job Type]
    C --> D[Plan]
    D --> D1[Skeleton Plan Templates]
    D --> D2[Step Specs for Tool Steps]
    D --> D3[Plan Cache TTL]

    D3 --> E[Orchestration Policy]
    E --> E1[Default Single-Agent]
    E --> E2[Multi/Team only when complexity and parallelizable]
    E --> E3[Budgeted Parallelism]

    E3 --> F[Execute]
    F --> F1[Typed Tool I/O Validation]
    F --> F2[Allow/Deny + Runtime Guard + Approval]
    F --> F3[Collect + Tool Mismatch Detector]
    F --> F4[Tool Start/Update/End Stream]

    F3 --> G[Fallback Ladder]
    G --> G1[same plan different model]
    G --> G2[reduced minimal plan]
    G --> G3[deterministic tool macro]
    G --> G4[ask user last]

    G4 --> H[Verify Mandatory Gate]
    H --> H1[Code: lint/smoke/typecheck/entrypoint]
    H --> H2[Research: sources/claim map/unknowns]
    H --> H3[Assets: format/dimension/safe-area]

    H3 --> I[Diff-based Repair Loop]
    I --> J[Delivery]
    J --> K[Telemetry + Auto-Tune (flagged)]
    K --> L[Dashboard Evidence Panel + Tool Timeline]
```

## Pipeline Spec (V2 Additive)

1. Normalize
- Keep existing normalize behavior.
- If `upgrade_attachment_indexer` enabled, index attachments before multimodal processing.

2. Intent Hardening
- Deterministic intent score uses rules + recent context + attachment presence.
- LLM rescue stays last resort.
- If `upgrade_intent_json_envelope` is on, LLM rescue must validate:
  - `{intent, confidence, required_artifacts, tools_needed, safety_flags, assumptions}`

3. Plan Split + Cache
- Build deterministic skeleton plan (3-7 steps by `job_type`).
- Build step specs only for tool-required steps.
- Cache by `(intent + job_type + context_fingerprint)` with TTL.

4. Workspace Isolation + Plain-Text Contract
- If `upgrade_workspace_isolation` enabled, each job/sub-agent gets an isolated workspace.
- Contract files are materialized as plain text:
  - `AGENTS.md`, `SOUL.md`, `TOOLS.md`, `MEMORY.md`
- Goal: reproducibility, diffability, and context contamination control.

5. Orchestration Policy
- Default `single_agent_cdg`.
- Multi/team only when complexity + parallelizable criteria pass.
- Budgeted parallelism: `max_agents <= 3` + token/time budgets.

6. Execute
- Optional typed tool input/output validation (wrapped, non-breaking).
- If `typed_tools_strict` is enabled, schema mismatch rejects tool calls.
- Artifact mismatch detection may fail-fast and trigger fallback state.
- Tool lifecycle stream emits: `start -> update -> end` (sanitized payload).

7. Fallback + Repair
- Progressive fallback ladder is recorded and applied progressively.
- Diff-based repair reruns failing steps only.

8. Verify Mandatory Gates
- If `upgrade_verify_mandatory_gates` enabled, completion is blocked unless gates pass.
- Contract checks include: min files, non-empty files, extension matching, evidence checks.

9. Performance Routing
- Cheap-first model routing with confidence gates.
- Prompt context minimized via digest + constraints + working set.

10. Telemetry
- Per job:
  - `complexity_score`, `token_cost_estimate`, `tool_success_rate`, `verify_pass_rate`, `repair_loops`, `ttfa_ms`
- Optional auto-tuning of orchestration thresholds and retries.
- Dashboard receives first-class tool events and evidence-oriented artifacts.

11. Security Baseline (Operational)
- Run high-risk automations in sandboxed/VM execution contexts.
- Keep credentials least-privileged and rotate periodically.
- Mask/omit sensitive/binary payloads from dashboard streams and logs.

## Migration Notes

- No tool interface breaks: typed validation is wrapper-only.
- Strict verify blocking is opt-in via `upgrade_verify_mandatory_gates`.
- `LLM intent JSON envelope` is opt-in via `upgrade_intent_json_envelope`.
- Existing orchestration remains default when flags are off.

## Suggested Defaults

- Keep all upgrade flags `false` for backward compatibility.
- Enable in rollout order:
  1. `upgrade_attachment_indexer`
  2. `upgrade_planning_split_cache`
  3. `upgrade_performance_routing`
  4. `upgrade_intent_hardening`
  5. `upgrade_orchestration_policy`
  6. `upgrade_typed_tool_io`
  7. `upgrade_fallback_ladder`
  8. `upgrade_verify_mandatory_gates`
  9. `upgrade_telemetry_autotune`
  10. `upgrade_intent_json_envelope`
