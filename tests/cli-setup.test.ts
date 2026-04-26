import { execFileSync } from 'child_process';
import { mkdtempSync, readFileSync, rmSync } from 'fs';
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
  it('prepares zero-cost local settings without hosted account linking', () => {
    const cwd = createTempDir();
    const home = createTempDir();
    const output = execFileSync(
      process.execPath,
      [cliPath, 'setup', '--zero-cost', '--model', 'llama3.2', '--probe-timeout-ms', '25'],
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
    expect(output).toContain('local_only via ollama:llama3.2');
    expect(settings.routing.routingMode).toBe('local_only');
    expect(settings.routing.preferredModelId).toBe('ollama:llama3.2');
    expect(settings.routing.searchEnabled).toBe(false);
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
});
