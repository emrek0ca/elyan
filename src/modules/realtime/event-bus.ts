import { EventEmitter } from "node:events";

export type DomainEvent = {
  topic: string;
  userId?: string;
  deviceId?: string;
  taskId?: string;
  payload: unknown;
  createdAt: string;
};

export class EventBus {
  private readonly emitter = new EventEmitter();

  public publish(event: Omit<DomainEvent, "createdAt">): void {
    const normalized: DomainEvent = {
      ...event,
      createdAt: new Date().toISOString(),
    };

    this.emitter.emit("event", normalized);

    if (normalized.userId) {
      this.emitter.emit(`user:${normalized.userId}`, normalized);
    }

    if (normalized.deviceId) {
      this.emitter.emit(`device:${normalized.deviceId}`, normalized);
    }

    if (normalized.taskId) {
      this.emitter.emit(`task:${normalized.taskId}`, normalized);
    }
  }

  public subscribe(channel: string, listener: (event: DomainEvent) => void): () => void {
    this.emitter.on(channel, listener);
    return () => this.emitter.off(channel, listener);
  }
}
