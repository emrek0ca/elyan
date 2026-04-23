export function normalizeWhitespace(value: string): string {
  return value.replace(/\s+/g, ' ').trim();
}

export function extractCheerioText($: unknown): string {
  // The crawler and scraper each carry their own Cheerio typings, so this helper
  // stays structurally loose while keeping the extracted text path deterministic.
  const root: any = $; // eslint-disable-line @typescript-eslint/no-explicit-any

  root('script, style, nav, footer, header, aside, .ad, .advertisement').remove?.();

  const content =
    root('article, main, .content, .post-body, #content')
      .first()
      .text()
      .trim() || root('body').text().trim();

  return normalizeWhitespace(content).slice(0, 8000);
}

export function extractCheerioLinks($: unknown, limit = 20): Array<{ href: string; text: string }> {
  const root: any = $; // eslint-disable-line @typescript-eslint/no-explicit-any

  const links: Array<{ href: string; text: string }> = root('a[href]')
    .toArray()
    .slice(0, limit)
    .map((element: unknown) => {
      const anchor = root(element);
      return {
        href: anchor.attr('href') || '',
        text: normalizeWhitespace(anchor.text()),
      };
    });

  return links.filter((link: { href: string; text: string }) => link.href.length > 0);
}
