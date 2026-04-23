import { LanguageModel } from 'ai';

export interface ModelInfo {
  id: string; // e.g., "ollama:llama3" or "openai:gpt-4o"
  name: string;
  provider: string;
  type: 'local' | 'cloud';
}

export interface ElyanProvider {
  id: string; // "ollama", "openai", "groq", "anthropic"
  name: string;
  type: 'local' | 'cloud';
  
  isAvailable(): Promise<boolean>;
  listModels(): Promise<ModelInfo[]>;
  createModel(modelId: string): LanguageModel;
}
