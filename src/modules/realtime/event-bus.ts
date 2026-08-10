import { EventEmitter } from "node:events";
import { randomUUID } from "node:crypto";
import { Redis } from "ioredis";
import { pack, unpack } from "msgpackr";

export type DomainEvent = {
  id?: number;
  topic: string;
  userId?: string;
  deviceId?: string;
  taskId?: string;
  payload: unknown;
  createdAt: string;
};

export type DomainEventInput = Omit<DomainEvent, "createdAt"> & {
  createdAt?: string;
};

export type DomainEventPersistor = (
  event: DomainEventInput,
) => Promise<DomainEvent> | DomainEvent;

export type PersistedDomainEvent = DomainEvent & {
  id: number;
};

export type RealtimeFanoutMessage = {
  channel: string;
  event: DomainEvent;
};

export type RealtimeFanout = {
  start: (handler: (message: RealtimeFanoutMessage) => void) => Promise<void>;
  publish: (channels: string[], event: DomainEvent) => Promise<void>;
  close: () => Promise<void>;
};

export type EventBusOptions = {
  fanout?: RealtimeFanout;
  onFanoutError?: (error: unknown) => void;
};

/**
 * Chat stream topic'leri volatile yayınlanır (persist yok) — SSE client'ı
 * yayın ANINDA bağlı değilse event kaybolur. İlk mesaj senaryosu: kullanıcı
 * uygulamayı açar açmaz yazar; SSE bağlantısı (auth + replay DB sorguları)
 * kurulurken cevap stream'lenir ve kaybolurdu. Bu snapshot katmanı kanal
 * başına topic'in SON event'ini kısa TTL ile tutar; SSE bağlanınca replay
 * sonrasında client'a verilir. `message.delta` payload'ı kümülatif otoriter
 * snapshot taşıdığı için topic başına SON event yeterlidir — ring buffer'a
 * gerek yok, bellek maliyeti kanal başına birkaç event.
 */
const VOLATILE_SNAPSHOT_TOPICS = new Set([
  "message.created",
  "message.delta",
  "block.preview",
  "message.completed",
  "message.error",
  "usage.final",
  // Cihaz durumu bir AKIŞ olayı değil, bir DURUM. Listede olmadığı için
  // masaüstü bağlandığı an yayınlanan olay, o saniyede dinlemeyen istemci
  // için kalıcı olarak kayboluyordu: kullanıcı eşleştirmeyi bitiriyor, olay
  // uçuyor, mobil elle yenilenene kadar "çevrimdışı" gösteriyordu.
  "device.status_changed",
]);
const VOLATILE_SNAPSHOT_TTL_MS = 45_000;
// Durum olayları akış olaylarından çok daha uzun yaşamalı: masaüstü on dakika
// önce bağlanmış olabilir ve o bilgi hâlâ doğrudur. Akış deltalarında uzun TTL
// bayat içerik gösterirdi; durumda tersi geçerli.
const VOLATILE_STATE_SNAPSHOT_TTL_MS = 15 * 60_000;
const VOLATILE_STATE_SNAPSHOT_TOPICS = new Set(["device.status_changed"]);

function volatileSnapshotTtlFor(topic: string): number {
  return VOLATILE_STATE_SNAPSHOT_TOPICS.has(topic)
    ? VOLATILE_STATE_SNAPSHOT_TTL_MS
    : VOLATILE_SNAPSHOT_TTL_MS;
}
const VOLATILE_SNAPSHOT_SWEEP_EVERY = 500;
const VOLATILE_SNAPSHOT_MAX_CHANNELS = 20_000;

type VolatileSnapshotEntry = { event: DomainEvent; at: number };

export class EventBus {
  constructor(
    private readonly persist?: DomainEventPersistor,
    private readonly options: EventBusOptions = {},
  ) {}

  private readonly emitter = new EventEmitter();
  private fanoutStarted = false;
  private readonly volatileSnapshots = new Map<
    string,
    Map<string, VolatileSnapshotEntry>
  >();
  private volatilePublishCount = 0;
  // Local SSE delivery must never wait for Redis. Remote volatile publishes
  // are ordered per channel, not globally: one slow user's Redis publish must
  // not queue every other user's delta behind it.
  private readonly volatileFanoutTails = new Map<string, Promise<void>>();

