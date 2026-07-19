import assert from "node:assert/strict";
import test from "node:test";
import { isInternalRoutingSummary, syncChatTaskLifecycle } from "./task-sync.js";

test("isInternalRoutingSummary catches dispatch routing-phrase variants", () => {
  // Kullanıcının #1 şikâyeti: "…desktopa yönlendirildi" gibi iç yönlendirme
  // cümleleri asistan cevabı gibi sızıyordu. Tüm varyantlar elenmeli.
  for (const phrase of [
    "Görev desktopa yönlendirildi.",
    "Görev masaüstüne yönlendirildi.",
    "Kullanıcı dispatch butonu ile bu görevi masaüstüne yönlendirdi.",
    "gorev desktopa yonlendirildi",
  ]) {
    assert.equal(isInternalRoutingSummary(phrase), true, phrase);
  }
});

test("isInternalRoutingSummary keeps genuine assistant answers", () => {
  for (const phrase of [
    "Fatura indirildi ve masaüstüne kaydedildi.",
    "3 adım tamamlandı: Chrome açıldı, PDF kaydedildi.",
    "Son dört e-postanın özeti hazır.",
  ]) {
    assert.equal(isInternalRoutingSummary(phrase), false, phrase);
  }
});

test("syncChatTaskLifecycle ignores non-chat tasks", async () => {
  const updates: Array<Record<string, unknown>> = [];
  const app = {
    config: {
      ELYAN_BLOCKS_V11_ENABLED: false,
    },
    db: {
      update() {
        return {
          set(values: Record<string, unknown>) {
            updates.push(values);
            return {
              where() {
                return {
                  returning: async () => [],
                };
              },
            };
          },
        };
      },
    },
    services: {
      eventBus: {
        publish() {
          throw new Error("should not publish");
        },
      },
    },
  };

  await syncChatTaskLifecycle(app as never, {
    originalTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "device-1",
      payload: { prompt: "hello" },
    } as never,
    updatedTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "device-1",
      status: "completed",
      payload: { prompt: "hello" },
      result: { text: "hi" },
    } as never,
  });

  assert.equal(updates.length, 0);
});

test("syncChatTaskLifecycle publishes running assistant snapshots for chat tasks", async () => {
  const updates: Array<Record<string, unknown>> = [];
  const published: Array<{
    topic?: string;
    payload?: Record<string, unknown>;
  }> = [];
  const app = {
    config: {
      ELYAN_BLOCKS_V11_ENABLED: false,
    },
    db: {
      update() {
        return {
          set(values: Record<string, unknown>) {
            updates.push(values);
            return {
              where() {
                return {
                  returning: async () => [
                    {
                      id: "assistant-1",
                      sessionId: "session-1",
                      userId: "user-1",
                      taskId: "task-1",
                      role: "assistant",
                      status: "running",
                      content: "",
                      error: null,
                    },
                  ],
                };
              },
            };
          },
        };
      },
    },
    services: {
      eventBus: {
        publish(event: Record<string, unknown>) {
          published.push({
            topic: typeof event.topic === "string" ? event.topic : undefined,
            payload:
              event.payload && typeof event.payload === "object" && !Array.isArray(event.payload)
                ? (event.payload as Record<string, unknown>)
                : undefined,
          });
        },
      },
    },
  };

  await syncChatTaskLifecycle(app as never, {
    originalTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "device-1",
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
    } as never,
    updatedTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "device-1",
      title: "hello",
      status: "running",
      queuePosition: 1,
      requestedCapabilities: [],
      createdAt: new Date("2026-01-01T12:00:00.000Z"),
      updatedAt: new Date("2026-01-01T12:00:01.000Z"),
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
    } as never,
  });

  assert.equal(updates.length, 2);
  assert.equal(updates[0]?.status, "running");
  assert.equal(updates[0]?.content, "");
  assert.equal(published.length, 1);
  assert.equal(published[0]?.topic, "chat.message.updated");
  const runningPayload = published[0]?.payload as
    | {
        sessionId?: string;
        presentation?: string;
        taskStatus?: string;
        assistantMessage?: {
          id?: string;
          status?: string;
          blocks?: unknown;
        };
      }
    | undefined;
  assert.equal(runningPayload?.sessionId, "session-1");
  assert.equal(runningPayload?.presentation, "chat");
  assert.equal(runningPayload?.taskStatus, "running");
  assert.equal(runningPayload?.assistantMessage?.id, "assistant-1");
  assert.equal(runningPayload?.assistantMessage?.status, "running");
  const runningBlocks = runningPayload?.assistantMessage?.blocks as
    | Array<Record<string, unknown>>
    | undefined;
  assert.equal(runningBlocks?.length ?? 0, 0);
});

