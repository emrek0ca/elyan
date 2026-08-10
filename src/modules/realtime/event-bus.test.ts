import assert from "node:assert/strict";
import test from "node:test";
import { EventBus, type RealtimeFanout, type RealtimeFanoutMessage } from "./event-bus.js";

test("EventBus fans out user, device, and task scoped events", async () => {
  const bus = new EventBus(async (event) => ({
    ...event,
    id: 41,
    createdAt: "2030-01-01T00:00:00.000Z",
  }));
  const seen: string[] = [];

  const unsubscribers = [
    bus.subscribe("user:user-1", () => seen.push("user")),
    bus.subscribe("device:device-1", () => seen.push("device")),
    bus.subscribe("task:task-1", () => seen.push("task")),
  ];

  const published = await bus.publish({
    topic: "task.updated",
    userId: "user-1",
    deviceId: "device-1",
    taskId: "task-1",
    payload: {
      ok: true,
    },
  });

  await new Promise((resolve) => setImmediate(resolve));

  unsubscribers.forEach((unsubscribe) => unsubscribe());

  assert.deepEqual(seen.sort(), ["device", "task", "user"]);
  assert.equal(published.id, 41);
  assert.equal(published.createdAt, "2030-01-01T00:00:00.000Z");
});

test("EventBus publishes persisted events to external fanout and accepts remote fanout messages", async () => {
  const handlers: Array<(message: RealtimeFanoutMessage) => void> = [];
  const published: Array<{ channels: string[]; topic: string; id?: number }> = [];
  const fanout: RealtimeFanout = {
    start(nextHandler) {
      handlers.push(nextHandler);
      return Promise.resolve();
    },
    publish(channels, event) {
      published.push({
        channels,
        topic: event.topic,
        id: event.id,
      });
      return Promise.resolve();
    },
    close() {
      return Promise.resolve();
    },
  };
  const bus = new EventBus(
    async (event) => ({
      ...event,
      id: 42,
      createdAt: "2030-01-01T00:00:00.000Z",
    }),
    {
      fanout,
    },
  );
  const seen: string[] = [];

  await bus.startFanout();
  const unsubscribe = bus.subscribe("user:user-1", (event) => seen.push(event.topic));

  await bus.publish({
    topic: "task.updated",
    userId: "user-1",
    payload: {},
  });
  const remoteHandler = handlers[0];
  assert.ok(remoteHandler);
  remoteHandler({
    channel: "user:user-1",
    event: {
      id: 43,
      topic: "chat.message.delta",
      userId: "user-1",
      payload: {},
      createdAt: "2030-01-01T00:00:01.000Z",
    },
  });

  unsubscribe();

  assert.deepEqual(published, [
    {
      channels: ["user:user-1"],
      topic: "task.updated",
      id: 42,
    },
  ]);
  assert.deepEqual(seen, ["task.updated", "chat.message.delta"]);
});

test("EventBus publishes volatile stream events without calling the persistor", async () => {
  let persistCount = 0;
  const published: Array<{ channels: string[]; topic: string; id?: number }> = [];
  const bus = new EventBus(
    async (event) => {
      persistCount += 1;
      return {
        ...event,
        id: 99,
        createdAt: "2030-01-01T00:00:00.000Z",
      };
    },
    {
      fanout: {
        start() {
          return Promise.resolve();
        },
        publish(channels, event) {
          published.push({
            channels,
            topic: event.topic,
            id: event.id,
          });
          return Promise.resolve();
        },
        close() {
          return Promise.resolve();
        },
      },
    },
  );
  const seen: string[] = [];

  await bus.startFanout();
  const unsubscribe = bus.subscribe("user:user-1", (event) => seen.push(event.topic));

  const event = await bus.publishVolatile({
    topic: "message.delta",
    userId: "user-1",
    payload: {
      delta: "Merhaba",
    },
  });

  unsubscribe();
  // Volatile fanout artık BİLEREK bloklamıyor: sağlayıcı akışı Redis
  // gidiş-dönüşünü beklemesin diye kanal başına sıralı bir kuyruğa
  // devrediliyor (bkz. publishVolatile). Bu yüzden yayının gerçekleşmesi
  // `publishVolatile` dönüşünde değil, kuyruk boşalınca garanti. `close()`
  // tüm kuyrukları bekler.
  await bus.close();

  assert.equal(persistCount, 0);
  assert.equal(event.id, undefined);
  assert.deepEqual(published, [
    {
      channels: ["user:user-1"],
      topic: "message.delta",
      id: undefined,
    },
  ]);
  assert.deepEqual(seen, ["message.delta"]);
});

