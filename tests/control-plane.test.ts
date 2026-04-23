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

    const reopened = ControlPlaneService.create(join(tempDirs[tempDirs.length - 1] ?? '', 'state.json'));
    const reopenedAccount = await reopened.getAccount(created.account.accountId);
    expect(reopenedAccount.evaluationSignalCount).toBe(1);
    expect(reopenedAccount.recentEvaluationSignals[0]?.requestId).toBe('req_eval_1');
  });

  it('tracks device link, bootstrap, push, and unlink transitions without private context leakage', async () => {
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
      lastSeenReleaseTag: 'v1.2.0',
    });

    expect(pushed.device.lastSeenReleaseTag).toBe('v1.2.0');
    expect(pushed.device.metadata).toMatchObject({
      platform: 'macOS',
      version: '1.0.1',
    });

    const unlinked = await service.unlinkDevice(completed.device.deviceToken);
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
  });
});