test("syncChatTaskLifecycle uses approval message for waiting approval chat snapshots", async () => {
  const updates: Array<Record<string, unknown>> = [];
  const app = {
    config: {
      ELYAN_BLOCKS_V11_ENABLED: false,
    },
    db: {
      update() {
        return {
          set(values: Record<string, unknown>) {
            updates.push(values);
            return {
              where() {
                return {
                  returning: async () => [
                    {
                      id: "assistant-1",
                      sessionId: "session-1",
                      userId: "user-1",
                      taskId: "task-1",
                      role: "assistant",
                      status: "waiting_approval",
                      content: values.content,
                      error: null,
                    },
                  ],
                };
              },
            };
          },
        };
      },
    },
    services: {
      eventBus: {
        publish() {
          return;
        },
      },
    },
  };

  await syncChatTaskLifecycle(app as never, {
    originalTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "device-1",
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
    } as never,
    updatedTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "device-1",
      status: "waiting_approval",
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
      summary: "Genel onay özeti",
      approvalRequest: {
        title: "Mail gönderilsin mi?",
        message: "Alıcı: ali@example.com\nKonu: Atatürk hakkında notlar",
        summary: "Atatürk araştırması sonrası mail gönderimi onay bekliyor.",
      },
    } as never,
  });

  assert.equal(updates[0]?.status, "waiting_approval");
  assert.equal(updates[0]?.content, "Alıcı: ali@example.com\nKonu: Atatürk hakkında notlar");
});

test("syncChatTaskLifecycle prefers resume summary for approved waiting approval snapshots", async () => {
  const updates: Array<Record<string, unknown>> = [];
  const app = {
    config: {
      ELYAN_BLOCKS_V11_ENABLED: false,
    },
    db: {
      update() {
        return {
          set(values: Record<string, unknown>) {
            updates.push(values);
            return {
              where() {
                return {
                  returning: async () => [
                    {
                      id: "assistant-1",
                      sessionId: "session-1",
                      userId: "user-1",
                      taskId: "task-1",
                      role: "assistant",
                      status: "waiting_approval",
                      content: values.content,
                      error: null,
                    },
                  ],
                };
              },
            };
          },
        };
      },
    },
    services: {
      eventBus: {
        publish() {
          return;
        },
      },
    },
  };

  await syncChatTaskLifecycle(app as never, {
    originalTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "device-1",
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
    } as never,
    updatedTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "device-1",
      status: "waiting_approval",
      summary: "Onay alındı. Görev devam ediyor.",
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
      approvalRequest: {
        title: "Mail gönderilsin mi?",
        message: "Alıcı: ali@example.com\nKonu: Atatürk hakkında notlar",
        resolution: {
          approved: true,
          status: "approved",
        },
      },
    } as never,
  });

  assert.equal(updates[0]?.status, "waiting_approval");
  assert.equal(updates[0]?.content, "Onay alındı. Görev devam ediyor.");
});

