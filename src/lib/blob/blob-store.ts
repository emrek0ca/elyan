import { GetObjectCommand, HeadObjectCommand, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import type { AppEnv } from "../../config/env.js";

export type BlobStorePutInput = {
  storageKey: string;
  body: Uint8Array;
  contentType: string;
  metadata?: Record<string, string>;
};

export class BlobStore {
  private readonly client: S3Client | null;
  private readonly bucket: string;
  private readonly signedUrlTtlSeconds: number;

  public constructor(private readonly env: Pick<
    AppEnv,
    | "BLOB_STORAGE_BUCKET"
    | "BLOB_STORAGE_REGION"
    | "BLOB_STORAGE_ENDPOINT"
    | "BLOB_STORAGE_ACCESS_KEY_ID"
    | "BLOB_STORAGE_SECRET_ACCESS_KEY"
    | "BLOB_STORAGE_FORCE_PATH_STYLE"
    | "BLOB_STORAGE_SIGNED_URL_TTL_SECONDS"
  >) {
    this.bucket = env.BLOB_STORAGE_BUCKET.trim();
    this.signedUrlTtlSeconds = env.BLOB_STORAGE_SIGNED_URL_TTL_SECONDS;

    if (
      !this.bucket ||
      !env.BLOB_STORAGE_REGION.trim() ||
      !env.BLOB_STORAGE_ACCESS_KEY_ID.trim() ||
      !env.BLOB_STORAGE_SECRET_ACCESS_KEY.trim()
    ) {
      this.client = null;
      return;
    }

    this.client = new S3Client({
      region: env.BLOB_STORAGE_REGION.trim(),
      endpoint: env.BLOB_STORAGE_ENDPOINT.trim() || undefined,
      forcePathStyle: env.BLOB_STORAGE_FORCE_PATH_STYLE,
      credentials: {
        accessKeyId: env.BLOB_STORAGE_ACCESS_KEY_ID.trim(),
        secretAccessKey: env.BLOB_STORAGE_SECRET_ACCESS_KEY.trim(),
      },
    });
  }

  public isConfigured(): boolean {
    return this.client !== null;
  }

  public async putObject(input: BlobStorePutInput): Promise<void> {
    if (!this.client) {
      throw new Error("blob_store_unconfigured");
    }

    await this.client.send(
      new PutObjectCommand({
        Bucket: this.bucket,
        Key: input.storageKey,
        Body: input.body,
        ContentType: input.contentType,
        Metadata: input.metadata,
      }),
    );
  }

  public async objectExists(storageKey: string): Promise<boolean> {
    if (!this.client) {
      return false;
    }

    try {
      await this.client.send(
        new HeadObjectCommand({
          Bucket: this.bucket,
          Key: storageKey,
        }),
      );
      return true;
    } catch {
      return false;
    }
  }

  public async getObjectBytes(storageKey: string): Promise<Uint8Array | null> {
    if (!this.client) {
      return null;
    }

    try {
      const response = await this.client.send(
        new GetObjectCommand({
          Bucket: this.bucket,
          Key: storageKey,
        }),
      );
      if (!response.Body) {
        return null;
      }
      return await response.Body.transformToByteArray();
    } catch {
      return null;
    }
  }

  public async createDownloadUrl(input: {
    storageKey: string;
    fileName?: string | null;
    contentType?: string | null;
  }): Promise<string | null> {
    if (!this.client) {
      return null;
    }

    return getSignedUrl(
      this.client,
      new GetObjectCommand({
        Bucket: this.bucket,
        Key: input.storageKey,
        ...(input.contentType ? { ResponseContentType: input.contentType } : {}),
        ...(input.fileName
          ? {
              ResponseContentDisposition: `attachment; filename="${input.fileName.replace(/"/g, "")}"`,
            }
          : {}),
      }),
      {
        expiresIn: this.signedUrlTtlSeconds,
      },
    );
  }
}
