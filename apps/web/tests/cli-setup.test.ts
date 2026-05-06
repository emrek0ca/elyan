import { execFileSync } from 'child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join, resolve } from 'path';
import { afterEach, describe, expect, it } from 'vitest';

const cliPath = resolve(process.cwd(), 'bin', 'elyan.js');
const tempDirs: string[] = [];

afterEach(() => {
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop()!, { recursive: true, force: true });
  }
});

function createTempDir() {
  const dir = mkdtempSync(join(tmpdir(), 'elyan-cli-setup-'));
  tempDirs.push(dir);
  return dir;
}

describe('elyan setup CLI', () => {
  it('prepares local-first settings without hosted account linking', () => {
    const cwd = createTempDir();
    const home = createTempDir();
    const output = execFileSync(
      process.execPath,
      [cliPath, 'setup', '--model', 'llama3.2', '--probe-timeout-ms', '25'],
      {
        cwd,
        env: {
          ...process.env,
          HOME: home,
          USERPROFILE: home,
          OLLAMA_URL: 'http://127.0.0.1:1',
          SEARXNG_URL: 'http://127.0.0.1:1',
        },
        encoding: 'utf8',
      }
    );

    const settings = JSON.parse(readFileSync(join(cwd, 'storage', 'runtime', 'settings.json'), 'utf8'));
    const envFile = readFileSync(join(home, '.elyan', '.env'), 'utf8');

    expect(output).toContain('Elyan setup');
    expect(output).toContain('local_first');
    expect(settings.routing.routingMode).toBe('local_first');
    expect(settings.routing.preferredModelId).toBeUndefined();
    expect(settings.routing.searchEnabled).toBe(true);
    expect(envFile).toContain('OLLAMA_URL=http://127.0.0.1:11434');
  });

  it('manages MCP server and tool visibility without changing command compatibility', () => {
    const cwd = createTempDir();
    const home = createTempDir();
    const env = {
      ...process.env,
      HOME: home,
      USERPROFILE: home,
    };
    const servers = JSON.stringify([
      {
        id: 'workspace-mcp',
        transport: 'stdio',
        command: 'node',
        args: [],
      },
    ]);

    const setOutput = execFileSync(process.execPath, [cliPath, 'mcp', 'set', servers], {
      cwd,
      env,
      encoding: 'utf8',
    });
    expect(setOutput).toContain('Updated MCP servers');

    const doctorOutput = execFileSync(process.execPath, [cliPath, 'mcp', 'doctor'], {
      cwd,
      env: {
        ...env,
        ELYAN_DISABLED_MCP_SERVERS: 'workspace-mcp',
        ELYAN_DISABLED_MCP_TOOLS: 'dangerous_write',
      },
      encoding: 'utf8',
    });
    expect(doctorOutput).toContain('MCP doctor');
    expect(doctorOutput).toContain('workspace-mcp');
    expect(doctorOutput).toContain('Disabled by env: workspace-mcp');
    expect(doctorOutput).toContain('dangerous_write');

    execFileSync(process.execPath, [cliPath, 'mcp', 'disable-tool', 'workspace-mcp', 'delete_file'], {
      cwd,
      env,
      encoding: 'utf8',
    });
    execFileSync(process.execPath, [cliPath, 'mcp', 'disable', 'workspace-mcp'], {
      cwd,
      env,
      encoding: 'utf8',
    });

    let settings = JSON.parse(readFileSync(join(cwd, 'storage', 'runtime', 'settings.json'), 'utf8'));
    expect(settings.mcp.servers[0].enabled).toBe(false);
    expect(settings.mcp.servers[0].disabledToolNames).toEqual(['delete_file']);

    execFileSync(process.execPath, [cliPath, 'mcp', 'enable', 'workspace-mcp'], {
      cwd,
      env,
      encoding: 'utf8',
    });
    settings = JSON.parse(readFileSync(join(cwd, 'storage', 'runtime', 'settings.json'), 'utf8'));
    expect(settings.mcp.servers[0].enabled).toBe(true);
  });

  it('creates and resolves local v1.3 operator runs without a hosted server', () => {
    const cwd = createTempDir();
    const home = createTempDir();
    const env = {
      ...process.env,
      HOME: home,
      USERPROFILE: home,
    };

    const runOutput = execFileSync(
      process.execPath,
      [cliPath, 'run', '--mode', 'code', 'implement', 'a', 'safe', 'patch'],
      {
        cwd,
        env,
        encoding: 'utf8',
      }
    );

    expect(runOutput).toContain('Elyan operator run');
    expect(runOutput).toContain('Mode: code');
    expect(runOutput).toContain('Reasoning: deep, 5 passes');
    expect(runOutput).toContain('Pending approvals: 1');

    const runsOutput = execFileSync(process.execPath, [cliPath, 'runs', 'list'], {
      cwd,
      env,
      encoding: 'utf8',
    });
    expect(runsOutput).toContain('code');
    expect(runsOutput).toContain('blocked');
    expect(runsOutput).toContain('0/3 gates');

    const runFiles = readdirSync(join(cwd, 'storage', 'operator-runs')).filter((entry) => entry.endsWith('.json'));
    const run = JSON.parse(readFileSync(join(cwd, 'storage', 'operator-runs', runFiles[0]), 'utf8'));
    const approvalId = run.approvals[0].id;
    expect(run.reasoning.depth).toBe('deep');
    expect(run.qualityGates.find((gate: { title: string }) => gate.title === 'Approval boundary')?.status).toBe('blocked');

    const approvalOutput = execFileSync(process.execPath, [cliPath, 'approvals', 'approve', approvalId], {
      cwd,
      env,
      encoding: 'utf8',
    });

    expect(approvalOutput).toContain('approved');

    const updatedRun = JSON.parse(readFileSync(join(cwd, 'storage', 'operator-runs', runFiles[0]), 'utf8'));
    expect(updatedRun.status).toBe('planned');
    expect(updatedRun.approvals[0].status).toBe('approved');
  });

  it('runs the local optimization demo as JSON and Markdown', () => {
    const cwd = createTempDir();
    const home = createTempDir();
    const env = {
      ...process.env,
      HOME: home,
      USERPROFILE: home,
    };

    const jsonOutput = execFileSync(process.execPath, [cliPath, 'optimize', 'demo', 'assignment', '--json'], {
      cwd,
      env,
      encoding: 'utf8',
    });
    const parsed = JSON.parse(jsonOutput);

    expect(parsed.jsonSummary.problemType).toBe('assignment');
    expect(parsed.jsonSummary.feasible).toBe(true);
    expect(parsed.pipeline.map((step: { step: string }) => step.step)).toContain('compare');
    expect(parsed.solverResults.map((entry: { solver: string }) => entry.solver)).toContain('simulated_annealing');

    const markdownOutput = execFileSync(process.execPath, [cliPath, 'optimize', 'demo', 'resource-allocation'], {
      cwd,
      env,
      encoding: 'utf8',
    });

    expect(markdownOutput).toContain('Recommended Solution');
    expect(markdownOutput).toContain('simulated_annealing');
    expect(markdownOutput).toContain('Constraint violations');
  });
});
