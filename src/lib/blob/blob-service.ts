import { createHmac } from "node:crypto";
import { and, eq } from "drizzle-orm";
import type { PostgresJsDatabase } from "drizzle-orm/postgres-js";
import type { AppEnv } from "../../config/env.js";
import * as schema from "../../db/schema.js";
import { buildTenantCacheKey } from "../../db/tenant-context.js";
import type { ReliabilityStore } from "../reliability/redis.js";
import {
  decodeBlobBytes,
  decodeJsonBlob,
  decodeTextBlob,
  encodeBinaryBlob,
  encodeJsonBlob,
  encodeTextBlob,
  type BlobCompression,
  type EncodedBlob,
} from "./blob-codec.js";
import { BlobStore } from "./blob-store.js";

export type BlobScope =
  | "chat_message_content"
  | "task_payload"
  | "task_result"
  | "task_approval_request"
  | "artifact_body"
  | "task_event_payload"
  | "realtime_event_payload";

export type BlobOwnerType =
  | "chat_message"
  | "task"
  | "artifact"
  | "task_event"
  | "realtime_event";

export type StoredBlobDescriptor = {
  blobId: string;
  contentHash: string;
  storageKey: string;
  contentType: string;
  contentEncoding: BlobCompression;
  byteLength: number;
  storedByteLength: number;
};

type BlobRow = typeof schema.blobObjects.$inferSelect;

const HOT_CACHE_TTL_MS = 5 * 60 * 1000;

function safeJsonRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export class BlobService {
  private readonly store: BlobStore;

  public constructor(
    private readonly db: PostgresJsDatabase<typeof schema>,
    private readonly reliabilityStore: ReliabilityStore,
    env: Pick<
      AppEnv,
      | "BLOB_STORAGE_BUCKET"
      | "BLOB_STORAGE_REGION"
      | "BLOB_STORAGE_ENDPOINT"
      | "BLOB_STORAGE_ACCESS_KEY_ID"
      | "BLOB_STORAGE_SECRET_ACCESS_KEY"
      | "BLOB_STORAGE_FORCE_PATH_STYLE"
      | "BLOB_STORAGE_SIGNED_URL_TTL_SECONDS"
      | "BLOB_HMAC_SECRET"
    >,
  ) {
    this.store = new BlobStore(env);
    this.addressSecret = env.BLOB_HMAC_SECRET.trim();
  }

  private readonly addressSecret: string;

  public isReady(): boolean {
    return this.store.isConfigured() && this.addressSecret.length >= 16;
  }

  public async storeJson(input: {
    ownerType: BlobOwnerType;
    ownerId: string;
    userId?: string;
    slot: string;
    scope: BlobScope;
    value: unknown;
    contentType?: string;
  }): Promise<StoredBlobDescriptor | null> {
    if (!this.isReady()) {
      return null;
    }
    const encoded = await encodeJsonBlob(input.value, input.contentType);
    return this.persistEncodedBlob(input, encoded);
  }

  public async storeText(input: {
    ownerType: BlobOwnerType;
    ownerId: string;
    userId?: string;
    slot: string;
    scope: BlobScope;
    value: string;
    contentType?: string;
  }): Promise<StoredBlobDescriptor | null> {
    if (!this.isReady()) {
      return null;
    }
    const encoded = await encodeTextBlob(input.value, input.contentType);
    return this.persistEncodedBlob(input, encoded);
  }

  public async storeBinary(input: {
    ownerType: BlobOwnerType;
    ownerId: string;
    userId?: string;
    slot: string;
    scope: BlobScope;
    value: Uint8Array;
    contentType: string;
  }): Promise<StoredBlobDescriptor | null> {
    if (!this.isReady()) {
      return null;
    }
    const encoded = await encodeBinaryBlob(input.value, input.contentType);
    return this.persistEncodedBlob(input, encoded);
  }

  public async hydrateText(blobId: string): Promise<string | null> {
    const cacheKey = `legacy:blob:text:${blobId}`;
    const cached = await this.reliabilityStore.get(cacheKey);
    if (cached) {
      return cached;
    }

    const row = await this.getBlobRow(blobId);
    if (!row) {
      return null;
    }

    const storedBytes = await this.store.getObjectBytes(row.storageKey);
    if (!storedBytes) {
      return null;
    }

    const text = await decodeTextBlob({
      storedBytes,
      compression: row.compression,
    });
    await this.reliabilityStore.set(cacheKey, text, HOT_CACHE_TTL_MS);
    void this.touchBlob(blobId);
    return text;
  }

  public async hydrateTextForOwner(input: {
    blobId: string;
    userId: string;
    ownerType: BlobOwnerType;
    ownerId: string;
  }): Promise<string | null> {
    const row = await this.getOwnedBlobRow(input);
    if (!row) {
      return null;
    }
    const cacheKey = this.tenantBlobCacheKey({
      userId: input.userId,
      kind: "text",
      row,
    });
    const cached = await this.reliabilityStore.get(cacheKey);
    if (cached) {
      return cached;
    }
    const storedBytes = await this.store.getObjectBytes(row.storageKey);
    if (!storedBytes) {
      return null;
    }
    const text = await decodeTextBlob({
      storedBytes,
      compression: row.compression,
    });
    await this.reliabilityStore.set(cacheKey, text, HOT_CACHE_TTL_MS);
    void this.touchBlob(input.blobId);
    return text;
  }

  public async hydrateJson<T>(blobId: string): Promise<T | null> {
    const cacheKey = `legacy:blob:json:${blobId}`;
    const cached = await this.reliabilityStore.get(cacheKey);
    if (cached) {
      return JSON.parse(cached) as T;
    }

    const row = await this.getBlobRow(blobId);
    if (!row) {
      return null;
    }

    const storedBytes = await this.store.getObjectBytes(row.storageKey);
    if (!storedBytes) {
      return null;
    }

    const value = await decodeJsonBlob<T>({
      storedBytes,
      compression: row.compression,
    });
    await this.reliabilityStore.set(cacheKey, JSON.stringify(value), HOT_CACHE_TTL_MS);
    void this.touchBlob(blobId);
    return value;
  }

  public async hydrateJsonForOwner<T>(input: {
    blobId: string;
    userId: string;
    ownerType: BlobOwnerType;
    ownerId: string;
  }): Promise<T | null> {
    const row = await this.getOwnedBlobRow(input);
    if (!row) {
      return null;
    }
    const cacheKey = this.tenantBlobCacheKey({
      userId: input.userId,
      kind: "json",
      row,
    });
    const cached = await this.reliabilityStore.get(cacheKey);
    if (cached) {
      return JSON.parse(cached) as T;
    }
    const storedBytes = await this.store.getObjectBytes(row.storageKey);
    if (!storedBytes) {
      return null;
    }
    const value = await decodeJsonBlob<T>({
      storedBytes,
      compression: row.compression,
    });
    await this.reliabilityStore.set(cacheKey, JSON.stringify(value), HOT_CACHE_TTL_MS);
    void this.touchBlob(input.blobId);
    return value;
  }

  public async hydrateBytes(blobId: string): Promise<Uint8Array | null> {
    const row = await this.getBlobRow(blobId);
    if (!row) {
      return null;
    }

    const storedBytes = await this.store.getObjectBytes(row.storageKey);
    if (!storedBytes) {
      return null;
    }

    void this.touchBlob(blobId);
    return decodeBlobBytes({
      storedBytes,
      compression: row.compression,
    });
  }

  public async hydrateBytesForOwner(input: {
    blobId: string;
    userId: string;
    ownerType: BlobOwnerType;
    ownerId: string;
  }): Promise<Uint8Array | null> {
    const row = await this.getOwnedBlobRow(input);
    if (!row) {
      return null;
    }

    const storedBytes = await this.store.getObjectBytes(row.storageKey);
    if (!storedBytes) {
      return null;
    }

    void this.touchBlob(input.blobId);
    return decodeBlobBytes({
      storedBytes,
      compression: row.compression,
    });
  }

  public async createDownloadUrl(input: {
    blobId: string;
    fileName?: string | null;
    contentType?: string | null;
  }): Promise<string | null> {
    const row = await this.getBlobRow(input.blobId);
    if (!row) {
      return null;
    }

    return this.store.createDownloadUrl({
      storageKey: row.storageKey,
      fileName: input.fileName,
      contentType: input.contentType ?? row.contentType,
    });
  }

  public async createDownloadUrlForOwner(input: {
    blobId: string;
    userId: string;
    ownerType: BlobOwnerType;
    ownerId: string;
    fileName?: string | null;
    contentType?: string | null;
  }): Promise<string | null> {
    const row = await this.getOwnedBlobRow(input);
    if (!row) {
      return null;
    }

    return this.store.createDownloadUrl({
      storageKey: row.storageKey,
      fileName: input.fileName,
      contentType: input.contentType ?? row.contentType,
    });
  }

  public async createDownloadUrlFromStorageKey(input: {
    storageKey: string;
    fileName?: string | null;
    contentType?: string | null;
  }): Promise<string | null> {
    return this.store.createDownloadUrl(input);
  }

  private async persistEncodedBlob(
    input: {
      ownerType: BlobOwnerType;
      ownerId: string;
      userId?: string;
      slot: string;
      scope: BlobScope;
    },
    encoded: EncodedBlob,
  ): Promise<StoredBlobDescriptor | null> {
    const storageScope = this.storageScope(input.scope, input.userId);
    const existing = await this.findBlobByScopeHash(storageScope, encoded.sha256);
    const row = existing ?? (await this.uploadAndInsertBlob(storageScope, input.scope, input.userId, encoded));
    if (!row) {
      return null;
    }

    await this.db
      .insert(schema.blobReferences)
      .values({
        ownerType: input.ownerType,
        ownerId: input.ownerId,
        slot: input.slot,
        blobId: row.id,
      })
      .onConflictDoNothing({
        target: [
          schema.blobReferences.ownerType,
          schema.blobReferences.ownerId,
          schema.blobReferences.slot,
          schema.blobReferences.blobId,
        ],
      });

    return {
      blobId: row.id,
      contentHash: row.contentSha256,
      storageKey: row.storageKey,
      contentType: row.contentType,
      contentEncoding: row.compression === "zstd" ? "zstd" : "identity",
      byteLength: row.rawSize,
      storedByteLength: row.storedSize,
    };
  }

  private async findBlobByScopeHash(scope: string, sha256: string): Promise<BlobRow | null> {
    const rows = await this.db
      .select()
      .from(schema.blobObjects)
      .where(and(eq(schema.blobObjects.scope, scope), eq(schema.blobObjects.contentSha256, sha256)))
      .limit(1);
    return rows[0] ?? null;
  }

  private async uploadAndInsertBlob(
    storageScope: string,
    publicScope: BlobScope,
    userId: string | undefined,
    encoded: EncodedBlob,
  ): Promise<BlobRow | null> {
    const addressKey = this.createAddressKey(storageScope, encoded.sha256);
    const storageKey = this.storageKey({
      publicScope,
      storageScope,
      userId,
      addressKey,
    });

    if (!(await this.store.objectExists(storageKey))) {
      await this.store.putObject({
        storageKey,
        body: encoded.storedBytes,
        contentType: encoded.contentType,
        metadata: {
          sha256: encoded.sha256,
          compression: encoded.compression,
        },
      });
    }

    const insertRows = await this.db
      .insert(schema.blobObjects)
      .values({
        contentSha256: encoded.sha256,
        scope: storageScope,
        addressKey,
        contentType: encoded.contentType,
        compression: encoded.compression,
        rawSize: encoded.rawSize,
        storedSize: encoded.storedSize,
        storageKey,
      })
      .onConflictDoNothing({
        target: [schema.blobObjects.scope, schema.blobObjects.contentSha256],
      })
      .returning();

    return insertRows[0] ?? (await this.findBlobByScopeHash(storageScope, encoded.sha256));
  }

  private storageScope(scope: BlobScope, userId?: string): string {
    return userId ? `${scope}:tenant:${userId}` : scope;
  }

  private storageKey(input: {
    publicScope: BlobScope;
    storageScope: string;
    userId?: string;
    addressKey: string;
  }): string {
    if (input.userId) {
      return `tenant/${input.userId}/${input.publicScope}/${input.addressKey.slice(0, 2)}/${input.addressKey}`;
    }
    return `${input.storageScope}/${input.addressKey.slice(0, 2)}/${input.addressKey}`;
  }

  private createAddressKey(scope: string, sha256: string): string {
    return createHmac("sha256", this.addressSecret)
      .update(`${scope}:${sha256}`)
      .digest("hex");
  }

  private async getBlobRow(blobId: string): Promise<BlobRow | null> {
    const rows = await this.db
      .select()
      .from(schema.blobObjects)
      .where(eq(schema.blobObjects.id, blobId))
      .limit(1);
    return rows[0] ?? null;
  }

  private async getOwnedBlobRow(input: {
    blobId: string;
    userId: string;
    ownerType: BlobOwnerType;
    ownerId: string;
  }): Promise<BlobRow | null> {
    const references = await this.db
      .select({ id: schema.blobReferences.id })
      .from(schema.blobReferences)
      .where(
        and(
          eq(schema.blobReferences.blobId, input.blobId),
          eq(schema.blobReferences.ownerType, input.ownerType),
          eq(schema.blobReferences.ownerId, input.ownerId),
        ),
      )
      .limit(1);
    if (!references[0]) {
      return null;
    }

    const ownerMatches = await this.verifyOwnerUser(input);
    if (!ownerMatches) {
      return null;
    }

    return this.getBlobRow(input.blobId);
  }

  private async verifyOwnerUser(input: {
    userId: string;
    ownerType: BlobOwnerType;
    ownerId: string;
  }): Promise<boolean> {
    if (input.ownerType === "chat_message") {
      const rows = await this.db
        .select({ id: schema.chatMessages.id })
        .from(schema.chatMessages)
        .where(and(eq(schema.chatMessages.id, input.ownerId), eq(schema.chatMessages.userId, input.userId)))
        .limit(1);
      return rows.length > 0;
    }
    if (input.ownerType === "task") {
      const rows = await this.db
        .select({ id: schema.tasks.id })
        .from(schema.tasks)
        .where(and(eq(schema.tasks.id, input.ownerId), eq(schema.tasks.userId, input.userId)))
        .limit(1);
      return rows.length > 0;
    }
    if (input.ownerType === "artifact") {
      const rows = await this.db
        .select({ id: schema.artifacts.id })
        .from(schema.artifacts)
        .innerJoin(schema.tasks, eq(schema.tasks.id, schema.artifacts.taskId))
        .where(and(eq(schema.artifacts.id, input.ownerId), eq(schema.tasks.userId, input.userId)))
        .limit(1);
      return rows.length > 0;
    }
    if (input.ownerType === "task_event") {
      const rows = await this.db
        .select({ id: schema.taskEvents.id })
        .from(schema.taskEvents)
        .innerJoin(schema.tasks, eq(schema.tasks.id, schema.taskEvents.taskId))
        .where(and(eq(schema.taskEvents.id, input.ownerId), eq(schema.tasks.userId, input.userId)))
        .limit(1);
      return rows.length > 0;
    }
    if (input.ownerType === "realtime_event") {
      const rows = await this.db
        .select({ id: schema.realtimeEvents.id })
        .from(schema.realtimeEvents)
        .where(and(eq(schema.realtimeEvents.id, Number(input.ownerId)), eq(schema.realtimeEvents.userId, input.userId)))
        .limit(1);
      return rows.length > 0;
    }
    return false;
  }

  private tenantBlobCacheKey(input: {
    userId: string;
    kind: "text" | "json";
    row: BlobRow;
  }): string {
    return buildTenantCacheKey({
      userId: input.userId,
      scope: `blob:${input.kind}`,
      parts: [input.row.id, input.row.contentSha256],
    });
  }

  private async touchBlob(blobId: string): Promise<void> {
    await this.db
      .update(schema.blobObjects)
      .set({
        lastAccessedAt: new Date(),
      })
      .where(eq(schema.blobObjects.id, blobId))
      .catch(() => undefined);
  }
}

export function compactStructuredPayloadPreview(value: unknown): Record<string, unknown> | null {
  const record = safeJsonRecord(value);
  if (!Object.keys(record).length) {
    return null;
  }

  const pick = (key: string): unknown => record[key];
  const compact = {
    ...(typeof pick("previewText") === "string" ? { previewText: pick("previewText") } : {}),
    ...(typeof pick("summary") === "string" ? { summary: pick("summary") } : {}),
    ...(typeof pick("output_type") === "string" ? { output_type: pick("output_type") } : {}),
    ...(typeof pick("format") === "string" ? { format: pick("format") } : {}),
    ...(typeof pick("render_on") === "string" ? { render_on: pick("render_on") } : {}),
    ...(typeof pick("mimeType") === "string" ? { mimeType: pick("mimeType") } : {}),
    ...(typeof pick("source") === "string" ? { source: pick("source") } : {}),
    ...(typeof pick("model") === "string" ? { model: pick("model") } : {}),
    ...(typeof pick("revisedPrompt") === "string" ? { revisedPrompt: pick("revisedPrompt") } : {}),
  };

  return Object.keys(compact).length > 0 ? compact : null;
}
