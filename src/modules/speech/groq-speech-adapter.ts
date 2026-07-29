import Groq, { APIUserAbortError, toFile } from "groq-sdk";
import { AppError } from "../../lib/errors.js";

const DEFAULT_MODEL = "whisper-large-v3-turbo";
const TRANSCRIPTION_TIMEOUT_MS = 30_000;

export type SpeechTranscriptionInput = {
  audio: Buffer;
  contentType: string;
  language?: string;
  signal?: AbortSignal;
};

export type SpeechTranscriptionResult = {
  text: string;
  language: string | null;
  model: string;
};

type GroqTranscriptionClient = Pick<Groq, "audio">;

export async function transcribeSpeechWithGroq(
  config: {
    GROQ_API_KEY: string;
    GROQ_BASE_URL: string;
    GROQ_TRANSCRIBE_MODEL?: string;
  },
  input: SpeechTranscriptionInput,
  client?: GroqTranscriptionClient,
): Promise<SpeechTranscriptionResult> {
  const apiKey = config.GROQ_API_KEY.trim();
  if (!apiKey && !client) {
    throw new AppError(
      503,
      "speech_provider_unavailable",
      "Sesli giriş şu anda kullanılamıyor.",
    );
  }

  const model = config.GROQ_TRANSCRIBE_MODEL?.trim() || DEFAULT_MODEL;
  const groq =
    client ??
    new Groq({
      apiKey,
      baseURL: groqSdkBaseUrl(config.GROQ_BASE_URL),
      timeout: TRANSCRIPTION_TIMEOUT_MS,
      // Audio transcription can be billable even when the response times out.
      // The mobile conversation controller keeps the transcript draft and lets
      // the user retry explicitly, so an implicit duplicate upload is unsafe.
      maxRetries: 0,
    });

  try {
    if (input.signal?.aborted) {
      throw new APIUserAbortError();
    }
    const file = await toFile(input.audio, "voice.m4a", {
      type: input.contentType,
    });
    const response = await groq.audio.transcriptions.create(
      {
        file,
        model,
        language: input.language,
        response_format: "json",
        temperature: 0,
      },
      { timeout: TRANSCRIPTION_TIMEOUT_MS, signal: input.signal },
    );
    const text = response.text.replace(/\s+/g, " ").trim();
    if (!text) {
      throw new AppError(
        422,
        "speech_not_detected",
        "Konuşma algılanamadı. Tekrar deneyin.",
      );
    }
    return {
      text,
      language: input.language ?? null,
      model,
    };
  } catch (error) {
    if (error instanceof AppError) {
      throw error;
    }
    if (input.signal?.aborted || error instanceof APIUserAbortError) {
      throw new AppError(
        503,
        "speech_transcription_failed",
        "Ses yazıya çevrilemedi. Tekrar deneyin.",
      );
    }
    throw new AppError(
      503,
      "speech_transcription_failed",
      "Ses yazıya çevrilemedi. Tekrar deneyin.",
    );
  }
}

export function groqSdkBaseUrl(baseUrl: string): string {
  return baseUrl.trim().replace(/\/openai\/v1\/?$/i, "").replace(/\/$/, "");
}
