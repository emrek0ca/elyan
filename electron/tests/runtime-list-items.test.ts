import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';
import { itemsFromRuntimeList } from '../src/renderer/lib/runtime-list-items';
import { ListSurface } from '../src/renderer/panels/ListSurface';

async function renderList(items: ReturnType<typeof itemsFromRuntimeList>): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      createElement(ListSurface, {
        title: 'Liste',
        subtitle: 'runtime truth',
        items,
        loading: false,
        error: '',
        onRefresh: () => undefined,
        onBack: () => undefined,
      }),
    );
    await Promise.resolve();
  });
  return { container, root };
}

describe('runtime list items', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('maps apps list with MCP tool and broken server truth', async () => {
    const items = itemsFromRuntimeList(
      'apps',
      {
        mcpStatus: {
          servers: [
            {
              id: 'mcp_fixture',
              name: 'Fixture Server',
              enabled: true,
              connected: true,
              toolCount: 1,
              lastErrorCode: '',
              lastErrorMessage: '',
            },
            {
              id: 'mcp_invalid',
              name: 'Broken Server',
              enabled: true,
              connected: false,
              toolCount: 0,
              lastErrorCode: 'MCP_SERVER_INVALID',
              lastErrorMessage: 'invalid config',
            },
          ],
          tools: [
            {
              serverId: 'mcp_fixture',
              serverName: 'Fixture Server',
              name: 'echo_readonly',
              description: 'Echo tool',
              readOnly: true,
              available: true,
              availabilityReason: '',
            },
          ],
        },
      },
      null,
    );

    const { container, root } = await renderList(items);

    expect(container.textContent).toContain('echo_readonly');
    expect(container.textContent).toContain('read-only');
    expect(container.textContent).toContain('hazır');
    expect(container.textContent).toContain('Broken Server');
    expect(container.textContent).toContain('Sunucu yapılandırması geçersiz');

    await act(async () => {
      root.unmount();
    });
  });

  it('maps skills list with blocked dependency truth and badges', async () => {
    const items = itemsFromRuntimeList(
      'skills',
      {
        skillStatus: {
          skills: [
            {
              id: 'document.report_from_context',
              name: 'Context Report',
              description: 'DOCX report',
              source: 'local',
              category: 'document',
              requiresConfirmation: true,
              enabled: true,
              available: false,
              lastErrorCode: 'DEPENDENCY_UNAVAILABLE',
              lastErrorMessage: 'missing',
              dependencySummary: {
                blockedCapabilities: ['document_write'],
              },
              path: '/tmp/context-report.json',
            },
          ],
        },
      },
      null,
    );

    const { container, root } = await renderList(items);

    expect(container.textContent).toContain('Context Report');
    expect(container.textContent).toContain('dependency eksik');
    expect(container.textContent).toContain('Bloke: document_write');
    expect(container.textContent).toContain('local');
    expect(container.textContent).toContain('document');
    expect(container.textContent).toContain('onay gerekli');

    await act(async () => {
      root.unmount();
    });
  });

  it('maps task inbox entries with approval and route truth', async () => {
    const items = itemsFromRuntimeList(
      'tasks',
      {
        data: {
          tasks: [
            {
              id: 'task-1',
              title: 'Mobil görev',
              summary: 'Mail gönderimi onay bekliyor.',
              status: 'waiting_approval',
              updatedAt: '2030-05-22T15:31:12Z',
              routeDecision: {
                route: 'desktop_runtime',
              },
              approvalRequest: {
                kind: 'email_send',
              },
              artifactCount: 1,
            },
          ],
        },
      },
      null,
    );

    const { container, root } = await renderList(items);

    expect(container.textContent).toContain('Mobil görev');
    expect(container.textContent).toContain('onay bekliyor');
    expect(container.textContent).toContain('İzin türü: email_send');
    expect(container.textContent).toContain('desktop_runtime');
    expect(container.textContent).toContain('1 artifact');

    await act(async () => {
      root.unmount();
    });
  });
});
