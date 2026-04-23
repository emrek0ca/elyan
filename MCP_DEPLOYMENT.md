# MCP Deployment Contract

MCP is optional. Elyan core v1 must keep working when MCP is absent, offline, or misconfigured.

## Transport Rule

- Use `stdio` for same-host workers launched as separate processes or containers
- Use `streamable-http` for remote or shared MCP services
- Do not embed a long-running MCP server inside the Next.js runtime

## Supported Objects

- Tools
- Resources
- Prompts
- Resource templates

These are surfaced through the local capability catalog and the MCP registry, but they stay protocol objects, not a generic tool pile.
They are runtime integration objects, not Codex/agent skills.

## Lifecycle Rule

- Discover, invoke, and close MCP clients explicitly
- Soft-fail discovery and connection issues
- Never let an MCP outage break the core ask -> retrieve -> read -> answer -> cite loop

## Disable Rule

- `ELYAN_DISABLED_MCP_SERVERS`
- `ELYAN_DISABLED_MCP_TOOLS`

## Browser Boundary

Playwright and Crawlee remain local Elyan capabilities.
They are not moved behind MCP unless there is a concrete operational reason.

## Validation

Use `npm run mcp:validate` to verify live transport, tool discovery, resource and prompt support, invocation, and teardown.
