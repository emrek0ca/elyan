import { randomUUID } from "node:crypto";
import { Redis } from "ioredis";
import { pack, unpack } from "msgpackr";
import WebSocket from "ws";

type RuntimeSocketEnvelope = {
  socket: WebSocket;
  userId: string;
  deviceId: string;
};

type RealtimeHubOptions = {
  redisUrl?: string;
  channelPrefix?: string;
  onError?: (error: unknown) => void;
};

type RuntimeCommandEnvelope = {
  kind: "command";
  commandId: string;
  replyInstanceId: string;
  deviceId: string;
  message: unknown;
};

type RuntimeCommandAck = {
  kind: "ack";
  commandId: string;
  delivered: boolean;
};

type RuntimeBridgeEnvelope = RuntimeCommandEnvelope | RuntimeCommandAck;

const RUNTIME_PRESENCE_TTL_MS = 90_000;
const RUNTIME_COMMAND_ACK_TIMEOUT_MS = 1_000;
const RUNTIME_PENDING_COMMAND_MAX = 2_048;

export class RealtimeHub {
  private readonly runtimeSockets = new Map<string, RuntimeSocketEnvelope>();
  private readonly instanceId = randomUUID();
  private publisher: Redis | null = null;
  private subscriber: Redis | null = null;
  private readonly pendingCommands = new Map<
    string,
    {
      resolve: (delivered: boolean) => void;
      timer: ReturnType<typeof setTimeout>;
    }
  >();

  public constructor(private readonly options: RealtimeHubOptions = {}) {}

  public async start(): Promise<void> {
    if (!this.options.redisUrl || this.publisher || this.subscriber) {
      return;
    }
    const publisher = this.createRedisClient();
    const subscriber = this.createRedisClient();
    subscriber.on("message", (_channel, raw) => {
      try {
        const envelope = unpack(
          Buffer.from(raw, "binary"),
        ) as RuntimeBridgeEnvelope;
        if (envelope.kind === "ack") {
          this.settlePendingCommand(
            envelope.commandId,
            envelope.delivered === true,
          );
          return;
        }
        const command = envelope;
        if (
          typeof command.commandId !== "string" ||
          typeof command.replyInstanceId !== "string" ||
          typeof command.deviceId !== "string" ||
          command.deviceId.trim().length === 0
        ) {
          return;
        }
        const delivered = this.sendToRuntime(
          command.deviceId,
          command.message,
        );
        void this.publisher
          ?.publish(
            this.instanceChannel(command.replyInstanceId),
            pack({
              kind: "ack",
              commandId: command.commandId,
              delivered,
            } satisfies RuntimeCommandAck).toString("binary"),
          )
          .catch((error) => this.options.onError?.(error));
      } catch (error) {
        this.options.onError?.(error);
      }
    });
    try {
      await Promise.all([publisher.connect(), subscriber.connect()]);
      await subscriber.subscribe(this.instanceChannel(this.instanceId));
      this.publisher = publisher;
      this.subscriber = subscriber;
    } catch (error) {
      await Promise.all([
        publisher.quit().catch(() => undefined),
        subscriber.quit().catch(() => undefined),
      ]);
      throw error;
    }
  }

  public async close(): Promise<void> {
    await Promise.all(
      [...this.runtimeSockets.keys()].map((deviceId) =>
        this.releaseRuntimePresence(deviceId).catch(() => undefined),
      ),
    );
    const clients = [this.subscriber, this.publisher].filter(
      (client): client is Redis => client !== null,
    );
    for (const commandId of [...this.pendingCommands.keys()]) {
      this.settlePendingCommand(commandId, false);
    }
    this.subscriber = null;
    this.publisher = null;
    await Promise.all(
      clients.map((client) => client.quit().catch(() => undefined)),
    );
  }

  public attachRuntime(input: RuntimeSocketEnvelope): void {
    const existing = this.runtimeSockets.get(input.deviceId);

    if (existing && existing.socket !== input.socket) {
      existing.socket.close(4001, "replaced");
    }

    this.runtimeSockets.set(input.deviceId, input);
  }

  public async registerRuntimePresence(deviceId: string): Promise<void> {
    if (!this.publisher) return;
    await this.publisher.set(
      this.presenceKey(deviceId),
      this.instanceId,
      "PX",
      RUNTIME_PRESENCE_TTL_MS,
    );
  }

