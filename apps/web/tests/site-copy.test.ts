import { describe, expect, it } from 'vitest';
import { docSections, pricingCards, publicFaq } from '@/content/site';

describe('site copy boundaries', () => {
  it('keeps hosted panel copy focused on hosted account state', () => {
    const faq = publicFaq.find((entry) => entry.question === 'What does the hosted panel show?');

    expect(faq?.answer).toContain('linked device state');
    expect(faq?.answer).not.toContain('interaction drafts');
  });

  it('describes hosted pricing as elyan.dev access, not runtime replacement', () => {
    const hostedPlan = pricingCards.find((entry) => entry.id === 'cloud_assisted');

    expect(hostedPlan?.summary).toContain('elyan.dev');
    expect(hostedPlan?.summary).not.toContain('runtime replacement');
  });

  it('describes the hosted account docs as shared control-plane state', () => {
    const hostedAccountSection = docSections.find((entry) => entry.slug === 'hosted-account');

    expect(hostedAccountSection?.body.join(' ')).toContain('device links');
    expect(hostedAccountSection?.body.join(' ')).toContain('local private runtime memory');
  });

  it('mentions workspace surfaces and voice in the optional integrations copy', () => {
    const optionalIntegrationsSection = docSections.find((entry) => entry.slug === 'search-and-mcp');

    expect(optionalIntegrationsSection?.body.join(' ')).toContain('Workspace surfaces');
    expect(optionalIntegrationsSection?.body.join(' ')).toContain('Voice input');
  });
});
