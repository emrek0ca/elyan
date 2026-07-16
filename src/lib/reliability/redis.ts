import { Redis } from "ioredis";
import type { AppEnv } from "../../config/env.js";

type MemoryRecord = {
  value: string;
  expiresAt: number | null;
};

export type ReliabilityStoreSummary = {
  mode: "redis" | "memory";
  ready: boolean;
  required: boolean;
};

export class ReliabilityStore {
  private readonly memory = new Map<string, MemoryRecord>();
  private readonly required: boolean;
  private redis: Redis | null = null;
  private ready = false;

  public constructor(env: Pick<AppEnv, "REDIS_URL" | "RELIABILITY_REDIS_REQUIRED">) {
    this.required = env.RELIABILITY_REDIS_REQUIRED;

    if (env.REDIS_URL) {
      const redis = new Redis(env.REDIS_URL, {
        connectTimeout: 750,
        enableOfflineQueue: false,
        lazyConnect: true,
        maxRetriesPerRequest: 1,
      });
      this.redis = redis;
      redis.on("ready", () => {
        this.ready = true;
      });
      redis.on("close", () => {
        this.ready = false;
      });
      redis.on("error", () => {
        this.ready = false;
      });
    }
  }

  public get redisClient(): Redis | null {
    return this.redis;
  }

  public async close(): Promise<void> {
    if (this.redis) {
      await this.redis.quit().catch(() => undefined);
    }
  }

  public async ping(): Promise<boolean> {
    if (!this.redis) {
      return !this.required;
    }

    try {
      if (this.redis.status === "end") {
        return false;
      }
      if (this.redis.status === "wait") {
        await this.redis.connect();
      }
      const pong = await this.redis.ping();
      this.ready = pong === "PONG";
      return this.ready;
    } catch {
      this.ready = false;
      return false;
    }
  }

  public summary(): ReliabilityStoreSummary {
    return {
      mode: this.redis ? "redis" : "memory",
      ready: this.redis ? this.ready : !this.required,
      required: this.required,
    };
  }

  public async get(key: string): Promise<string | null> {
    if (await this.canUseRedis()) {
      return this.redis!.get(key);
    }

    return this.getMemory(key);
  }

  public async set(key: string, value: string, ttlMs?: number): Promise<void> {
    if (await this.canUseRedis()) {
      if (ttlMs && ttlMs > 0) {
        await this.redis!.set(key, value, "PX", ttlMs);
      } else {
        await this.redis!.set(key, value);
      }
      return;
    }

    this.setMemory(key, value, ttlMs);
  }

  public async del(key: string): Promise<void> {
    if (await this.canUseRedis()) {
      await this.redis!.del(key);
      return;
    }

    this.memory.delete(key);
  }

  public async increment(key: string, ttlMs: number): Promise<number> {
    if (await this.canUseRedis()) {
      const value = await this.redis!.incr(key);
      if (value === 1) {
        await this.redis!.pexpire(key, ttlMs);
      }
      return value;
    }

    const current = Number(this.getMemory(key) ?? "0") + 1;
    this.setMemory(key, String(current), ttlMs);
    return current;
  }

  public async incrementBy(key: string, amount: number, ttlMs: number): Promise<number> {
    const safeAmount = Math.max(0, Math.trunc(amount));
    if (safeAmount === 0) {
      return Number((await this.get(key)) ?? "0");
    }
    if (await this.canUseRedis()) {
      const value = await this.redis!.incrby(key, safeAmount);
      if (value === safeAmount) {
        await this.redis!.pexpire(key, ttlMs);
      }
      return value;
    }

    const current = Number(this.getMemory(key) ?? "0") + safeAmount;
    this.setMemory(key, String(current), ttlMs);
    return current;
  }

  public async acquireLock(key: string, owner: string, ttlMs: number): Promise<boolean> {
    if (await this.canUseRedis()) {
      const result = await this.redis!.set(key, owner, "PX", ttlMs, "NX");
      return result === "OK";
    }

    if (this.getMemory(key) !== null) {
      return false;
    }
    this.setMemory(key, owner, ttlMs);
    return true;
  }

  public async releaseLock(key: string, owner: string): Promise<boolean> {
    if (await this.canUseRedis()) {
      const result = await this.redis!.eval(
        "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end",
        1,
        key,
        owner,
      );
      return result === 1;
    }

    if (this.getMemory(key) !== owner) {
      return false;
    }
    this.memory.delete(key);
    return true;
  }

  private async canUseRedis(): Promise<boolean> {
    if (!this.redis) {
      return false;
    }

    if (this.ready) {
      return true;
    }

    return this.ping();
  }

  private getMemory(key: string): string | null {
    const record = this.memory.get(key);
    if (!record) {
      return null;
    }
    if (record.expiresAt !== null && record.expiresAt <= Date.now()) {
      this.memory.delete(key);
      return null;
    }
    return record.value;
  }

  private setMemory(key: string, value: string, ttlMs?: number): void {
    this.memory.set(key, {
      value,
      expiresAt: ttlMs && ttlMs > 0 ? Date.now() + ttlMs : null,
    });
  }
}
