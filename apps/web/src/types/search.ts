export interface SearxNGResult {
  url: string;
  title: string;
  content: string;
  engine: string;
  category: string;
  publishedDate?: string;
  thumbnail?: string;
  score: number;
}

export interface SearchOptions {
  categories?: string[];
  engines?: string[];
  language?: string;
  timeRange?: string;
  pageNo?: number;
  signal?: AbortSignal;
}

export interface ScrapedContent {
  url: string;
  title: string;
  content: string;
  wordCount: number;
  extractedAt: Date;
}

export type SearchMode = 'speed' | 'research';
