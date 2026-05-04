import { describe, expect, it } from 'vitest';
import { evaluateLocalAgentAction, type LocalAgentAction } from '@/core/local-agent';
import type { RuntimeLocalAgentSettings } from '@/core/runtime-settings';

const settings: RuntimeLocalAgentSettings = {
  enabled: true,
  allowedRoots: ['.'],
  protectedPaths: ['.env', '.ssh', '/etc'],
  approvalPolicy: {
    readOnly: 'AUTO',
    writeSafe: 'CONFIRM',
    writeSensitive: 'SCREEN',
    destructive: 'TWO_FA',
    systemCritical: 'TWO_FA',
  },
  evidenceDir: 'storage/evidence',
};

describe('Local operator policy', () => {
  it('allows read-only actions inside configured roots without confirmation', () => {
    const action: LocalAgentAction = {
      type: 'filesystem.list',
      path: '.',
    };

    const decision = evaluateLocalAgentAction(action, settings);

    expect(decision.allowed).toBe(true);
    expect(decision.riskLevel).toBe('read_only');
    expect(decision.requiresConfirmation).toBe(false);
  });

  it('requires confirmation for safe writes', () => {
    const action: LocalAgentAction = {
      type: 'filesystem.write_text',
      path: 'tmp/example.txt',
      content: 'hello',
    };

    const decision = evaluateLocalAgentAction(action, settings);

    expect(decision.allowed).toBe(false);
    expect(decision.riskLevel).toBe('write_safe');
    expect(decision.approvalLevel).toBe('CONFIRM');
  });

  it('denies actions outside configured roots', () => {
    const action: LocalAgentAction = {
      type: 'terminal.exec',
      cwd: '/tmp',
      command: 'pwd',
      args: [],
      timeoutMs: 1000,
    };

    const decision = evaluateLocalAgentAction(action, settings);

    expect(decision.allowed).toBe(false);
    expect(decision.riskLevel).toBe('system_critical');
  });

  it('requires confirmation for unknown terminal commands even inside allowed roots', () => {
    const action: LocalAgentAction = {
      type: 'terminal.exec',
      cwd: '.',
      command: 'python',
      args: ['-c', 'print(1)'],
      timeoutMs: 1000,
    };

    const decision = evaluateLocalAgentAction(action, settings);

    expect(decision.allowed).toBe(false);
    expect(decision.riskLevel).toBe('write_safe');
    expect(decision.approvalLevel).toBe('CONFIRM');
  });

  it('escalates protected path writes to system critical', () => {
    const action: LocalAgentAction = {
      type: 'filesystem.write_text',
      path: '.env',
      content: 'SECRET=1',
    };

    const decision = evaluateLocalAgentAction(action, settings);

    expect(decision.allowed).toBe(false);
    expect(decision.riskLevel).toBe('system_critical');
    expect(decision.approvalLevel).toBe('TWO_FA');
  });
});
