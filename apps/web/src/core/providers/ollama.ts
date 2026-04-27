import { ElyanProvider, ModelInfo } from '@/types/provider';
import { createOpenAI } from '@ai-sdk/openai';
import { LanguageModel } from 'ai';

export class OllamaProvider implements ElyanProvider {
  id = 'ollama';
  name = 'Ollama (Local)';
  type = 'local' as const;
  
  private baseURL: string;

  constructor(baseURL?: string) {
    this.baseURL = baseURL || process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
  }

  async isAvailable(): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseURL}/api/version`, {
        signal: AbortSignal.timeout(2000)
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  async listModels(): Promise<ModelInfo[]> {
    try {
      const response = await fetch(`${this.baseURL}/api/tags`);
      if (!response.ok) return [];
      
      const data = await response.json();
      return (data.models || []).map((m: { name: string }) => ({
        id: `ollama:${m.name}`,
        name: m.name,
        provider: 'ollama',
        type: 'local',
      }));
    } catch {
      return [];
    }
  }

  createModel(modelId: string): LanguageModel {
    const ollama = createOpenAI({
      apiKey: 'ollama',
      baseURL: `${this.baseURL.replace(/\/$/, '')}/v1`,
    });

    const parsedId = modelId.startsWith('ollama:') ? modelId.slice(7) : modelId;
    return ollama(parsedId) as unknown as LanguageModel;
  }
}
