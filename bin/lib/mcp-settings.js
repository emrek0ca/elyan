function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function parseCsvSet(value) {
  return new Set(
    String(value || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
  );
}

function findServer(settings, serverId) {
  return (settings.mcp?.servers || []).find((server) => server.id === serverId);
}

function requireServer(settings, serverId) {
  const server = findServer(settings, serverId);
  if (!server) {
    throw new Error(`Unknown MCP server: ${serverId}`);
  }
  return server;
}

function parseMcpServerList(raw) {
  const parsed = JSON.parse(raw);
  return Array.isArray(parsed) ? parsed : parsed.servers;
}

function setMcpServers(settings, raw) {
  const servers = parseMcpServerList(raw);
  if (!Array.isArray(servers)) {
    throw new Error('MCP JSON must be an array or an object with a servers array.');
  }

  const next = clone(settings);
  next.mcp = next.mcp || {};
  next.mcp.servers = servers;
  return next;
}

function setMcpServerEnabled(settings, serverId, enabled) {
  const next = clone(settings);
  const server = requireServer(next, serverId);
  server.enabled = enabled;
  return next;
}

function disableMcpTool(settings, serverId, toolName) {
  const next = clone(settings);
  const server = requireServer(next, serverId);
  const disabledToolNames = new Set(server.disabledToolNames || []);
  disabledToolNames.add(toolName);
  server.disabledToolNames = Array.from(disabledToolNames).sort();
  return next;
}

function buildMcpDoctor(settings, env = process.env) {
  const servers = settings.mcp?.servers || [];
  const disabledServerIds = parseCsvSet(env.ELYAN_DISABLED_MCP_SERVERS);
  const disabledToolNames = parseCsvSet(env.ELYAN_DISABLED_MCP_TOOLS);

  return {
    configured: servers.length > 0,
    serverCount: servers.length,
    disabledServerIds,
    disabledToolNames,
    servers: servers.map((server) => {
      const envDisabled = disabledServerIds.has(server.id);
      const localDisabledTools = new Set(server.disabledToolNames || []);
      const disabledTools = new Set([...localDisabledTools, ...disabledToolNames]);

      return {
        id: server.id,
        transport: server.transport,
        enabled: server.enabled !== false && !envDisabled,
        state: server.enabled === false || envDisabled ? 'disabled' : 'configured',
        stateReason:
          server.enabled === false
            ? 'Server disabled in runtime settings.'
            : envDisabled
              ? 'Server disabled by ELYAN_DISABLED_MCP_SERVERS.'
              : 'Server configured; live discovery runs through the policy-bound MCP registry.',
        disabledToolNames: Array.from(disabledTools).sort(),
        endpoint: server.transport === 'streamable-http' ? server.url : server.command,
      };
    }),
  };
}

module.exports = {
  buildMcpDoctor,
  disableMcpTool,
  setMcpServerEnabled,
  setMcpServers,
};