test("syncChatTaskLifecycle publishes completed assistant blocks with the task snapshot", async () => {
  const updates: Array<Record<string, unknown>> = [];
  const published: Array<{
    topic?: string;
    payload?: Record<string, unknown>;
  }> = [];
  const app = {
    config: {
      ELYAN_BLOCKS_V11_ENABLED: false,
    },
    db: {
      update() {
        return {
          set(values: Record<string, unknown>) {
            updates.push(values);
            return {
              where() {
                return {
                  returning: async () => [
                    {
                      id: "assistant-1",
                      sessionId: "session-1",
                      userId: "user-1",
                      taskId: "task-1",
                      role: "assistant",
                      status: values.status,
                      content: values.content,
                      error: values.error ?? null,
                    },
                  ],
                };
              },
            };
          },
        };
      },
    },
    services: {
      eventBus: {
        publish(event: Record<string, unknown>) {
          published.push({
            topic: typeof event.topic === "string" ? event.topic : undefined,
            payload:
              event.payload && typeof event.payload === "object" && !Array.isArray(event.payload)
                ? (event.payload as Record<string, unknown>)
                : undefined,
          });
        },
      },
    },
  };

  await syncChatTaskLifecycle(app as never, {
    originalTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "shared-brain-device",
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
    } as never,
    updatedTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "shared-brain-device",
      title: "Selam",
      status: "completed",
      queuePosition: 0,
      requestedCapabilities: [],
      summary: "Kısa özet",
      result: {
        text: "Merhaba, nasıl yardımcı olabilirim?",
        renderRecipe: {
          output_type: "document_render_recipe",
          format: "pdf",
          render_on: "mobile",
        },
      },
      createdAt: new Date("2026-01-01T12:00:00.000Z"),
      updatedAt: new Date("2026-01-01T12:00:02.000Z"),
      completedAt: new Date("2026-01-01T12:00:02.000Z"),
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
    } as never,
  });

  assert.equal(updates[0]?.status, "completed");
  assert.equal(updates[0]?.content, "Merhaba, nasıl yardımcı olabilirim?");
  assert.equal(published.length, 1);
  assert.equal(published[0]?.topic, "chat.message.updated");
  const completedPayload = published[0]?.payload as
    | {
        sessionId?: string;
        presentation?: string;
        taskStatus?: string;
        assistantMessage?: {
          content?: string;
          blocks?: unknown;
        };
      }
    | undefined;
  assert.equal(completedPayload?.sessionId, "session-1");
  assert.equal(completedPayload?.presentation, "chat");
  assert.equal(completedPayload?.taskStatus, "completed");
  assert.equal(completedPayload?.assistantMessage?.content, undefined);
  const completedBlocks = completedPayload?.assistantMessage?.blocks as
    | Array<Record<string, unknown>>
    | undefined;
  assert.equal(completedBlocks?.length, 1);
  assert.equal(completedBlocks?.[0]?.type, "text");
  assert.equal(completedBlocks?.[0]?.markdown, "Merhaba, nasıl yardımcı olabilirim?");
});

