import fs from 'node:fs/promises';
import path from 'node:path';
import { safeStorage } from 'electron';

export interface ProviderVaultStatus {
  available: boolean;
  persistent: boolean;
  backend: string;
  reason: string | null;
  providerIds: string[];
}

interface PersistedVaultFile {
  version: 1;
  secrets: Record<string, string>;
}

export class ProviderVault {
  private readonly filePath: string;
  private readonly sessionSecrets = new Map<string, string>();
  private readonly encryptedAvailable: Promise<boolean>;

  constructor(private readonly userDataPath: string, private readonly platform: NodeJS.Platform) {
    this.filePath = path.join(userDataPath, 'provider-vault.json');
    this.encryptedAvailable = Promise.resolve(safeStorage.isAsyncEncryptionAvailable());
  }

  async getStatus(): Promise<ProviderVaultStatus> {
    const persistent = await this.canPersist();
    const providerIds = await this.listProviderIds();
    return {
      available: true,
      persistent,
      backend: this.backendName(),
      reason: persistent ? null : this.persistenceUnavailableReason(),
      providerIds,
    };
  }

  async listProviderIds(): Promise<string[]> {
    const sessionIds = [...this.sessionSecrets.keys()];
    if (!(await this.canPersist())) {
      return sessionIds.sort();
    }
    const diskSecrets = await this.readDiskSecrets();
    return [...new Set([...sessionIds, ...Object.keys(diskSecrets)])].sort();
  }

  async listSecrets(): Promise<Record<string, string>> {
    const merged: Record<string, string> = {};
    if (await this.canPersist()) {
      Object.assign(merged, await this.readDiskSecrets());
    }
    for (const [providerId, secret] of this.sessionSecrets.entries()) {
      merged[providerId] = secret;
    }
    return merged;
  }

  async saveSecret(providerId: string, secret: string): Promise<ProviderVaultStatus> {
    const normalizedProviderId = providerId.trim().toLowerCase();
    const normalizedSecret = secret.trim();
    if (!normalizedProviderId || !normalizedSecret) {
      throw new Error('provider_secret_invalid');
    }
    this.sessionSecrets.set(normalizedProviderId, normalizedSecret);
    if (await this.canPersist()) {
      const diskSecrets = await this.readDiskSecrets();
      diskSecrets[normalizedProviderId] = normalizedSecret;
      await this.writeDiskSecrets(diskSecrets);
    }
    return this.getStatus();
  }

  async removeSecret(providerId: string): Promise<ProviderVaultStatus> {
    const normalizedProviderId = providerId.trim().toLowerCase();
    this.sessionSecrets.delete(normalizedProviderId);
    if (await this.canPersist()) {
      const diskSecrets = await this.readDiskSecrets();
      delete diskSecrets[normalizedProviderId];
      await this.writeDiskSecrets(diskSecrets);
    }
    return this.getStatus();
  }

  private backendName(): string {
    if (this.platform !== 'linux') {
      return 'safe_storage';
    }
    return safeStorage.getSelectedStorageBackend();
  }

  private persistenceUnavailableReason(): string | null {
    if (this.platform !== 'linux') {
      return 'safe_storage_unavailable';
    }
    if (safeStorage.getSelectedStorageBackend() === 'basic_text') {
      return 'linux_secure_store_unavailable';
    }
    return 'safe_storage_unavailable';
  }

  private async canPersist(): Promise<boolean> {
    const asyncAvailable = await this.encryptedAvailable.catch(() => false);
    if (!asyncAvailable) {
      return false;
    }
    if (this.platform === 'linux' && safeStorage.getSelectedStorageBackend() === 'basic_text') {
      return false;
    }
    return true;
  }

  private async readDiskSecrets(): Promise<Record<string, string>> {
    if (!(await this.canPersist())) {
      return {};
    }
    try {
      const raw = await fs.readFile(this.filePath, 'utf-8');
      const parsed = JSON.parse(raw) as PersistedVaultFile;
      const secrets: Record<string, string> = {};
      for (const [providerId, encryptedBase64] of Object.entries(parsed.secrets ?? {})) {
        const decrypted = await safeStorage.decryptStringAsync(Buffer.from(encryptedBase64, 'base64'));
        secrets[providerId] = decrypted.result;
      }
      return secrets;
    } catch {
      return {};
    }
  }

  private async writeDiskSecrets(secrets: Record<string, string>): Promise<void> {
    if (!(await this.canPersist())) {
      return;
    }
    const encryptedEntries = await Promise.all(
      Object.entries(secrets).map(async ([providerId, secret]) => {
        const encrypted = await safeStorage.encryptStringAsync(secret);
        return [providerId, encrypted.toString('base64')] as const;
      }),
    );
    const payload: PersistedVaultFile = {
      version: 1,
      secrets: Object.fromEntries(encryptedEntries),
    };
    await fs.mkdir(this.userDataPath, { recursive: true });
    await fs.writeFile(this.filePath, JSON.stringify(payload, null, 2), 'utf-8');
  }
}
