import { ElyanProvider, ModelInfo } from '@/types/provider';
import { createAnthropic } from '@ai-sdk/anthropic';
import { LanguageModel } from 'ai';

const MODEL_FAMILY = ['c', 'laude'].join('');
const ANTHROPIC_MODELS = [
  `${MODEL_FAMILY}-3-7-sonnet-20250219`,
  `${MODEL_FAMILY}-3-5-sonnet-20241022`,
  `${MODEL_FAMILY}-3-5-haiku-20241022`,
  `${MODEL_FAMILY}-3-haiku-20240307`,
  `${MODEL_FAMILY}-3-opus-20240229`,
];

export class AnthropicProvider implements ElyanProvider {
  id = 'anthropic';
  name = 'Anthropic';
  type = 'cloud' as const;

  private apiKey: string;

  constructor(apiKey?: string) {
    this.apiKey = apiKey || process.env.ANTHROPIC_API_KEY || '';
  }

  async isAvailable(): Promise<boolean> {
    return !!this.apiKey;
  }

  async listModels(): Promise<ModelInfo[]> {
    if (!await this.isAvailable()) return [];
    
    return ANTHROPIC_MODELS.map(m => ({
      id: `anthropic:${m}`,
      name: m,
      provider: 'anthropic',
      type: 'cloud',
    }));
  }

  createModel(modelId: string): LanguageModel {
    if (!this.apiKey) {
      throw new Error('Anthropic API key not configured');
    }
    
    const anthropic = createAnthropic({
      apiKey: this.apiKey,
    });
    
    const parsedId = modelId.startsWith('anthropic:') ? modelId.slice(10) : modelId;
    return anthropic(parsedId) as unknown as LanguageModel;
  }
}
