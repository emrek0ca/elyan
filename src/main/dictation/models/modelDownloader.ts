import fs from 'node:fs';
import https from 'node:https';
import path from 'node:path';

export interface DownloadProgress {
  downloadedBytes: number;
  totalBytes: number;
  percent: number;
}

export function downloadModel(url: string, destPath: string, onProgress: (progress: DownloadProgress) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    // Ensure the directory exists
    const dir = path.dirname(destPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    const tempPath = `${destPath}.tmp`;
    const file = fs.createWriteStream(tempPath);

    const request = https.get(url, (response) => {
      // Handle redirects
      if (response.statusCode === 301 || response.statusCode === 302 || response.statusCode === 307 || response.statusCode === 308) {
        const redirectUrl = response.headers.location;
        if (redirectUrl) {
          downloadModel(redirectUrl, destPath, onProgress).then(resolve).catch(reject);
          return;
        }
      }

      if (response.statusCode && response.statusCode >= 400) {
        reject(new Error(`Failed to download model: HTTP ${response.statusCode}`));
        return;
      }

      const totalBytes = parseInt(response.headers['content-length'] || '0', 10);
      let downloadedBytes = 0;

      response.on('data', (chunk: Buffer) => {
        downloadedBytes += chunk.length;
        if (totalBytes > 0) {
          const percent = Math.round((downloadedBytes / totalBytes) * 100);
          onProgress({ downloadedBytes, totalBytes, percent });
        }
      });

      response.pipe(file);

      file.on('finish', () => {
        file.close((err) => {
          if (err) {
            reject(err);
            return;
          }
          try {
            fs.renameSync(tempPath, destPath);
            resolve();
          } catch (renameErr) {
            reject(renameErr);
          }
        });
      });
    });

    request.on('error', (err) => {
      fs.unlink(tempPath, () => {});
      reject(err);
    });
  });
}
