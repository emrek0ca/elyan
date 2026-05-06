import { ElyanProvider, ModelInfo } from '@/types/provider';
import { OllamaProvider } from './ollama';
import { OpenAIProvider } from './openai';
import { GroqProvider } from './groq';
import { AnthropicProvider } from './anthropic';
import { LanguageModel } from 'ai';
import { resolvePreferredModelIdFromAvailableModels, type ModelRoutingSelection } from './routing';

export class ProviderRegistry {
  private providers: Map<string, ElyanProvider> = new Map();

  constructor() {
    this.register(new OllamaProvider());
    this.register(new OpenAIProvider());
    this.register(new GroqProvider());
    this.register(new AnthropicProvider());
  }

  register(provider: ElyanProvider): void {
    this.providers.set(provider.id, provider);
  }

  get(providerId: string): ElyanProvider {
    const provider = this.providers.get(providerId);
    if (!provider) {
      throw new Error(`Provider not found: ${providerId}`);
    }
    return provider;
  }

  async listAvailableModels(): Promise<ModelInfo[]> {
    const allModels: ModelInfo[] = [];

    for (const provider of this.providers.values()) {
      if (await provider.isAvailable()) {
        const models = await provider.listModels();
        allModels.push(...models);
      }
    }

    return allModels.sort((left, right) => {
      if (left.type !== right.type) {
        return left.type === 'local' ? -1 : 1;
      }

      if (left.provider !== right.provider) {
        return left.provider.localeCompare(right.provider);
      }

      return left.name.localeCompare(right.name);
    });
  }

  async resolvePreferredModelId(
    preferredModelIdOrSelection?: string | ModelRoutingSelection,
    routingMode?: ModelRoutingSelection['routingMode']
  ): Promise<string> {
    const availableModels = await this.listAvailableModels();
    return resolvePreferredModelIdFromAvailableModels(availableModels, preferredModelIdOrSelection, routingMode);
  }

  resolveModel(modelIdString: string): { provider: ElyanProvider; model: LanguageModel } {
    let providerId = 'ollama';
    let modelId = modelIdString;

    if (modelIdString.includes(':')) {
      [providerId, modelId] = modelIdString.split(':', 2);
    }

    const provider = this.get(providerId);
    const model = provider.createModel(modelId);

    return { provider, model };
  }
}

// Singleton registry for the app
export const registry = new ProviderRegistry();
