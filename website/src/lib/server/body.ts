export class RequestBodyError extends Error {
  constructor(public status: number, public code: string) {
    super(code);
  }
}

export async function readLimitedBody(request: Request, limit: number): Promise<Uint8Array> {
  const declaredLength = Number(request.headers.get('content-length') || 0);
  if (Number.isFinite(declaredLength) && declaredLength > limit) throw new RequestBodyError(413, 'payload_too_large');
  if (!request.body) return new Uint8Array();

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > limit) {
        await reader.cancel('payload_too_large');
        throw new RequestBodyError(413, 'payload_too_large');
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

export async function readLimitedJson(request: Request, limit = 64 * 1024): Promise<Record<string, unknown>> {
  const body = await readLimitedBody(request, limit);
  try {
    const parsed = JSON.parse(new TextDecoder().decode(body));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('invalid_json');
    return parsed as Record<string, unknown>;
  } catch {
    throw new RequestBodyError(400, 'validation_error');
  }
}

export async function readLimitedFormData(request: Request, limit = 64 * 1024): Promise<FormData> {
  const body = await readLimitedBody(request, limit);
  try {
    const buffer = Uint8Array.from(body).buffer;
    return await new Response(buffer, {
      headers: { 'content-type': request.headers.get('content-type') || 'application/x-www-form-urlencoded' },
    }).formData();
  } catch {
    throw new RequestBodyError(400, 'validation_error');
  }
}