test("syncChatTaskLifecycle strips internal analysis from completed assistant snapshots", async () => {
  const published: Array<{
    topic?: string;
    payload?: Record<string, unknown>;
  }> = [];
  const app = {
    config: {
      ELYAN_BLOCKS_V11_ENABLED: false,
    },
    db: {
      update() {
        return {
          set(values: Record<string, unknown>) {
            return {
              where() {
                return {
                  returning: async () => [
                    {
                      id: "assistant-1",
                      sessionId: "session-1",
                      userId: "user-1",
                      taskId: "task-1",
                      role: "assistant",
                      status: values.status,
                      content: values.content,
                      error: values.error ?? null,
                    },
                  ],
                };
              },
            };
          },
        };
      },
    },
    services: {
      eventBus: {
        publish(event: Record<string, unknown>) {
          published.push({
            topic: typeof event.topic === "string" ? event.topic : undefined,
            payload:
              event.payload && typeof event.payload === "object" && !Array.isArray(event.payload)
                ? (event.payload as Record<string, unknown>)
                : undefined,
          });
        },
      },
    },
  };

  await syncChatTaskLifecycle(app as never, {
    originalTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "shared-brain-device",
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
    } as never,
    updatedTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "shared-brain-device",
      title: "Belge sorusu",
      status: "completed",
      queuePosition: 0,
      requestedCapabilities: [],
      summary: "Kısa özet",
      result: {
        text: `- User says: "Ne yazıyor burada"
- Language: Turkish
- Attachment context shows:
- OCR/Summary text: "10:03 cku.itiraf.paylasim •II = 37"

Final answer: Görselde okunan metin kabaca "10:03 cku.itiraf.paylasim •II = 37" diye başlıyor.`,
      },
      createdAt: new Date("2026-01-01T12:00:00.000Z"),
      updatedAt: new Date("2026-01-01T12:00:02.000Z"),
      completedAt: new Date("2026-01-01T12:00:02.000Z"),
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
    } as never,
  });

  const completedPayload = published[0]?.payload as
    | {
        assistantMessage?: {
          content?: string;
          blocks?: Array<{ type?: string; markdown?: string }>;
        };
      }
    | undefined;

  assert.equal(
    completedPayload?.assistantMessage?.content,
    undefined,
  );
  assert.equal(
    completedPayload?.assistantMessage?.blocks?.[0]?.markdown,
    'Görselde okunan metin kabaca "10:03 cku.itiraf.paylasim •II = 37" diye başlıyor.',
  );
});

test("syncChatTaskLifecycle emits phased v1.1 summary blocks when enabled", async () => {
  const published: Array<Record<string, unknown>> = [];
  const app = {
    config: {
      ELYAN_BLOCKS_V11_ENABLED: true,
    },
    db: {
      update() {
        return {
          set(values: Record<string, unknown>) {
            return {
              where() {
                return {
                  returning: async () => [
                    {
                      id: "assistant-1",
                      sessionId: "session-1",
                      userId: "user-1",
                      taskId: "task-1",
                      role: "assistant",
                      status: values.status,
                      content: values.content,
                      error: values.error ?? null,
                    },
                  ],
                };
              },
            };
          },
        };
      },
    },
    services: {
      eventBus: {
        publish(event: Record<string, unknown>) {
          published.push(event);
        },
      },
    },
  };

  await syncChatTaskLifecycle(app as never, {
    originalTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "device-1",
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
    } as never,
    updatedTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "device-1",
      title: "Raporu özetle",
      status: "completed",
      queuePosition: 0,
      requestedCapabilities: [],
      result: {
        text: "Teslim tarihi iki hafta kaymış görünüyor. Ayrıntılı açıklama aşağıda.",
      },
      createdAt: new Date("2026-01-01T12:00:00.000Z"),
      updatedAt: new Date("2026-01-01T12:00:02.000Z"),
      completedAt: new Date("2026-01-01T12:00:02.000Z"),
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
    } as never,
  });

  const payload = published[0]?.payload as
    | {
        assistantMessage?: { blocks?: Array<Record<string, unknown>> };
      }
    | undefined;
  const blocks = payload?.assistantMessage?.blocks ?? [];
  assert.equal(blocks[0]?.type, "summary");
  assert.equal(blocks[1]?.type, "text");
});

