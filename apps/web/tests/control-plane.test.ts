import { readFile, writeFile } from 'fs/promises';
import { mkdtemp, rm } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlPlaneService, buildControlPlaneEvaluationSummary } from '@/core/control-plane';

describe('ControlPlaneService', () => {
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
    const dir = await mkdtemp(join(tmpdir(), 'elyan-control-plane-'));
    tempDirs.push(dir);
    return ControlPlaneService.create(join(dir, 'state.json'));
  }

  function getLatestStatePath() {
    const dir = tempDirs[tempDirs.length - 1];
    if (!dir) {
      throw new Error('No active control-plane test directory');
    }

    return join(dir, 'state.json');
  }

  it('exposes a narrow plan catalog with clean boundaries', async () => {
    const service = await createService();
    const plans = await service.listPlans();

    expect(plans).toHaveLength(4);
    expect(plans.find((plan) => plan.id === 'local_byok')?.entitlements.hostedAccess).toBe(false);
    expect(plans.find((plan) => plan.id === 'cloud_assisted')?.entitlements.hostedAccess).toBe(true);
  });

  it('registers identity and binds an account to the owner', async () => {
    const service = await createService();
    const result = await service.registerIdentity({
      email: 'ayla@example.com',
      password: 'very-strong-password',
      displayName: 'Ayla',
      ownerType: 'individual',
      planId: 'cloud_assisted',
    });

    expect(result.user.email).toBe('ayla@example.com');
    expect(result.account.ownerUserId).toBe(result.user.userId);
    expect(result.account.subscription.status).toBe('trialing');
    expect(result.account.balanceCredits).toBe('0.00');
    expect(result.account.entitlements.hostedAccess).toBe(false);
    expect(result.account.usageSnapshot.dailyRequests).toBe(0);
    expect(result.account.usageSnapshot.remainingRequests).toBe(result.account.plan.dailyLimits.hostedRequestsPerDay);
    expect(result.account.usageSnapshot.state).toBe('monthly_credits_exhausted');
  });

  it('activates hosted billing through iyzico webhook and then records usage', async () => {
    const service = await createService();
    await service.upsertAccount('acct_200', {
      displayName: 'Mira',
      ownerType: 'team',
      planId: 'pro_builder',
      billingCustomerRef: 'cust_200',
    });

    await expect(
      service.quoteUsage('acct_200', {
        domain: 'inference',
        units: 10,
        source: 'hosted_api',
      })
    ).rejects.toMatchObject({
      statusCode: 403,
    });

    const activated = await service.applyIyzicoWebhook(
      {
        customerReferenceCode: 'cust_200',
        subscriptionReferenceCode: 'sub_200',
        orderReferenceCode: 'ord_200',
        iyziReferenceCode: 'ref_200',
        iyziEventType: 'subscription.order.success',
        iyziEventTime: Date.now(),
      },
      undefined,
      { bypassSignatureValidation: true }
    );

    expect(activated.account.subscription.status).toBe('active');
    expect(activated.account.entitlements.hostedAccess).toBe(true);
    expect(activated.account.balanceCredits).toBe('5000.00');

    const quote = await service.quoteUsage('acct_200', {
      domain: 'inference',
      units: 10,
      source: 'hosted_api',
    });

    expect(quote.allowed).toBe(true);
    expect(quote.creditsDelta).toBe('9.50');
    expect(quote.balanceAfter).toBe('4990.50');

    const result = await service.recordUsage('acct_200', {
      domain: 'inference',
      units: 10,
      source: 'hosted_api',
      requestId: 'req_1',
    });

    expect(result.account.balanceCredits).toBe('4990.50');
    expect(result.ledgerEntry.kind).toBe('usage_charge');
    expect(result.ledgerEntry.requestId).toBe('req_1');

    const ledger = await service.listLedger('acct_200');
    expect(ledger[0]?.kind).toBe('usage_charge');
  });

  it('treats repeated iyzico success webhooks as idempotent', async () => {
    const service = await createService();
    await service.upsertAccount('acct_201', {
      displayName: 'Nora',
      ownerType: 'individual',
      planId: 'cloud_assisted',
      billingCustomerRef: 'cust_201',
    });

    const payload = {
      customerReferenceCode: 'cust_201',
      subscriptionReferenceCode: 'sub_201',
      orderReferenceCode: 'ord_201',
      iyziReferenceCode: 'ref_201',
      iyziEventType: 'subscription.order.success' as const,
      iyziEventTime: Date.now(),
    };

    const first = await service.applyIyzicoWebhook(payload, undefined, {
      bypassSignatureValidation: true,
    });

    expect(first.applied).toBe(true);
    expect(first.duplicate).toBe(false);
    expect(first.account.balanceCredits).toBe('1000.00');
    expect(first.account.processedWebhookEventCount).toBe(1);

    const duplicate = await service.applyIyzicoWebhook(payload, undefined, {
      bypassSignatureValidation: true,
    });

    expect(duplicate.applied).toBe(false);
    expect(duplicate.duplicate).toBe(true);
    expect(duplicate.ledgerEntry).toBeUndefined();
    expect(duplicate.account.balanceCredits).toBe('1000.00');
    expect(duplicate.account.processedWebhookEventCount).toBe(1);
  });

  it('records hosted usage bundles across multiple buckets', async () => {
    const service = await createService();
    await service.upsertAccount('acct_220', {
      displayName: 'Tara',
      ownerType: 'organization',
      planId: 'cloud_assisted',
      billingCustomerRef: 'cust_220',
    });

    await service.applyIyzicoWebhook(
      {
        customerReferenceCode: 'cust_220',
        subscriptionReferenceCode: 'sub_220',
        orderReferenceCode: 'ord_220',
        iyziReferenceCode: 'ref_220',
        iyziEventType: 'subscription.order.success',
        iyziEventTime: Date.now(),
      },
      undefined,
      { bypassSignatureValidation: true }
    );

    const bundle = await service.recordUsageBundle('acct_220', [
      {
        domain: 'inference',
        units: 2,
        source: 'hosted_web',
        requestId: 'bundle_1',
      },
      {
        domain: 'retrieval',
        units: 3,
        source: 'hosted_web',
        requestId: 'bundle_1',
      },
    ]);

    expect(bundle.account.balanceCredits).toBe('997.70');
    expect(bundle.quotes).toHaveLength(2);
    expect(bundle.quotes[0]?.domain).toBe('inference');
    expect(bundle.quotes[1]?.balanceAfter).toBe('997.70');
    expect(bundle.ledgerEntries).toHaveLength(2);
    expect(bundle.ledgerEntries[0]?.domain).toBe('inference');
    expect(bundle.ledgerEntries[1]?.domain).toBe('retrieval');
  });

  it('records hosted evaluation signals and keeps them persisted in the shared state', async () => {
    const service = await createService();
    const created = await service.registerIdentity({
      email: 'eval@example.com',
      password: 'very-strong-password',
      displayName: 'Eval Owner',
      ownerType: 'individual',
      planId: 'cloud_assisted',
    });

    await service.upsertAccount(created.account.accountId, {
      displayName: created.account.displayName,
      ownerType: created.account.ownerType,
      planId: 'cloud_assisted',
      ownerUserId: created.user.userId,
      billingCustomerRef: 'cust_eval',
    });

    await service.applyIyzicoWebhook(
      {
        customerReferenceCode: 'cust_eval',
        subscriptionReferenceCode: 'sub_eval',
        orderReferenceCode: 'ord_eval',
        iyziReferenceCode: 'ref_eval',
        iyziEventType: 'subscription.order.success',
        iyziEventTime: Date.now(),
      },
      undefined,
      { bypassSignatureValidation: true }
    );

    const signal = await service.recordEvaluationSignal(created.account.accountId, {
      requestId: 'req_eval_1',
      mode: 'research',
      surface: 'hosted',
      model: {
        provider: 'openai',
        modelId: 'gpt-4.1',
      },
      taskIntent: 'research',
      reasoningDepth: 'deep',
      routingMode: 'cloud_preferred',
      intentConfidence: 'high',
      retrieval: {
        shouldRetrieve: true,
        searchAvailable: true,
        rounds: 3,
        maxUrls: 8,
        sourceCount: 2,
        citationCount: 2,
      },
      tooling: {
        enabled: true,
        capabilityIds: ['web_crawl'],
        toolCallCount: 1,
        toolResultCount: 1,
      },
      usage: {
        inputTokens: 120,
        outputTokens: 80,
        totalTokens: 200,
      },
      latencyMs: 1234,
      queryLength: 42,
      answerLength: 180,
      quality: 'good',
      promotionCandidate: false,
      notes: ['captured from hosted answer'],
    });

    expect(signal.accountId).toBe(created.account.accountId);

    const account = await service.getAccount(created.account.accountId);
    expect(account.evaluationSignalCount).toBe(1);
    expect(account.recentEvaluationSignals[0]?.signalId).toBe(signal.signalId);
    expect(account.recentEvaluationSignals[0]?.quality).toBe('good');

    const summary = buildControlPlaneEvaluationSummary(account.recentEvaluationSignals);
    expect(summary.windowCount).toBe(1);
    expect(summary.qualityCounts.good).toBe(1);
    expect(summary.promotionCandidates).toBe(0);
    expect(summary.averageLatencyMs).toBe(1234);
    expect(summary.retrievalCoverageRate).toBe(1);
    expect(summary.toolCompletionRate).toBe(1);

    const reopened = ControlPlaneService.create(join(tempDirs[tempDirs.length - 1] ?? '', 'state.json'));
    const reopenedAccount = await reopened.getAccount(created.account.accountId);
    expect(reopenedAccount.evaluationSignalCount).toBe(1);
    expect(reopenedAccount.recentEvaluationSignals[0]?.requestId).toBe('req_eval_1');
  });

  it('records hosted learning events for dataset generation', async () => {
    const service = await createService();
    const created = await service.registerIdentity({
      email: 'learning@example.com',
      password: 'very-strong-password',
      displayName: 'Learning Owner',
      ownerType: 'individual',
      planId: 'cloud_assisted',
    });

    await service.upsertAccount(created.account.accountId, {
      displayName: created.account.displayName,
      ownerType: created.account.ownerType,
      planId: 'cloud_assisted',
      ownerUserId: created.user.userId,
      billingCustomerRef: 'cust_learning',
    });

    await service.applyIyzicoWebhook(
      {
        customerReferenceCode: 'cust_learning',
        subscriptionReferenceCode: 'sub_learning',
        orderReferenceCode: 'ord_learning',
        iyziReferenceCode: 'ref_learning',
        iyziEventType: 'subscription.order.success',
        iyziEventTime: Date.now(),
      },
      undefined,
      { bypassSignatureValidation: true }
    );

    const event = await service.recordLearningEvent(created.account.accountId, {
      requestId: 'req_learning_1',
      source: 'web',
      input: 'How do I make this response better?',
      intent: 'direct_answer',
      plan: 'intent=direct_answer; routing=local_first; depth=standard',
      reasoningSteps: ['input: How do I make this response better?', 'intent: direct_answer'],
      output: 'Rewrite the answer with clearer steps.',
      success: true,
      latencyMs: 120,
      modelId: 'gpt-4.1',
      modelProvider: 'openai',
      metadata: {
        citationCount: 1,
        toolCallCount: 0,
      },
    });

    expect(event.requestId).toBe('req_learning_1');
    expect(event.score).toBeGreaterThan(0);
    expect(event.accepted).toBe(true);
    expect(event.betterOutput).toEqual(expect.any(String));

    const account = await service.getAccount(created.account.accountId);
    expect(account.learningEventCount).toBe(1);
  });

  it('tracks device link, bootstrap, push, rotate, and unlink transitions without private context leakage', async () => {
    const service = await createService();
    const registration = await service.registerIdentity({
      email: 'device@example.com',
      password: 'very-strong-password',
      displayName: 'Device Owner',
      ownerType: 'individual',
      planId: 'cloud_assisted',
    });

    const link = await service.startDeviceLink(registration.account.accountId, registration.user.userId, {
      deviceLabel: 'Mac Studio',
    });

    const completed = await service.completeDeviceLink({
      linkCode: link.linkCode,
      deviceLabel: 'Mac Studio',
      metadata: {
        platform: 'macOS',
        version: '1.0.0',
      },
    });

    expect(completed.device.deviceToken).toBeDefined();
    expect(completed.device.status).toBe('active');

    const bootstrap = await service.bootstrapDevice(completed.device.deviceToken);
    expect(bootstrap.account.accountId).toBe(registration.account.accountId);
    expect(bootstrap.syncScope.planId).toBe('cloud_assisted');
    expect(bootstrap.release === null || bootstrap.release.complete === true).toBe(true);

    const pushed = await service.pushDevice({
      deviceToken: completed.device.deviceToken,
      metadata: {
        platform: 'macOS',
        version: '1.0.1',
      },
      lastSeenReleaseTag: 'v1.3.0',
    });

    expect(pushed.device.lastSeenReleaseTag).toBe('v1.3.0');
    expect(pushed.device.metadata).toMatchObject({
      platform: 'macOS',
      version: '1.0.1',
    });

    const rotated = await service.rotateDeviceToken(completed.device.deviceToken);
    expect(rotated.device.deviceToken).not.toBe(completed.device.deviceToken);
    expect(rotated.previousDeviceToken).toBe(completed.device.deviceToken);
    expect(rotated.device.metadata).toMatchObject({
      rotationStatus: 'rotated',
      previousTokenFingerprint: completed.device.deviceToken.slice(-8),
    });

    const unlinked = await service.unlinkDevice(rotated.device.deviceToken);
    expect(unlinked.device.status).toBe('revoked');
  });

  it('marks iyzico failures as past due and escalates on repeated retries', async () => {
    const service = await createService();
    const created = await service.registerIdentity({
      email: 'billing@example.com',
      password: 'very-strong-password',
      displayName: 'Billing Owner',
      ownerType: 'individual',
      planId: 'cloud_assisted',
    });

    await service.upsertAccount(created.account.accountId, {
      displayName: created.account.displayName,
      ownerType: created.account.ownerType,
      planId: 'cloud_assisted',
      ownerUserId: created.user.userId,
      billingCustomerRef: 'cust_fail',
    });

    await service.applyIyzicoWebhook(
      {
        customerReferenceCode: 'cust_fail',
        subscriptionReferenceCode: 'sub_fail_1',
        orderReferenceCode: 'ord_fail_1',
        iyziReferenceCode: 'ref_fail_1',
        iyziEventType: 'subscription.order.failure',
        iyziEventTime: Date.now(),
      },
      undefined,
      { bypassSignatureValidation: true }
    );

    const firstFailure = await service.getAccount(created.account.accountId);
    expect(firstFailure.subscription.status).toBe('past_due');
    expect(firstFailure.entitlements.hostedAccess).toBe(false);
    expect(firstFailure.subscription.retryCount).toBe(1);

    await service.applyIyzicoWebhook(
      {
        customerReferenceCode: 'cust_fail',
        subscriptionReferenceCode: 'sub_fail_1',
        orderReferenceCode: 'ord_fail_1',
        iyziReferenceCode: 'ref_fail_1',
        iyziEventType: 'subscription.order.failure',
        iyziEventTime: Date.now(),
      },
      undefined,
      { bypassSignatureValidation: true }
    );

    const duplicateFailure = await service.getAccount(created.account.accountId);
    expect(duplicateFailure.subscription.retryCount).toBe(1);
    expect(duplicateFailure.subscription.status).toBe('past_due');

    await service.applyIyzicoWebhook(
      {
        customerReferenceCode: 'cust_fail',
        subscriptionReferenceCode: 'sub_fail_1',
        orderReferenceCode: 'ord_fail_2',
        iyziReferenceCode: 'ref_fail_2',
        iyziEventType: 'subscription.order.failure',
        iyziEventTime: Date.now(),
      },
      undefined,
      { bypassSignatureValidation: true }
    );

    await service.applyIyzicoWebhook(
      {
        customerReferenceCode: 'cust_fail',
        subscriptionReferenceCode: 'sub_fail_1',
        orderReferenceCode: 'ord_fail_3',
        iyziReferenceCode: 'ref_fail_3',
        iyziEventType: 'subscription.order.failure',
        iyziEventTime: Date.now(),
      },
      undefined,
      { bypassSignatureValidation: true }
    );

    const suspended = await service.getAccount(created.account.accountId);
    expect(suspended.subscription.status).toBe('suspended');
  });

  it('rejects hosted usage for local-only plans', async () => {
    const service = await createService();
    await service.upsertAccount('acct_300', {
      displayName: 'Local Only',
      ownerType: 'individual',
      planId: 'local_byok',
    });

    await expect(
      service.recordUsage('acct_300', {
        domain: 'inference',
        units: 1,
        source: 'hosted_api',
      })
      ).rejects.toMatchObject({
      statusCode: 403,
    });
  });

  it('rejects hosted usage when the daily request limit is exhausted', async () => {
    const service = await createService();
    const created = await service.registerIdentity({
      email: 'limit@example.com',
      password: 'very-strong-password',
      displayName: 'Limit Owner',
      ownerType: 'individual',
      planId: 'cloud_assisted',
    });

    await service.upsertAccount(created.account.accountId, {
      displayName: created.account.displayName,
      ownerType: created.account.ownerType,
      planId: 'cloud_assisted',
      ownerUserId: created.user.userId,
      billingCustomerRef: 'cust_limit',
    });

    await service.applyIyzicoWebhook(
      {
        customerReferenceCode: 'cust_limit',
        subscriptionReferenceCode: 'sub_limit',
        orderReferenceCode: 'ord_limit',
        iyziReferenceCode: 'ref_limit',
        iyziEventType: 'subscription.order.success',
        iyziEventTime: Date.now(),
      },
      undefined,
      { bypassSignatureValidation: true }
    );

    const statePath = getLatestStatePath();
    const rawState = JSON.parse(await readFile(statePath, 'utf8'));
    const account = rawState.accounts[created.account.accountId];

    account.usageSnapshot = {
      ...account.usageSnapshot,
      dailyRequests: account.usageSnapshot.dailyRequestsLimit,
      remainingRequests: 0,
      dailyHostedToolActionCalls: 0,
      remainingHostedToolActionCalls: account.usageSnapshot.dailyHostedToolActionCallsLimit,
      monthlyCreditsRemaining: account.balanceCredits,
      monthlyCreditsBurned: '0.00',
      state: 'daily_limit_reached',
    };

    await writeFile(statePath, `${JSON.stringify(rawState, null, 2)}\n`, 'utf8');

    await expect(
      service.recordUsage(created.account.accountId, {
        domain: 'inference',
        units: 1,
        source: 'hosted_api',
      })
    ).rejects.toMatchObject({
      statusCode: 429,
    });
  });

  it('resets the usage snapshot when the day key rolls over', async () => {
    const service = await createService();
    const created = await service.registerIdentity({
      email: 'reset@example.com',
      password: 'very-strong-password',
      displayName: 'Reset Owner',
      ownerType: 'individual',
      planId: 'cloud_assisted',
    });

    await service.upsertAccount(created.account.accountId, {
      displayName: created.account.displayName,
      ownerType: created.account.ownerType,
      planId: 'cloud_assisted',
      ownerUserId: created.user.userId,
      billingCustomerRef: 'cust_reset',
    });

    await service.applyIyzicoWebhook(
      {
        customerReferenceCode: 'cust_reset',
        subscriptionReferenceCode: 'sub_reset',
        orderReferenceCode: 'ord_reset',
        iyziReferenceCode: 'ref_reset',
        iyziEventType: 'subscription.order.success',
        iyziEventTime: Date.now(),
      },
      undefined,
      { bypassSignatureValidation: true }
    );

    const statePath = getLatestStatePath();
    const rawState = JSON.parse(await readFile(statePath, 'utf8'));
    const account = rawState.accounts[created.account.accountId];
    account.usageSnapshot = {
      ...account.usageSnapshot,
      dayKey: '2001-01-01',
      dailyRequests: account.usageSnapshot.dailyRequestsLimit,
      remainingRequests: 0,
      dailyHostedToolActionCalls: account.usageSnapshot.dailyHostedToolActionCallsLimit,
      remainingHostedToolActionCalls: 0,
      state: 'daily_limit_reached',
      resetAt: new Date().toISOString(),
    };
    await writeFile(statePath, `${JSON.stringify(rawState, null, 2)}\n`, 'utf8');

    const accountView = await service.getAccount(created.account.accountId);
    expect(accountView.usageSnapshot.dailyRequests).toBe(0);
    expect(accountView.usageSnapshot.remainingRequests).toBe(accountView.plan.dailyLimits.hostedRequestsPerDay);
    expect(accountView.usageSnapshot.state).toBe('ok');
  });

  it('persists state to disk for the shared control plane', async () => {
    const service = await createService();
    const created = await service.registerIdentity({
      email: 'persisted@example.com',
      password: 'very-strong-password',
      displayName: 'Persisted',
      ownerType: 'organization',
      planId: 'team_business',
    });

    const reopened = ControlPlaneService.create(join(tempDirs[tempDirs.length - 1] ?? '', 'state.json'));
    const account = await reopened.getAccount(created.account.accountId);

    expect(account.subscription.planId).toBe('team_business');
    expect(account.subscription.status).toBe('trialing');
    expect(account.ownerUserId).toBe(created.user.userId);
  });

  it('reports a compact control-plane runtime snapshot for the hosted bridge', async () => {
    const service = await createService();
    const health = await service.health();

    expect(health.runtime).toMatchObject({
      surface: 'shared-vps',
      storage: 'file',
      billingMode: 'sandbox',
      callbackUrl: expect.stringContaining('/api/control-plane/billing/iyzico/webhook'),
    });
    expect(health.connection).toMatchObject({
      storage: 'file',
      billingMode: 'sandbox',
      callbackUrl: expect.stringContaining('/api/control-plane/billing/iyzico/webhook'),
    });
    expect(health.readiness).toMatchObject({
      database: false,
      auth: false,
      billing: false,
      hosted: false,
    });
    expect(health.counts).toMatchObject({
      accounts: 0,
      users: 0,
      devices: 0,
      deviceLinks: 0,
      ledgerEntries: 0,
    });
    expect(health.database).toMatchObject({
      storage: 'file',
      mode: 'file_backed',
      configured: false,
      ready: true,
    });
    expect(health.database.detail).toContain('File-backed state store is active');
    expect(health.syncSummary).toMatchObject({
      subscriptions: {
        total: 0,
        trialing: 0,
        active: 0,
        past_due: 0,
        suspended: 0,
        canceled: 0,
        unbound: 0,
        pending: 0,
        synced: 0,
        failed: 0,
        ready: 0,
        billingPending: 0,
        syncFailed: 0,
      },
      devices: {
        total: 0,
        pending: 0,
        active: 0,
        revoked: 0,
        expired: 0,
      },
    });
    expect(health.evaluationSummary).toMatchObject({
      windowCount: 0,
      promotionCandidates: 0,
      qualityCounts: {
        good: 0,
        mixed: 0,
        poor: 0,
        skipped: 0,
      },
    });
  });
});
