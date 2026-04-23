# Elyan Product Model

Elyan has three product layers and one operator layer.

## Local Agent Runtime

- Primary product
- Runs on the user’s machine or their own server
- Keeps private context local by default
- Handles model routing, retrieval, citations, capabilities, and operator execution

## Shared VPS Control Plane

- Accounts
- Subscriptions
- Billing
- Entitlements
- Credits and hosted usage accounting
- Product-level routing policy and non-personal signals
- Release metadata and update status for the installed runtime
- Device sync metadata that does not contain private local context

This plane is intentionally narrow. It must not become a private-memory store.

## Hosted Web Surface

- Public access through `elyan.dev`
- Can answer users honestly through the hosted path
- Does not replace the local runtime
- Can expose billing, credits, entitlement state, and update availability clearly

## Operator Layer

The operator decides whether a request should:

1. Use a local runtime capability or bridge tool
2. Read an MCP resource or prompt
3. Invoke an MCP tool
4. Use Playwright for dynamic browser interaction
5. Use Crawlee for bounded crawl work
6. Answer directly

Reusable runtime prompt templates belong in the runtime itself, such as `src/core/agents/answer-prompts.ts`, or in MCP prompt/resource objects when the integration is external.

## Continuous Improvement

- Evaluation hooks capture retrieval quality, citation accuracy, tool success, latency, and usage
- Signals are stored as non-personal hosted truth only
- No automatic model mutation or silent promotion is allowed
- A promotion gate is required before any learned change can influence stable behavior
- Local private context stays local unless the user explicitly chooses otherwise

## Boundary Rule

- Local/private data stays local by default
- Hosted usage is metered and separated
- MCP is optional and isolated
- The system remains one product, not three unrelated systems