test("syncChatTaskLifecycle preserves typed result blocks even when v1.1 chrome is disabled", async () => {
  const published: Array<Record<string, unknown>> = [];
  const app = {
    config: {
      ELYAN_BLOCKS_V11_ENABLED: false,
    },
    db: {
      update() {
        return {
          set(values: Record<string, unknown>) {
            return {
              where() {
                return {
                  returning: async () => [
                    {
                      id: "assistant-1",
                      sessionId: "session-1",
                      userId: "user-1",
                      taskId: "task-1",
                      role: "assistant",
                      status: values.status,
                      content: values.content,
                      error: values.error ?? null,
                    },
                  ],
                };
              },
            };
          },
        };
      },
    },
    services: {
      eventBus: {
        publish(event: Record<string, unknown>) {
          published.push(event);
        },
      },
    },
  };

  await syncChatTaskLifecycle(app as never, {
    originalTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "device-1",
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
    } as never,
    updatedTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "device-1",
      title: "Haftalık rapor",
      status: "completed",
      queuePosition: 0,
      requestedCapabilities: [],
      summary: "Belge hazır.",
      result: {
        text: "",
        assistantBlocks: [
          {
            type: "document_block",
            title: "Haftalık Rapor",
            sections: [{ heading: "Özet", content: "Teslim edildi." }],
          },
        ],
      },
      createdAt: new Date("2026-01-01T12:00:00.000Z"),
      updatedAt: new Date("2026-01-01T12:00:02.000Z"),
      completedAt: new Date("2026-01-01T12:00:02.000Z"),
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
    } as never,
  });

  const payload = published[0]?.payload as
    | {
        assistantMessage?: { blocks?: Array<Record<string, unknown>> };
      }
    | undefined;
  const blocks = payload?.assistantMessage?.blocks ?? [];
  assert.equal(blocks[0]?.type, "document_block");
  assert.equal(blocks.length, 2);
  assert.equal(blocks[1]?.type, "text");
});

test("syncChatTaskLifecycle carries generated image artifact blocks to chat surface", async () => {
  const published: Array<Record<string, unknown>> = [];
  const app = {
    config: {
      ELYAN_BLOCKS_V11_ENABLED: false,
    },
    db: {
      update() {
        return {
          set(values: Record<string, unknown>) {
            return {
              where() {
                return {
                  returning: async () => [
                    {
                      id: "assistant-1",
                      sessionId: "session-1",
                      userId: "user-1",
                      taskId: "task-1",
                      role: "assistant",
                      status: values.status,
                      content: values.content,
                      error: values.error ?? null,
                    },
                  ],
                };
              },
            };
          },
        };
      },
    },
    services: {
      eventBus: {
        publish(event: Record<string, unknown>) {
          published.push(event);
        },
      },
    },
  };

  await syncChatTaskLifecycle(app as never, {
    originalTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "device-1",
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
    } as never,
    updatedTask: {
      id: "task-1",
      userId: "user-1",
      targetDeviceId: "device-1",
      title: "Kedi resmi",
      status: "completed",
      queuePosition: 0,
      requestedCapabilities: [],
      summary: "Görsel hazır.",
      result: {
        text: "Görsel hazır.",
        assistantBlocks: [
          {
            type: "artifact",
            artifactType: "image",
            artifactId: "artifact-1",
            title: "Görsel hazır",
            preview: "Görsel hazır.",
            url: "https://api.elyan.dev/v1/artifacts/artifact-1/content?token=signed",
            mime: "image/jpeg",
            viewerHint: "image",
            contentFamily: "image",
            loadStrategy: "remote_url",
          },
        ],
      },
      createdAt: new Date("2026-01-01T12:00:00.000Z"),
      updatedAt: new Date("2026-01-01T12:00:02.000Z"),
      completedAt: new Date("2026-01-01T12:00:02.000Z"),
      payload: {
        metadata: {
          presentation: "chat",
          chat: {
            sessionId: "session-1",
            assistantMessageId: "assistant-1",
          },
        },
      },
    } as never,
  });

  const payload = published[0]?.payload as
    | {
        assistantMessage?: { blocks?: Array<Record<string, unknown>> };
      }
    | undefined;
  const blocks = payload?.assistantMessage?.blocks ?? [];
  assert.equal(blocks[0]?.type, "artifact");
  assert.equal(blocks[0]?.viewerHint, "image");
  assert.equal(blocks[0]?.contentFamily, "image");
  assert.equal(blocks[0]?.url, "https://api.elyan.dev/v1/artifacts/artifact-1/content?token=signed");
  assert.equal(blocks.length, 2);
  assert.equal(blocks[1]?.type, "text");
});
