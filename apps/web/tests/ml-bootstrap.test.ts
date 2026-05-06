import { describe, expect, it } from 'vitest';
import { chunkBootstrapText, cleanBootstrapText } from '@/core/ml';

describe('ml bootstrap pipeline', () => {
  it('cleans html and extracts readable bootstrap text', () => {
    const cleaned = cleanBootstrapText(`
      <html>
        <head><title>Ignored</title><style>body { color: red; }</style></head>
        <body>
          <script>window.__noise = true;</script>
          <main>
            <h1>Common Crawl sample</h1>
            <p>Filtered bootstrap text.</p>
          </main>
        </body>
      </html>
    `);

    expect(cleaned).toContain('Common Crawl sample');
    expect(cleaned).toContain('Filtered bootstrap text.');
    expect(cleaned).not.toContain('window.__noise');
    expect(cleaned).not.toContain('body { color: red; }');
  });

  it('chunks long bootstrap text with overlap', () => {
    const text = Array.from({ length: 200 }, (_, index) => `token${index}`).join(' ');
    const chunks = chunkBootstrapText(text, 120, 20);

    expect(chunks.length).toBeGreaterThan(1);
    expect(chunks[0]).toContain('token0');
    expect(chunks[chunks.length - 1]).toContain('token199');
  });
});