// ── Connect-race recovery: volatile snapshot layer ─────────────────────────
// SSE client'ı yayından SONRA bağlanınca aktif stream'in son durumunu
// alabilmeli. publishVolatile chat topic'lerinde kanal başına SON event'i
// TTL'li saklar; recentVolatileSnapshots bağlantı anında teslim eder.

test("EventBus keeps the latest volatile snapshot per chat topic for late subscribers", async () => {
  const bus = new EventBus();

  await bus.publishVolatile({
    topic: "message.delta",
    userId: "user-1",
    taskId: "task-1",
    payload: { content: "ilk parça" },
  });
  await bus.publishVolatile({
    topic: "message.delta",
    userId: "user-1",
    taskId: "task-1",
    payload: { content: "ilk parça ve devamı — kümülatif snapshot" },
  });
  await bus.publishVolatile({
    topic: "message.completed",
    userId: "user-1",
    taskId: "task-1",
    payload: { content: "final" },
  });

  // Geç bağlanan client: kanalda topic başına SON event, yayın sırasıyla.
  const snapshots = bus.recentVolatileSnapshots("user:user-1");
  assert.equal(snapshots.length, 2);
  assert.equal(snapshots[0]?.topic, "message.delta");
  assert.deepEqual(snapshots[0]?.payload, {
    content: "ilk parça ve devamı — kümülatif snapshot",
  });
  assert.equal(snapshots[1]?.topic, "message.completed");

  // Task kanalı da aynı snapshot'ları taşır.
  assert.equal(bus.recentVolatileSnapshots("task:task-1").length, 2);
  // Alakasız kanal boş.
  assert.deepEqual(bus.recentVolatileSnapshots("user:user-2"), []);
});

test("EventBus volatile snapshots expire after their TTL window", async () => {
  const bus = new EventBus();
  await bus.publishVolatile({
    topic: "message.delta",
    userId: "user-1",
    payload: { content: "eski" },
  });

  // Kısa bekleme sonrası dar pencere → süresi dolmuş sayılır (aynı-ms
  // yarışını önlemek için gerçek gecikme kullanıyoruz).
  await new Promise((resolve) => setTimeout(resolve, 15));
  assert.deepEqual(bus.recentVolatileSnapshots("user:user-1", 5), []);
  // Varsayılan pencerede hâlâ görünür.
  assert.equal(bus.recentVolatileSnapshots("user:user-1").length, 1);
});

test("EventBus does not snapshot non-chat volatile topics", async () => {
  const bus = new EventBus();
  await bus.publishVolatile({
    topic: "heartbeat",
    userId: "user-1",
    payload: {},
  });
  assert.deepEqual(bus.recentVolatileSnapshots("user:user-1"), []);
});

test("device status survives the connect race that chat deltas do not", async () => {
  // Canlı şikâyet: masaüstü eşleştirildikten sonra mobil uzun süre
  // "çevrimdışı" gösteriyordu. Sebep, olayın o saniyede dinlemeyen istemci
  // için kalıcı olarak kaybolmasıydı — cihaz durumu snapshot listesinde
  // değildi. Durum bir AKIŞ değil, DURUM: sonradan bağlanan da öğrenmeli.
  const bus = new EventBus();
  await bus.publishVolatile({
    topic: "device.status_changed",
    userId: "user-late",
    deviceId: "desktop-1",
    payload: { deviceId: "desktop-1", isOnline: true, reason: "runtime_connected" },
  });

  const snapshots = bus.recentVolatileSnapshots("user:user-late");
  assert.equal(snapshots.length, 1);
  assert.equal(snapshots[0]?.topic, "device.status_changed");
  assert.equal((snapshots[0]?.payload as { isOnline?: boolean }).isOnline, true);
});

test("state snapshots outlive the short streaming window", async () => {
  // Akış deltası 45 sn sonra bayat sayılır; cihaz durumu sayılmaz — masaüstü
  // on dakika önce bağlanmış olabilir ve o bilgi hâlâ doğrudur.
  const bus = new EventBus();
  await bus.publishVolatile({
    topic: "message.delta",
    userId: "user-ttl",
    payload: { text: "yazıyor" },
  });
  await bus.publishVolatile({
    topic: "device.status_changed",
    userId: "user-ttl",
    deviceId: "desktop-1",
    payload: { deviceId: "desktop-1", isOnline: true },
  });

  const topics = bus
    .recentVolatileSnapshots("user:user-ttl")
    .map((event) => event.topic);
  assert.deepEqual(topics.sort(), ["device.status_changed", "message.delta"]);
});
