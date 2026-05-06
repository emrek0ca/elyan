import { ElyanProvider, ModelInfo } from '@/types/provider';
import { createOpenAI } from '@ai-sdk/openai';
import { LanguageModel } from 'ai';

const OPENAI_MODELS = [
  'gpt-4o',
  'gpt-4o-mini',
  'gpt-4-turbo',
  'gpt-3.5-turbo',
  'o1-mini',
  'o1-preview',
];

export class OpenAIProvider implements ElyanProvider {
  id = 'openai';
  name = 'OpenAI';
  type = 'cloud' as const;

  private apiKey: string;

  constructor(apiKey?: string) {
    this.apiKey = apiKey || process.env.OPENAI_API_KEY || '';
  }

  async isAvailable(): Promise<boolean> {
    return !!this.apiKey;
  }

  async listModels(): Promise<ModelInfo[]> {
    if (!await this.isAvailable()) return [];
    
    return OPENAI_MODELS.map(m => ({
      id: `openai:${m}`,
      name: m,
      provider: 'openai',
      type: 'cloud',
    }));
  }

  createModel(modelId: string): LanguageModel {
    if (!this.apiKey) {
      throw new Error('OpenAI API key not configured');
    }
    
    const openai = createOpenAI({
      apiKey: this.apiKey,
    });
    
    const parsedId = modelId.startsWith('openai:') ? modelId.slice(7) : modelId;
    return openai(parsedId) as unknown as LanguageModel;
  }
}
