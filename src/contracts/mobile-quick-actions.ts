export type MobileQuickActionSource = "catalog" | "semantic";

export type MobileQuickActionContext = {
  sessionId?: string;
  messageId?: string;
  taskId?: string;
};

export const MOBILE_QUICK_ACTION_IDS = [
  "summarize_content",
  "create_image",
  "make_a_plan",
  "research_topic",
  "search_local_files",
] as const;
