/**
 * Local runtime health probe that also surfaces hosted control-plane readiness.
 * Layer: status API. Critical top-level readiness endpoint used by local verification and deploy checks.
 */
import { NextResponse } from 'next/server';
import { readRuntimeEnvValue } from '@/core/runtime-config';
import { readRuntimeStatusSnapshot } from '@/core/runtime-status';
import { buildRuntimeRegistryHealthSnapshot } from '@/core/runtime-registry';
import { getRuntimeVersionInfo } from '@/core/runtime-version';

export async function GET() {
  const result = await readRuntimeStatusSnapshot();
  const version = getRuntimeVersionInfo();

  if (!result.ok) {
    return NextResponse.json(
      {
        ok: false,
        service: 'elyan',
        version: version.version,
        releaseTag: version.releaseTag,
        buildSha: version.buildSha,
        mode: process.env.NODE_ENV ?? 'development',
        runtime: 'local-first',
        ready: false,
        error: 'Environment configuration is invalid.',
        issues: result.issues,
      },
      { status: 503 }
    );
  }

  const { snapshot } = result;
  const runtimeSettings = snapshot.runtimeSettings;
  const searchProbe = snapshot.search.probe;
  const controlPlaneHealth = snapshot.controlPlane.health;
  const workspace = snapshot.workspace;
  const registryHealth = buildRuntimeRegistryHealthSnapshot(snapshot.registry);
  const hostedAuthConfigured =
    controlPlaneHealth.runtime?.authConfigured ?? controlPlaneHealth.authConfigured ?? false;
  const hostedBillingConfigured =
    controlPlaneHealth.runtime?.billingConfigured ?? controlPlaneHealth.billingConfigured ?? false;
  const mcpConfigured =
    runtimeSettings.mcp.servers.length > 0 || Boolean(readRuntimeEnvValue('ELYAN_MCP_SERVERS')?.trim());
  const voiceConfigured = Boolean(runtimeSettings.voice.accessKey || readRuntimeEnvValue('PICOVOICE_ACCESS_KEY'));
  const ready = registryHealth.ready;

  return NextResponse.json({
    ok: true,
    service: 'elyan',
    version: version.version,
    releaseTag: version.releaseTag,
    buildSha: version.buildSha,
    mode: process.env.NODE_ENV ?? 'development',
    runtime: 'local-first',
    ready,
    checks: {
      search: {
        ok: runtimeSettings.routing.searchEnabled ? searchProbe.ok : true,
        url: snapshot.search.url,
        status: searchProbe.status,
        optional: true,
        enabled: runtimeSettings.routing.searchEnabled,
        hint: searchProbe.ok
          ? undefined
          : runtimeSettings.routing.searchEnabled
            ? 'Search is optional. Start SearxNG or update SEARXNG_URL if you want live web retrieval and citations.'
            : 'Search is disabled in runtime settings.',
      },
      models: {
        ok: registryHealth.sections.ml.status === 'healthy',
        count: snapshot.models.length,
        local: snapshot.models.filter((model) => model.type === 'local').map((model) => model.id),
        cloud: snapshot.models.filter((model) => model.type === 'cloud').map((model) => model.id),
        lastError: registryHealth.sections.ml.lastError,
        latest: registryHealth.latest.ml,
        hint: registryHealth.sections.ml.status === 'healthy'
          ? undefined
          : registryHealth.sections.ml.lastError ?? 'Run Ollama and pull a model, or set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GROQ_API_KEY.',
      },
      mcp: {
        configured: mcpConfigured,
        hint: mcpConfigured ? undefined : 'Optional. Set ELYAN_MCP_SERVERS only if you want live MCP integration.',
      },
      channels: {
        ...snapshot.channels,
      },
      localAgent: {
        ...snapshot.localAgent,
        ready: snapshot.localAgent.enabled && snapshot.localAgent.allowedRoots.length > 0,
      },
      voice: {
        configured: voiceConfigured,
        enabled: runtimeSettings.voice.enabled,
        wakeWord: runtimeSettings.voice.wakeWord,
        hint: voiceConfigured
          ? undefined
          : 'Optional. Set PICOVOICE_ACCESS_KEY to enable the local wake-word voice path.',
      },
      workspace: {
        configured: workspace.summary.configuredSourceCount > 0,
        connectedSources: workspace.summary.connectedSourceCount,
        briefItems: workspace.summary.briefItemCount,
        hint:
          workspace.summary.configuredSourceCount > 0
            ? undefined
            : 'Optional. Connect GitHub, Obsidian, or MCP surfaces for Gmail, Calendar, and Notion to build a daily brief.',
      },
      hosted: {
        authConfigured: hostedAuthConfigured,
        billingConfigured: hostedBillingConfigured,
        hint:
          hostedAuthConfigured && hostedBillingConfigured
            ? undefined
            : 'Optional. Hosted auth and billing are only required for shared control-plane flows.',
      },
      registry: {
        ok: registryHealth.ready,
        ...registryHealth,
        operator: {
          status: registryHealth.sections.operator.status,
          runs: registryHealth.sections.operator.counts.runs,
          pendingApprovals: registryHealth.sections.operator.counts.pendingApprovals,
          latestRun: registryHealth.latest.run,
          latestApproval: registryHealth.latest.approval,
        },
        runs: {
          status: registryHealth.sections.runs.status,
          enabled: registryHealth.sections.runs.enabled,
          source: registryHealth.sections.runs.source,
          risk: registryHealth.sections.runs.risk,
          approvalRequirement: registryHealth.sections.runs.approvalRequirement,
          live: registryHealth.sections.runs.live,
          cached: registryHealth.sections.runs.cached,
          lastError: registryHealth.sections.runs.lastError,
          counts: registryHealth.sections.runs.counts,
          latest: registryHealth.latest.run,
        },
        approvals: {
          status: registryHealth.sections.approvals.status,
          enabled: registryHealth.sections.approvals.enabled,
          source: registryHealth.sections.approvals.source,
          risk: registryHealth.sections.approvals.risk,
          approvalRequirement: registryHealth.sections.approvals.approvalRequirement,
          live: registryHealth.sections.approvals.live,
          cached: registryHealth.sections.approvals.cached,
          lastError: registryHealth.sections.approvals.lastError,
          counts: registryHealth.sections.approvals.counts,
          latest: registryHealth.latest.approval,
        },
        skills: {
          status: registryHealth.sections.skills.status,
          enabled: registryHealth.sections.skills.enabled,
          source: registryHealth.sections.skills.source,
          risk: registryHealth.sections.skills.risk,
          approvalRequirement: registryHealth.sections.skills.approvalRequirement,
          live: registryHealth.sections.skills.live,
          cached: registryHealth.sections.skills.cached,
          lastError: registryHealth.sections.skills.lastError,
          counts: registryHealth.sections.skills.counts,
          latest: registryHealth.latest.skill,
        },
        mcp: {
          status: registryHealth.sections.mcp.status,
          enabled: registryHealth.sections.mcp.enabled,
          source: registryHealth.sections.mcp.source,
          risk: registryHealth.sections.mcp.risk,
          approvalRequirement: registryHealth.sections.mcp.approvalRequirement,
          live: registryHealth.sections.mcp.live,
          cached: registryHealth.sections.mcp.cached,
          lastError: registryHealth.sections.mcp.lastError,
          counts: registryHealth.sections.mcp.counts,
          latest: registryHealth.latest.mcp,
        },
        ml: {
          status: registryHealth.sections.ml.status,
          enabled: registryHealth.sections.ml.enabled,
          source: registryHealth.sections.ml.source,
          risk: registryHealth.sections.ml.risk,
          approvalRequirement: registryHealth.sections.ml.approvalRequirement,
          live: registryHealth.sections.ml.live,
          cached: registryHealth.sections.ml.cached,
          lastError: registryHealth.sections.ml.lastError,
          counts: registryHealth.sections.ml.counts,
          latest: registryHealth.latest.ml,
        },
        models: {
          status: registryHealth.sections.ml.status,
          enabled: registryHealth.sections.ml.enabled,
          source: registryHealth.sections.ml.source,
          risk: registryHealth.sections.ml.risk,
          approvalRequirement: registryHealth.sections.ml.approvalRequirement,
          live: registryHealth.sections.ml.live,
          cached: registryHealth.sections.ml.cached,
          lastError: registryHealth.sections.ml.lastError,
          counts: registryHealth.sections.ml.counts,
          latest: registryHealth.latest.ml,
        },
      },
      operator: {
        status: snapshot.operator?.status ?? 'unknown',
        pendingApprovals: Number(snapshot.operator?.approvals?.pending ?? 0),
        totalRuns: Number(snapshot.operator?.runs?.total ?? 0),
        latestRunId: snapshot.operator?.runs?.latest?.id,
        modelRuntime: snapshot.registry.ml,
      },
    },
    nextSteps: snapshot.nextSteps,
    surfaces: snapshot.surfaces,
    operator: snapshot.operator,
    registry: snapshot.registry,
    workspace,
  });
}
