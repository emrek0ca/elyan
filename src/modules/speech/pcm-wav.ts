/**
 * Groq's transcription endpoint takes an audio *file*, not a raw sample buffer.
 * The live path holds 16 kHz mono PCM, so every window has to be given a
 * container before it can be sent. WAV is the cheapest one that exists: a
 * 44-byte header and the samples verbatim, no encoder and no re-sampling.
 *
 * Kept apart from the session engine because that module is deliberately free
 * of provider details.
 */

import { BYTES_PER_SAMPLE, SAMPLE_RATE_HZ } from "./streaming-session.js";

export const WAV_HEADER_BYTES = 44;
export const WAV_CONTENT_TYPE = "audio/wav";

/** Wrap 16-bit little-endian mono PCM in a canonical WAV container. */
export function pcmToWav(
  pcm: Buffer,
  sampleRateHz: number = SAMPLE_RATE_HZ,
): Buffer {
  const channels = 1;
  const bitsPerSample = BYTES_PER_SAMPLE * 8;
  const byteRate = sampleRateHz * channels * BYTES_PER_SAMPLE;
  const blockAlign = channels * BYTES_PER_SAMPLE;
  const header = Buffer.alloc(WAV_HEADER_BYTES);

  header.write("RIFF", 0, "ascii");
  // RIFF chunk size counts everything after this field.
  header.writeUInt32LE(36 + pcm.length, 4);
  header.write("WAVE", 8, "ascii");
  header.write("fmt ", 12, "ascii");
  header.writeUInt32LE(16, 16); // PCM fmt chunk length
  header.writeUInt16LE(1, 20); // format 1 = uncompressed PCM
  header.writeUInt16LE(channels, 22);
  header.writeUInt32LE(sampleRateHz, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(bitsPerSample, 34);
  header.write("data", 36, "ascii");
  header.writeUInt32LE(pcm.length, 40);

  return Buffer.concat([header, pcm]);
}
