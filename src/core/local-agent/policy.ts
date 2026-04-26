import path from 'path';
import type { RuntimeLocalAgentSettings } from '@/core/runtime-settings';
import type { LocalAgentAction, LocalAgentApprovalLevel, LocalAgentDecision, LocalAgentRiskLevel } from './types';

const terminalDestructivePattern = /\b(rm|sudo|chmod|chown|mkfs|dd|shutdown|reboot|killall|launchctl|systemctl|docker\s+system\s+prune)\b/i;
const terminalWritePattern = /\b(mv|cp|mkdir|touch|npm\s+install|pnpm\s+install|yarn\s+add|brew\s+install|git\s+commit|git\s+push)\b/i;
const terminalReadOnlyCommands = new Set([
  'pwd',
  'ls',
  'cat',
  'sed',
  'rg',
  'grep',
  'find',
  'wc',
  'head',
  'tail',
  'git',
  'node',
  'npm',
]);

function resolveInsideCwd(inputPath: string) {
  return path.resolve(process.cwd(), inputPath);
}

function normalizeConfiguredPath(inputPath: string) {
  return path.isAbsolute(inputPath) ? path.resolve(inputPath) : resolveInsideCwd(inputPath);
}

function isInside(candidate: string, root: string) {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

function actionPath(action: LocalAgentAction) {
  if ('path' in action) {
    return action.path;
  }

  return action.cwd;
}

function approvalForRisk(settings: RuntimeLocalAgentSettings, riskLevel: LocalAgentRiskLevel): LocalAgentApprovalLevel {
  switch (riskLevel) {
    case 'read_only':
      return settings.approvalPolicy.readOnly;
    case 'write_safe':
      return settings.approvalPolicy.writeSafe;
    case 'write_sensitive':
      return settings.approvalPolicy.writeSensitive;
    case 'destructive':
      return settings.approvalPolicy.destructive;
    case 'system_critical':
      return settings.approvalPolicy.systemCritical;
  }
}

function baseRiskForAction(action: LocalAgentAction): LocalAgentRiskLevel {
  if (action.type === 'filesystem.list' || action.type === 'filesystem.read_text') {
    return 'read_only';
  }

  if (action.type === 'filesystem.trash') {
    return 'destructive';
  }

  if (action.type === 'terminal.exec') {
    const commandLine = [action.command, ...action.args].join(' ');
    if (terminalDestructivePattern.test(commandLine)) {
      return 'destructive';
    }
    if (terminalWritePattern.test(commandLine)) {
      return 'write_safe';
    }
    const commandName = path.basename(action.command);
    if (terminalReadOnlyCommands.has(commandName)) {
      if (action.args.some((arg) => ['-delete', '-exec', '-execdir', '-i', '--in-place'].includes(arg))) {
        return 'write_safe';
      }
      if (commandName === 'git' && !['status', 'diff', 'log', 'show', 'branch'].includes(action.args[0] ?? '')) {
        return 'write_safe';
      }
      if (commandName === 'npm' && !['--version', '-v', 'view', 'list'].includes(action.args[0] ?? '')) {
        return 'write_safe';
      }
      if (commandName === 'node' && !['--version', '-v'].includes(action.args[0] ?? '')) {
        return 'write_safe';
      }
      return 'read_only';
    }
    return 'write_safe';
  }

  return 'write_safe';
}

function touchesProtectedPath(normalizedPath: string, settings: RuntimeLocalAgentSettings) {
  return settings.protectedPaths.some((entry) => {
    const protectedPath = normalizeConfiguredPath(entry);
    if (path.isAbsolute(entry)) {
      return isInside(normalizedPath, protectedPath) || normalizedPath === protectedPath;
    }

    return normalizedPath.includes(`${path.sep}${entry}${path.sep}`) || normalizedPath.endsWith(`${path.sep}${entry}`);
  });
}

export function evaluateLocalAgentAction(action: LocalAgentAction, settings: RuntimeLocalAgentSettings): LocalAgentDecision {
  if (!settings.enabled) {
    return {
      allowed: false,
      riskLevel: 'system_critical',
      approvalLevel: 'TWO_FA',
      reason: 'Local operator is disabled in runtime settings.',
      requiresConfirmation: true,
    };
  }

  const primaryPath = actionPath(action);
  const normalizedPath = normalizeConfiguredPath(primaryPath);
  const allowedRoots = settings.allowedRoots.map(normalizeConfiguredPath);
  const insideAllowedRoot = allowedRoots.some((root) => isInside(normalizedPath, root));

  if (!insideAllowedRoot) {
    return {
      allowed: false,
      riskLevel: 'system_critical',
      approvalLevel: 'TWO_FA',
      reason: 'Action target is outside configured local operator roots.',
      requiresConfirmation: true,
      normalizedPath,
    };
  }

  let riskLevel = baseRiskForAction(action);
  if (touchesProtectedPath(normalizedPath, settings)) {
    riskLevel = riskLevel === 'read_only' ? 'write_sensitive' : 'system_critical';
  }

  if ('targetPath' in action) {
    const normalizedTarget = normalizeConfiguredPath(action.targetPath);
    const targetAllowed = allowedRoots.some((root) => isInside(normalizedTarget, root));
    if (!targetAllowed) {
      return {
        allowed: false,
        riskLevel: 'system_critical',
        approvalLevel: 'TWO_FA',
        reason: 'Action target path is outside configured local operator roots.',
        requiresConfirmation: true,
        normalizedPath,
      };
    }
    if (touchesProtectedPath(normalizedTarget, settings)) {
      riskLevel = 'system_critical';
    }
  }

  const approvalLevel = approvalForRisk(settings, riskLevel);
  const requiresConfirmation = approvalLevel !== 'AUTO';

  return {
    allowed: !requiresConfirmation || action.approved === true,
    riskLevel,
    approvalLevel,
    reason: requiresConfirmation && action.approved !== true
      ? `Action requires ${approvalLevel} approval.`
      : 'Action is allowed by local operator policy.',
    requiresConfirmation,
    normalizedPath,
  };
}
