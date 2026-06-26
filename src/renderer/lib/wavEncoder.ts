export async function convertWebmToWav(blob: Blob): Promise<Blob> {
  const arrayBuffer = await blob.arrayBuffer();
  const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 });
  const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

  const numChannels = 1; // force mono
  const sampleRate = 16000; // whisper requires 16kHz
  
  // Mixdown to mono if there are multiple channels
  let channelData = audioBuffer.getChannelData(0);
  if (audioBuffer.numberOfChannels > 1) {
    const mixed = new Float32Array(audioBuffer.length);
    for (let i = 0; i < audioBuffer.numberOfChannels; i++) {
      const cData = audioBuffer.getChannelData(i);
      for (let j = 0; j < audioBuffer.length; j++) {
        mixed[j] = (mixed[j] || 0) + ((cData[j] || 0) / audioBuffer.numberOfChannels);
      }
    }
    channelData = mixed;
  }

  // 16-bit PCM WAV
  const length = channelData.length * 2; // 2 bytes per sample
  const buffer = new ArrayBuffer(44 + length);
  const view = new DataView(buffer);

  // RIFF header
  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + length, true);
  writeString(view, 8, 'WAVE');

  // fmt subchunk
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true); // Subchunk1Size (16 for PCM)
  view.setUint16(20, 1, true); // AudioFormat (1 for PCM)
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * numChannels * 2, true); // ByteRate
  view.setUint16(32, numChannels * 2, true); // BlockAlign
  view.setUint16(34, 16, true); // BitsPerSample

  // data subchunk
  writeString(view, 36, 'data');
  view.setUint32(40, length, true);

  // PCM data
  let offset = 44;
  for (let i = 0; i < channelData.length; i++, offset += 2) {
    let s = Math.max(-1, Math.min(1, channelData[i] || 0));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }

  return new Blob([view], { type: 'audio/wav' });
}

function writeString(view: DataView, offset: number, string: string) {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i));
  }
}
