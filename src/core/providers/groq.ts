import { ElyanProvider, ModelInfo } from '@/types/provider';
import { createOpenAI } from '@ai-sdk/openai';
import { LanguageModel } from 'ai';

const GROQ_MODELS = [
  'llama-3.3-70b-versatile',
  'llama-3.1-8b-instant',
  'llama-3.1-70b-versatile',
  'mixtral-8x7b-32768',
  'gemma2-9b-it',
];

export class GroqProvider implements ElyanProvider {
  id = 'groq';
  name = 'Groq';
  type = 'cloud' as const;

  private apiKey: string;

  constructor(apiKey?: string) {
    this.apiKey = apiKey || process.env.GROQ_API_KEY || '';
  }

  async isAvailable(): Promise<boolean> {
    return !!this.apiKey;
  }

  async listModels(): Promise<ModelInfo[]> {
    if (!await this.isAvailable()) return [];
    
    return GROQ_MODELS.map(m => ({
      id: `groq:${m}`,
      name: m,
      provider: 'groq',
      type: 'cloud',
    }));
  }

  createModel(modelId: string): LanguageModel {
    if (!this.apiKey) {
      throw new Error('Groq API key not configured');
    }
    
    // Groq provides an OpenAI compatible API
    const groq = createOpenAI({
      apiKey: this.apiKey,
      baseURL: 'https://api.groq.com/openai/v1',
    });
    
    const parsedId = modelId.startsWith('groq:') ? modelId.slice(5) : modelId;
    return groq(parsedId) as unknown as LanguageModel;
  }
}
