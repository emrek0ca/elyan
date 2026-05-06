import type {
  ControlPlaneConversationThread,
  ControlPlaneConversationMessage,
  ControlPlaneLearningDraft,
  ControlPlaneMemoryItem,
} from '@/core/control-plane/types';
import type { RetrievalDocumentRecord } from '@/core/retrieval';
import { buildContextLayerBlock, filterContextBlocks } from '@/core/retrieval/context';

export type MemoryLayer = 'short_term' | 'episodic' | 'semantic';

export type MemoryContextInput = {
  thread?: ControlPlaneConversationThread;
  messages?: ControlPlaneConversationMessage[];
  memoryItems: ControlPlaneMemoryItem[];
  learningDrafts?: ControlPlaneLearningDraft[];
  semanticDocuments?: RetrievalDocumentRecord[];
};

export type MemoryContextResult = {
  layers: Record<MemoryLayer, string[]>;
  contextBlocks: string[];
};

function buildShortTermLayer(thread?: ControlPlaneConversationThread, messages?: ControlPlaneConversationMessage[]) {
  if (!thread) {
    return [];
  }

  const recentMessages = (messages ?? [])
    .filter((message) => message.threadId === thread.threadId)
    .slice(-4)
    .map((message) => ({
      label: `${message.role}: ${message.createdAt}`,
      summary: message.content,
    }));

  return filterContextBlocks(
    [
      buildContextLayerBlock({
        title: 'Short-term memory',
        entries: [
          {
            label: thread.title,
            summary: thread.summary,
          },
          ...recentMessages,
        ],
      }),
    ],
    { maxTokens: 300, maxBlocks: 2, minScore: 0 }
  );
}

function buildEpisodicLayer(memoryItems: ControlPlaneMemoryItem[], learningDrafts: ControlPlaneLearningDraft[]) {
  return filterContextBlocks(
    [
      buildContextLayerBlock({
        title: 'Episodic memory',
        entries: memoryItems.slice(-6).map((item) => ({
          label: item.title,
          summary: item.summary,
          score: item.confidence,
        })),
      }),
      buildContextLayerBlock({
        title: 'Learning drafts',
        entries: learningDrafts.slice(-4).map((draft) => ({
          label: draft.title,
          summary: draft.summary,
        })),
      }),
    ],
    { maxTokens: 700, maxBlocks: 4, minScore: 0.15 }
  );
}

function buildSemanticLayer(documents: RetrievalDocumentRecord[]) {
  return filterContextBlocks(
    documents.slice(0, 6).map((document) => ({
      text: [
        `Semantic memory ${document.title?.trim() || document.sourceName}`,
        document.sourceUrl ? `URL: ${document.sourceUrl}` : '',
        document.content,
      ]
        .filter(Boolean)
        .join('\n'),
      score: document.combinedScore ?? document.similarity ?? document.keywordScore ?? 0,
    })),
    { maxTokens: 1_200, maxBlocks: 4, minScore: 0.2 }
  );
}

export function buildMemoryContext(input: MemoryContextInput): MemoryContextResult {
  const layers: Record<MemoryLayer, string[]> = {
    short_term: buildShortTermLayer(input.thread, input.messages),
    episodic: buildEpisodicLayer(input.memoryItems, input.learningDrafts ?? []),
    semantic: buildSemanticLayer(input.semanticDocuments ?? []),
  };

  const contextBlocks = filterContextBlocks(
    [...layers.short_term, ...layers.episodic, ...layers.semantic],
    { maxTokens: 1_800, maxBlocks: 8, minScore: 0.15 }
  );

  return {
    layers,
    contextBlocks,
  };
}
