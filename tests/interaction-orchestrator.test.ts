import { mkdtemp, rm } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlPlaneService } from '@/core/control-plane';
import { classifyInteractionIntent } from '@/core/interaction/intent';

describe('Interaction orchestrator primitives', () => {
  const tempDirs: string[] = [];

  afterEach(async () => {
    while (tempDirs.length > 0) {
      const dir = tempDirs.pop();
      if (dir) {
        await rm(dir, { recursive: true, force: true });
      }
    }
  });

  async function createService() {
    const dir = await mkdtemp(join(tmpdir(), 'elyan-interaction-'));
    tempDirs.push(dir);
    return ControlPlaneService.create(join(dir, 'state.json'));
  }

  it('classifies backend intent without relying on the UI mode', () => {
    expect(classifyInteractionIntent('What changed in AI search this week?').intent).toBe('research');
    expect(classifyInteractionIntent('Rename the report file and move it into the workspace').intent).toBe('tool_action');
    expect(classifyInteractionIntent('Refactor the repo and update tests for the code path').intent).toBe('tool_action');
    expect(classifyInteractionIntent('Draft a design brief in markdown for the product UI').intent).toBe('tool_action');
    expect(classifyInteractionIntent('What about caching?').intent).toBe('follow_up_question');
    expect(classifyInteractionIntent('Give me a direct answer').intent).toBe('direct_answer');
  });

  it('persists interaction memory and rebuilds context from the control plane', async () => {
    const service = await createService();
    const created = await service.registerIdentity({
      email: 'memory@example.com',
      password: 'very-strong-password',
      displayName: 'Memory Owner',
      ownerType: 'individual',
      planId: 'local_byok',
    });

    await service.recordInteraction(created.account.accountId, {
      source: 'web',
      query: 'Remember that I prefer short answers and concise formatting.',
      responseText: 'Noted.',
      mode: 'speed',
      intent: 'direct_answer',
      confidence: 'high',
      conversationId: 'thread-1',
      messageId: 'msg-1',
      userId: created.user.userId,
      displayName: created.user.displayName,
      modelId: 'local-test-model',
      metadata: {
        surface: 'web',
      },
      sources: [],
      citationCount: 0,
    });

    await service.recordInteraction(created.account.accountId, {
      source: 'web',
      query: 'Research the latest local storage patterns and cite them.',
      responseText: 'Pattern summary [1]',
      mode: 'research',
      intent: 'research',
      confidence: 'high',
      conversationId: 'thread-2',
      messageId: 'msg-2',
      userId: created.user.userId,
      displayName: created.user.displayName,
      modelId: 'local-test-model',
      metadata: {
        surface: 'web',
      },
      sources: [{ url: 'https://example.com', title: 'Example' }],
      citationCount: 1,
    });

    const account = await service.getAccount(created.account.accountId);
    expect(account.interactionSummary.threadCount).toBe(2);
    expect(account.interactionSummary.messageCount).toBe(4);
    expect(account.interactionSummary.memoryItemCount).toBe(2);
    expect(account.interactionSummary.learningDraftCount).toBe(1);
    expect(account.recentLearningDrafts[0]?.status).toBe('draft');

    const context = await service.getInteractionContext(created.account.accountId, {
      query: 'short answers',
      source: 'web',
      conversationId: 'thread-1',
    });

    expect(context.contextBlocks.join('\n')).toContain('short answers');
    expect(context.memoryItems.length).toBeGreaterThan(0);
  });

  it('promotes a learning draft into long-lived memory', async () => {
    const service = await createService();
    const created = await service.registerIdentity({
      email: 'promote@example.com',
      password: 'very-strong-password',
      displayName: 'Promote Owner',
      ownerType: 'individual',
      planId: 'local_byok',
    });

    const interaction = await service.recordInteraction(created.account.accountId, {
      source: 'web',
      query: 'Research the latest local storage patterns and cite them.',
      responseText: 'Pattern summary [1]',
      mode: 'research',
      intent: 'research',
      confidence: 'high',
      conversationId: 'thread-3',
      messageId: 'msg-3',
      userId: created.user.userId,
      displayName: created.user.displayName,
      modelId: 'local-test-model',
      metadata: {
        surface: 'web',
      },
      sources: [{ url: 'https://example.com', title: 'Example' }],
      citationCount: 1,
    });

    expect(interaction.learningDraft).toBeDefined();
    const promoted = await service.promoteLearningDraft(created.account.accountId, interaction.learningDraft!.draftId);

    expect(promoted.draft.status).toBe('promoted');
    expect(promoted.memoryItem.promoted).toBe(true);

    const account = await service.getAccount(created.account.accountId);
    expect(account.interactionSummary.memoryItemCount).toBe(2);
    expect(account.interactionSummary.learningDraftCount).toBe(1);
  });
});
