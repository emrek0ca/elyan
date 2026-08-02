import assert from "node:assert/strict";
import test from "node:test";
import {
  getLastAssistantMessageText,
  isInternalRoutingSummary,
  isTransientChatProgressMessage,
  syncChatTaskLifecycle,
} from "./task-sync.js";

function selectStub(rows: Array<Record<string, unknown>>) {
  return {
    db: {
      select: () => ({
        from: () => ({
          where: () => ({
            orderBy: () => ({ limit: async () => rows }),
          }),
        }),
      }),
    },
  };
}

test("getLastAssistantMessageText carries the previous answer for the mobile chain", async () => {
  // ZİNCİRİN KAYNAK UCU: lastAssistantSummary şemada vardı ve contextPack ile
  // masaüstüne dispatch ediliyordu, ama DOLDURAN kimse yoktu — ne mobil
  // istemci gönderiyordu ne backend türetiyordu. Bu olmadan mobilde
  // "bunu belge yap" belgelenecek içeriği bulamıyordu.
  const app = selectStub([{ content: "Pomodoro tekniği 25 dakikalık bloklara dayanır.", preview: null }]);
  const text = await getLastAssistantMessageText(app as never, {
    userId: "u1",
    sessionId: "s1",
  });
  assert.equal(text, "Pomodoro tekniği 25 dakikalık bloklara dayanır.");
});

test("getLastAssistantMessageText falls back to preview, then yields null", async () => {
  const previewOnly = selectStub([{ content: "   ", preview: "Kısa özet" }]);
  assert.equal(
    await getLastAssistantMessageText(previewOnly as never, { userId: "u1", sessionId: "s1" }),
    "Kısa özet",
  );

  const empty = selectStub([]);
  assert.equal(
    await getLastAssistantMessageText(empty as never, { userId: "u1", sessionId: "s1" }),
    null,
  );

  // Kimlik eksikse sorgu hiç yapılmaz.
  const exploding = {
    db: {
      select() {
        throw new Error("sorgulanmamalıydı");
      },
    },
  };
  assert.equal(
    await getLastAssistantMessageText(exploding as never, { userId: "", sessionId: "s1" }),
    null,
  );
});

test("getLastAssistantMessageText fails open so task creation never breaks", async () => {
  // Süreklilik bir kolaylıktır, bağımlılık değil.
  const broken = {
    db: {
      select() {
        throw new Error("db down");
      },
    },
  };
  assert.equal(
    await getLastAssistantMessageText(broken as never, { userId: "u1", sessionId: "s1" }),
    null,
  );
});

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
      result: {
        executionTrace: {
          title: "Rapor hazırlanıyor",
          activeStepId: "write",
          steps: [
            {
              id: "research",
              label: "Kaynakları araştırıyorum",
              status: "completed",
              capability: "web_research",
              verificationStatus: "passed",
              attemptCount: 1,
            },
            {
              id: "write",
              label: "Raporu yazıyorum",
              status: "running",
              capability: "document_write",
              verificationStatus: "pending",
              attemptCount: 1,
            },
          ],
        },
      },
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
  assert.equal(
    updates[0]?.content,
    "Adımlar:\n1. Kaynakları araştırıyorum tamamlandı\n2. Raporu yazıyorum yürütülüyor",
  );
  const updatedEvent = published.find((event) => event.topic === "chat.message.updated");
  assert.ok(updatedEvent);
  const runningPayload = updatedEvent.payload as
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
  assert.equal(runningBlocks?.length, 1);
  assert.equal(runningBlocks?.[0]?.type, "task_trace");
  assert.equal(runningBlocks?.[0]?.activeStepId, "write");
  const runningSteps = runningBlocks?.[0]?.steps as
    | Array<Record<string, unknown>>
    | undefined;
  assert.deepEqual(
    runningSteps?.map((step) => step.id),
    ["research", "write"],
  );
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
        skillUsed: true,
        skillId: "research-report",
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
          metadata?: Record<string, unknown>;
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
  assert.equal(completedBlocks?.length, 2);
  assert.equal(completedBlocks?.some((block) => block.type === "task_trace"), true);
  assert.equal(
    completedBlocks?.find((block) => block.type === "text")?.markdown,
    "Merhaba, nasıl yardımcı olabilirim?",
  );
  assert.equal(completedPayload?.assistantMessage?.metadata?.skillUsed, true);
  assert.equal(
    completedPayload?.assistantMessage?.metadata?.skillId,
    "research-report",
  );
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
          metadata?: Record<string, unknown>;
        };
      }
    | undefined;

  assert.equal(
    completedPayload?.assistantMessage?.content,
    undefined,
  );
  assert.equal(
    completedPayload?.assistantMessage?.blocks?.find(
      (block) => block.type === "text",
    )?.markdown,
    'Görselde okunan metin kabaca "10:03 cku.itiraf.paylasim •II = 37" diye başlıyor.',
  );
  assert.equal(completedPayload?.assistantMessage?.metadata?.skillUsed, false);
  assert.equal(completedPayload?.assistantMessage?.metadata?.skillId, null);
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
  assert.equal(blocks.some((block) => block.type === "task_trace"), true);
  assert.equal(blocks.some((block) => block.type === "summary"), true);
  assert.equal(blocks.some((block) => block.type === "text"), true);
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
  assert.equal(blocks.length, 3);
  assert.equal(blocks.some((block) => block.type === "task_trace"), true);
  assert.equal(blocks.some((block) => block.type === "text"), true);
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
  assert.equal(blocks.length, 3);
  assert.equal(blocks.some((block) => block.type === "task_trace"), true);
  assert.equal(blocks.some((block) => block.type === "text"), true);
});

