import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';
import { BlockListRenderer } from '../../src/renderer/chat/blocks/BlockRenderer';

describe('backend block renderer parity', () => {
  it('renders every elyan_blocks.v2 surface without unsupported fallbacks', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(<BlockListRenderer
        blocks={[
          { type: 'summary', summary: 'Özet' },
          { type: 'next_steps', title: 'Sonraki adımlar', items: ['Devam et'] },
          { type: 'status', title: 'Durum', status: 'running', summary: 'Sürüyor' },
          { type: 'security_decision', title: 'Güvenlik', summary: 'Onay gerekli' },
          { type: 'info_card', title: 'Bilgi', summary: 'Hazır' },
          { type: 'web_search', query: 'Elyan', results: [{ title: 'Kaynak', url: 'https://example.com' }] },
          { type: 'math', content: 'x^2', result: '4' },
          { type: 'math_surface_3d', expression: 'x+y' },
          { type: 'svg', title: 'Şema', svg: '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><circle cx="5" cy="5" r="4"/></svg>' },
          { type: 'actionable', title: 'Onay', detail: 'Devam et' },
          { type: 'block_group', title: 'Grup', children: [{ type: 'text', markdown: 'İçerik' }] },
          { type: 'document_block', title: 'Belge', sections: [{ heading: 'Başlık', content: 'Metin' }] },
          { type: 'attachment_ack', summary: 'Dosya alındı', attachmentCount: 1 },
          { type: 'image_analysis', description: 'Görsel açıklaması', detectedText: 'OCR metni' },
          { type: 'chart', chartType: 'bar', labels: ['A'], values: [3] },
        ]}
      />);
    });

    expect(container.textContent).not.toMatch(/desktop sürümünde desteklenmiyor/i);
    expect(container.textContent).toContain('Belge');
    expect(container.textContent).toContain('Kaynak');
    expect(container.querySelector('img[alt="Şema"]')?.getAttribute('src')).not.toContain('script');
    await act(async () => root.unmount());
    container.remove();
  });
});