  public async touchRuntimePresence(deviceId: string): Promise<boolean> {
    if (!this.publisher) {
      return this.isRuntimeConnected(deviceId);
    }
    const result = await this.publisher.eval(
      "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('PEXPIRE', KEYS[1], ARGV[2]) else return 0 end",
      1,
      this.presenceKey(deviceId),
      this.instanceId,
      RUNTIME_PRESENCE_TTL_MS,
    );
    return Number(result) === 1;
  }

  public async releaseRuntimePresence(deviceId: string): Promise<void> {
    if (!this.publisher) return;
    await this.publisher.eval(
      "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end",
      1,
      this.presenceKey(deviceId),
      this.instanceId,
    );
  }

  public detachRuntime(deviceId: string, socket?: WebSocket): void {
    const existing = this.runtimeSockets.get(deviceId);

    if (!existing) {
      return;
    }

    if (socket && existing.socket !== socket) {
      return;
    }

    this.runtimeSockets.delete(deviceId);
  }

  public closeRuntime(deviceId: string, code = 4001, reason = "replaced", socket?: WebSocket): void {
    const existing = this.runtimeSockets.get(deviceId);

    if (!existing) {
      return;
    }

    if (socket && existing.socket !== socket) {
      return;
    }

    this.runtimeSockets.delete(deviceId);

    if (existing.socket.readyState === WebSocket.OPEN || existing.socket.readyState === WebSocket.CONNECTING) {
      existing.socket.close(code, reason);
    }
  }

  public isRuntimeConnected(deviceId: string): boolean {
    const connection = this.runtimeSockets.get(deviceId);
    return Boolean(connection && connection.socket.readyState === WebSocket.OPEN);
  }

  public sendToRuntime(deviceId: string, message: unknown): boolean {
    const connection = this.runtimeSockets.get(deviceId);

    if (!connection || connection.socket.readyState !== WebSocket.OPEN) {
      return false;
    }

    try {
      connection.socket.send(JSON.stringify(message));
      return true;
    } catch (error) {
      this.options.onError?.(error);
      this.detachRuntime(deviceId, connection.socket);
      return false;
    }
  }

  public async sendToRuntimeDistributed(
    deviceId: string,
    message: unknown,
  ): Promise<boolean> {
    if (this.sendToRuntime(deviceId, message)) {
      return true;
    }
    if (!this.publisher) {
      return false;
    }
    let pendingCommandId: string | null = null;
    try {
      const owner = await this.publisher.get(this.presenceKey(deviceId));
      if (!owner || owner === this.instanceId) {
        return false;
      }
      if (this.pendingCommands.size >= RUNTIME_PENDING_COMMAND_MAX) {
        return false;
      }
      const commandId = randomUUID();
      pendingCommandId = commandId;
      const delivered = new Promise<boolean>((resolve) => {
        const timer = setTimeout(() => {
          this.settlePendingCommand(commandId, false);
        }, RUNTIME_COMMAND_ACK_TIMEOUT_MS);
        timer.unref?.();
        this.pendingCommands.set(commandId, { resolve, timer });
      });
      const receivers = await this.publisher.publish(
        this.instanceChannel(owner),
        pack({
          kind: "command",
          commandId,
          replyInstanceId: this.instanceId,
          deviceId,
          message,
        } satisfies RuntimeCommandEnvelope).toString("binary"),
      );
      if (receivers <= 0) {
        this.settlePendingCommand(commandId, false);
      }
      return await delivered;
    } catch (error) {
      if (pendingCommandId) {
        this.settlePendingCommand(pendingCommandId, false);
      }
      this.options.onError?.(error);
      return false;
    }
  }

  private get channelPrefix(): string {
    const base =
      this.options.channelPrefix?.trim() || "elyan:realtime";
    return `${base}:runtime-command:v1`;
  }

  private presenceKey(deviceId: string): string {
    return `${this.channelPrefix}:presence:${deviceId}`;
  }

  private instanceChannel(instanceId: string): string {
    return `${this.channelPrefix}:instance:${instanceId}`;
  }

  private createRedisClient(): Redis {
    const redis = new Redis(this.options.redisUrl!, {
      connectTimeout: 750,
      enableOfflineQueue: false,
      lazyConnect: true,
      maxRetriesPerRequest: 1,
    });
    redis.on("error", (error) => {
      this.options.onError?.(error);
    });
    return redis;
  }

  private settlePendingCommand(
    commandId: string,
    delivered: boolean,
  ): void {
    const pending = this.pendingCommands.get(commandId);
    if (!pending) return;
    this.pendingCommands.delete(commandId);
    clearTimeout(pending.timer);
    pending.resolve(delivered);
  }
}