test("isTransientChatProgressMessage catches queue progress texts only", () => {
  for (const phrase of [
    "Yanıt hazırlanıyor.",
    "Yanıt yeniden deneniyor.",
    "Yanıt güvenli şekilde tamamlanıyor.",
    "  yanıt hazırlanıyor  ",
  ]) {
    assert.equal(isTransientChatProgressMessage(phrase), true, phrase);
  }
  for (const phrase of [
    "Yanıt sıraya alınamadı. Lütfen biraz sonra yeniden dene.",
    "Sıcak havada serin kalmanın birkaç yolu var...",
    "Görev tamamlandı, rapor hazır.",
    "",
  ]) {
    assert.equal(isTransientChatProgressMessage(phrase), false, phrase);
  }
});

test("syncChatTaskLifecycle never persists transient progress text as completed content", async () => {
  // Canlı bug'ın kalıcı-veri ayağı: markQueuedSharedBrainChatPhase task.summary'ye
  // "Yanıt hazırlanıyor." yazar; görev sonuç metni olmadan complete olursa bu
  // metin canonical asistan cevabı gibi history'ye düşmemeli.
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
          throw new Error("should not publish without a persisted row");
        },
      },
    },
  };

  const chatTask = {
    id: "task-1",
    userId: "user-1",
    targetDeviceId: "device-1",
    title: "hava durumu",
    summary: "Yanıt hazırlanıyor.",
    status: "completed",
    error: null,
    result: null,
    createdAt: new Date("2026-01-01T12:00:00.000Z"),
    updatedAt: new Date("2026-01-01T12:00:02.000Z"),
    payload: {
      metadata: {
        presentation: "chat",
        chat: {
          sessionId: "session-1",
          assistantMessageId: "assistant-1",
        },
      },
    },
  };

  await syncChatTaskLifecycle(app as never, {
    originalTask: chatTask as never,
    updatedTask: chatTask as never,
    message: "Yanıt hazırlanıyor.",
  });

  assert.equal(updates.length, 1);
  const persistedContent = String(updates[0]?.content ?? "");
  assert.notEqual(persistedContent, "Yanıt hazırlanıyor.");
  assert.match(persistedContent, /tamamlandı/i);
});

test("syncChatTaskLifecycle never writes transient progress text into row content", async () => {
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
          throw new Error("should not publish without a persisted row");
        },
      },
    },
  };

  const chatTask = {
    id: "task-1",
    userId: "user-1",
    targetDeviceId: "device-1",
    title: "hava durumu",
    summary: "Yanıt hazırlanıyor.",
    status: "queued",
    error: null,
    result: null,
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
  };

  await syncChatTaskLifecycle(app as never, {
    originalTask: chatTask as never,
    updatedTask: chatTask as never,
    message: "Yanıt hazırlanıyor.",
  });

  // Cevap tek kaynaktan gelir: kuyruk fazı content/preview alanlarını korur,
  // fakat canlı task-trace metadata'sı ilerlemeye devam eder. Böylece REST
  // history/poll hiçbir an "Yanıt hazırlanıyor."ı cevap olarak taşımaz.
  assert.equal(updates.length, 1);
  assert.equal(updates[0]?.status, "queued");
  assert.equal("content" in (updates[0] ?? {}), false);
  assert.equal("metadata" in (updates[0] ?? {}), true);
  assert.equal("preview" in (updates[0] ?? {}), false);
});

test("syncChatTaskLifecycle publishes statusRank and terminal authority fields", async () => {
  const published: Array<{ payload?: Record<string, unknown> }> = [];
  const app = {
    config: {
      ELYAN_BLOCKS_V11_ENABLED: false,
    },
    db: {
      update() {
        return {
          set() {
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
                      status: "completed",
                      content: "Cevap hazır.",
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
            payload:
              event.payload && typeof event.payload === "object" && !Array.isArray(event.payload)
                ? (event.payload as Record<string, unknown>)
                : undefined,
          });
        },
      },
    },
  };

  const chatTask = {
    id: "task-1",
    userId: "user-1",
    targetDeviceId: "device-1",
    title: "hava durumu",
    summary: null,
    status: "completed",
    error: null,
    result: { text: "Cevap hazır." },
    createdAt: new Date("2026-01-01T12:00:00.000Z"),
    updatedAt: new Date("2026-01-01T12:00:02.000Z"),
    payload: {
      metadata: {
        presentation: "chat",
        chat: {
          sessionId: "session-1",
          assistantMessageId: "assistant-1",
        },
      },
    },
  };

  await syncChatTaskLifecycle(app as never, {
    originalTask: chatTask as never,
    updatedTask: chatTask as never,
  });

  assert.equal(published.length, 1);
  const payload = published[0]?.payload as
    | {
        assistantMessageId?: string;
        statusRank?: number;
        terminal?: boolean;
      }
    | undefined;
  assert.equal(payload?.assistantMessageId, "assistant-1");
  assert.equal(payload?.statusRank, 90);
  assert.equal(payload?.terminal, true);
});
