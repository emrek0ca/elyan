export interface ParsedLocalFile {
  fileName: string;
  mimeType: string;
  sizeBytes: number;
  extractedText?: string;
  base64Data?: string;
  isImage: boolean;
  isTextBased: boolean;
}

const TEXT_MIME_TYPES = [
  'text/plain',
  'text/markdown',
  'text/csv',
  'application/json',
  'text/html'
];

const TEXT_EXTENSIONS = ['.txt', '.md', '.csv', '.json', '.html'];

const IMAGE_MIME_TYPES = [
  'image/jpeg',
  'image/png',
  'image/webp',
  'image/gif',
  'image/svg+xml'
];

export async function parseLocalFile(file: File): Promise<ParsedLocalFile> {
  const isTextMime = TEXT_MIME_TYPES.includes(file.type);
  const isTextExt = TEXT_EXTENSIONS.some(ext => file.name.toLowerCase().endsWith(ext));
  const isTextBased = isTextMime || isTextExt;
  
  const isImage = IMAGE_MIME_TYPES.includes(file.type) || file.type.startsWith('image/');

  let extractedText: string | undefined = undefined;
  let base64Data: string | undefined = undefined;

  if (isTextBased) {
    try {
      extractedText = await file.text();
    } catch (e) {
      console.warn("Could not read text file:", e);
    }
  } else if (isImage) {
    try {
      base64Data = await readAsBase64(file);
    } catch (e) {
      console.warn("Could not read image file:", e);
    }
  }

  return {
    fileName: file.name,
    mimeType: file.type || 'application/octet-stream',
    sizeBytes: file.size,
    extractedText,
    base64Data,
    isImage,
    isTextBased
  };
}

function readAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        resolve(reader.result.split(',')[1]); // return only the base64 part
      } else {
        reject(new Error("Failed to read base64"));
      }
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