  private recordVolatileSnapshot(channels: string[], event: DomainEvent): void {
    if (!VOLATILE_SNAPSHOT_TOPICS.has(event.topic)) {
      return;
    }
    const at = Date.now();
    for (const channel of channels) {
      let byTopic = this.volatileSnapshots.get(channel);
      if (!byTopic) {
        // Kanal tavanı: patolojik durumda (ör. bir sızıntı) map sınırsız
        // büyümesin. Tavana gelince en eski kanalı at (Map insertion order).
        if (this.volatileSnapshots.size >= VOLATILE_SNAPSHOT_MAX_CHANNELS) {
          const oldest = this.volatileSnapshots.keys().next().value;
          if (oldest !== undefined) {
            this.volatileSnapshots.delete(oldest);
          }
        }
        byTopic = new Map();
        this.volatileSnapshots.set(channel, byTopic);
      }
      byTopic.set(event.topic, { event, at });
    }

    this.volatilePublishCount += 1;
    if (this.volatilePublishCount % VOLATILE_SNAPSHOT_SWEEP_EVERY === 0) {
      this.sweepVolatileSnapshots(at);
    }
  }

  private sweepVolatileSnapshots(now: number): void {
    for (const [channel, byTopic] of this.volatileSnapshots) {
      for (const [topic, entry] of byTopic) {
        if (now - entry.at > volatileSnapshotTtlFor(topic)) {
          byTopic.delete(topic);
        }
      }
      if (byTopic.size === 0) {
        this.volatileSnapshots.delete(channel);
      }
    }
  }

  /**
   * SSE bağlantısı kurulduğunda aktif stream'in kaçırılan son durumunu geri
   * vermek için: kanaldaki taze (TTL içi) son volatile event'ler, yayın
   * sırasına göre. Boş dizi = kaçırılan aktif stream yok.
   */
  public recentVolatileSnapshots(
    channel: string,
    // Verilmezse her topic KENDİ TTL'iyle süzülür. Tek bir üst sınır
    // kullanmak, uzun ömürlü durum olaylarını akış deltalarının kısa
    // penceresine hapsediyordu.
    maxAgeMs?: number,
  ): DomainEvent[] {
    const byTopic = this.volatileSnapshots.get(channel);
    if (!byTopic) {
      return [];
    }
    const now = Date.now();
    return [...byTopic.entries()]
      .filter(
        ([topic, entry]) =>
          now - entry.at <= (maxAgeMs ?? volatileSnapshotTtlFor(topic)),
      )
      .map(([, entry]) => entry)
      .sort((a, b) => a.at - b.at)
      .map((entry) => entry.event);
  }

  public async startFanout(): Promise<void> {
    if (!this.options.fanout || this.fanoutStarted) {
      return;
    }

    await this.options.fanout.start((message) => {
      // A client may connect to this worker after the remote publish reached
      // Redis but before its SSE subscription was attached. Keep the same
      // short-lived connect-race snapshot on every worker, not only the one
      // that originally published the volatile event.
      this.recordVolatileSnapshot([message.channel], message.event);
      this.emitChannel(message.channel, message.event);
    });
    this.fanoutStarted = true;
  }

  public async publish(event: DomainEventInput): Promise<DomainEvent> {
    const normalized = this.persist
      ? await this.persist(event)
      : {
          ...event,
          createdAt: event.createdAt ?? new Date().toISOString(),
        };
    const storedEvent: DomainEvent = {
      ...event,
      ...normalized,
      createdAt: normalized.createdAt ?? event.createdAt ?? new Date().toISOString(),
    };
    const channels = this.channelsFor(storedEvent);

    this.emitter.emit("event", storedEvent);

    for (const channel of channels) {
      this.emitChannel(channel, storedEvent);
    }

    if (this.options.fanout && this.fanoutStarted && channels.length > 0) {
      await this.options.fanout.publish(channels, storedEvent).catch((error: unknown) => {
        this.options.onFanoutError?.(error);
      });
    }


    return storedEvent;
  }

  public async publishVolatile(event: DomainEventInput): Promise<DomainEvent> {
    const storedEvent: DomainEvent = {
      ...event,
      createdAt: event.createdAt ?? new Date().toISOString(),
    };
    const channels = this.channelsFor(storedEvent);

    this.recordVolatileSnapshot(channels, storedEvent);
    this.emitter.emit("event", storedEvent);

    for (const channel of channels) {
      this.emitChannel(channel, storedEvent);
    }

    // Volatile chat events are already delivered to local SSE subscribers and
    // recorded in the short-lived snapshot above. Do not make the provider
    // stream wait for a remote Redis round trip; the durable terminal event
    // remains recoverable from Postgres if a replica disappears mid-stream.
    if (this.options.fanout && this.fanoutStarted && channels.length > 0) {
      const fanout = this.options.fanout;
      const previous = channels.map(
        (channel) => this.volatileFanoutTails.get(channel) ?? Promise.resolve(),
      );
      // One Redis publish still carries all scopes for this event. Waiting on
      // every affected channel tail preserves ordering for each scope while
      // allowing unrelated users/tasks to publish concurrently.
      const next = Promise.all(previous)
        .then(() => fanout.publish(channels, storedEvent))
        .catch((error: unknown) => {
          this.options.onFanoutError?.(error);
        });
      const settled = next.then(
        () => undefined,
        () => undefined,
      );
      for (const channel of channels) {
        this.volatileFanoutTails.set(channel, settled);
        void settled.then(() => {
          if (this.volatileFanoutTails.get(channel) === settled) {
            this.volatileFanoutTails.delete(channel);
          }
        });
      }
    }

    return storedEvent;
  }

  public subscribe(channel: string, listener: (event: DomainEvent) => void): () => void {
    this.emitter.on(channel, listener);
    return () => this.emitter.off(channel, listener);
  }

  public async close(): Promise<void> {
    await Promise.all(this.volatileFanoutTails.values());
    await this.options.fanout?.close();
  }

  private channelsFor(event: DomainEvent): string[] {
    const channels = new Set<string>();
    if (event.userId) {
      channels.add(`user:${event.userId}`);
    }
    if (event.deviceId) {
      channels.add(`device:${event.deviceId}`);
    }
    if (event.taskId) {
      channels.add(`task:${event.taskId}`);
    }
    return [...channels];
  }

  private emitChannel(channel: string, event: DomainEvent): void {
    this.emitter.emit(channel, event);
  }
}

export class RedisRealtimeFanout implements RealtimeFanout {
  private readonly instanceId = randomUUID();
  private publisher: Redis | null = null;
  private subscriber: Redis | null = null;
  private started = false;

  public constructor(
    private readonly input: {
      redisUrl: string;
      channelPrefix?: string;
      onError?: (error: unknown) => void;
    },
  ) {}

  public async start(handler: (message: RealtimeFanoutMessage) => void): Promise<void> {
    if (this.started) {
      return;
    }

    const publisher = this.createRedisClient();
    const subscriber = this.createRedisClient();
    const pattern = `${this.channelPrefix}:*`;

    subscriber.on("pmessage", (_pattern, channel, raw) => {
      try {
        /* msgpackr: try binary unpack, fall back to JSON for legacy messages */
        let parsed: { originId?: string; channel?: string; event?: DomainEvent };
        try {
          parsed = unpack(Buffer.from(raw, "binary")) as typeof parsed;
        } catch {
          parsed = JSON.parse(raw) as typeof parsed;
        }

        if (parsed.originId === this.instanceId || !parsed.channel || !parsed.event) {
          return;
        }

        handler({
          channel: parsed.channel,
          event: parsed.event,
        });
      } catch (error) {
        this.input.onError?.(error);
      }
    });

    try {
      await Promise.all([publisher.connect(), subscriber.connect()]);
      await subscriber.psubscribe(pattern);
    } catch (error) {
      await Promise.all([
        publisher.quit().catch(() => undefined),
        subscriber.quit().catch(() => undefined),
      ]);
      throw error;
    }

    this.publisher = publisher;
    this.subscriber = subscriber;
    this.started = true;
  }

  public async publish(channels: string[], event: DomainEvent): Promise<void> {
    if (!this.publisher || !this.started) {
      return;
    }

    const uniqueChannels = [...new Set(channels)];
    await Promise.all(
      uniqueChannels.map((channel) =>
        this.publisher!.publish(
          this.redisChannel(channel),
          pack({ originId: this.instanceId, channel, event }).toString("binary"),
        ),
      ),
    );
  }

  public async close(): Promise<void> {
    const clients = [this.subscriber, this.publisher].filter((client): client is Redis => client !== null);
    this.subscriber = null;
    this.publisher = null;
    this.started = false;
    await Promise.all(clients.map((client) => client.quit().catch(() => undefined)));
  }

  private get channelPrefix(): string {
    return this.input.channelPrefix?.trim() || "elyan:realtime";
  }

  private redisChannel(channel: string): string {
    return `${this.channelPrefix}:${channel}`;
  }

  private createRedisClient(): Redis {
    const redis = new Redis(this.input.redisUrl, {
      connectTimeout: 750,
      enableOfflineQueue: false,
      lazyConnect: true,
      maxRetriesPerRequest: 1,
    });
    redis.on("error", (error) => {
      this.input.onError?.(error);
    });
    return redis;
  }
}
