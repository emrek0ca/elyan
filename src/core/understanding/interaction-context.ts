import { createHash } from "node:crypto";
import type { TaskUnderstandingInput } from "./types.js";
import { asRecord as readRecord } from "../../lib/record.js";

export const interactionChannelValues = [
  "mobile",
  "desktop",
  "web",
  "email",
  "whatsapp",
  "unknown",
] as const;

export type InteractionChannel = (typeof interactionChannelValues)[number];

export type InteractionContext = {
  schemaVersion: "interaction_context.v1";
  channel: InteractionChannel;
  profileScope: "canonical_user";
  identityRef: string | null;
  conversationRef: string | null;
  messageRef: string | null;
};

function boundedOpaqueRef(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!/^[A-Za-z0-9._:-]{1,160}$/u.test(trimmed)) return null;
  return `ref_${createHash("sha256").update(trimmed).digest("hex").slice(0, 24)}`;
}

function normalizeChannel(value: unknown): InteractionChannel {
  if (typeof value !== "string") return "unknown";
  const normalized = value.trim().toLowerCase();
  const aliases: Record<string, InteractionChannel> = {
    ios: "mobile",
    android: "mobile",
    flutter: "mobile",
    macos: "desktop",
    windows: "desktop",
    linux: "desktop",
    browser: "web",
    gmail: "email",
    mail: "email",
    "whats-app": "whatsapp",
  };
  const candidate = aliases[normalized] ?? normalized;
  return interactionChannelValues.includes(candidate as InteractionChannel)
    ? (candidate as InteractionChannel)
    : "unknown";
}

/**
 * Channel metadata is attribution only. Authentication already resolved the
 * canonical userId before this seam, so an inbound identityRef can never
 * select or merge another user's profile.
 */
export function resolveInteractionContext(
  input: Pick<TaskUnderstandingInput, "source" | "metadata">,
): InteractionContext {
  const metadata = readRecord(input.metadata);
  const channelContext = readRecord(metadata?.channelContext);
  const contextChannel = normalizeChannel(channelContext?.channel);
  const metadataChannel = normalizeChannel(metadata?.channel);
  const channel =
    contextChannel !== "unknown"
      ? contextChannel
      : metadataChannel !== "unknown"
        ? metadataChannel
        : normalizeChannel(input.source);

  return {
    schemaVersion: "interaction_context.v1",
    channel,
    profileScope: "canonical_user",
    identityRef: boundedOpaqueRef(channelContext?.identityRef),
    conversationRef: boundedOpaqueRef(
      channelContext?.conversationRef ?? channelContext?.conversationId,
    ),
    messageRef: boundedOpaqueRef(
      channelContext?.messageRef ?? channelContext?.messageId,
    ),
  };
}

export function buildLearningProvenance(input: {
  interaction: InteractionContext;
  evidenceBasis:
    | "explicit_user"
    | "user_feedback"
    | "behavioral_inference"
    | "runtime_observation"
    | "system_evaluation";
  observedAt?: Date;
}): Record<string, unknown> {
  return {
    schemaVersion: "learning_provenance.v2",
    profileScope: input.interaction.profileScope,
    channel: input.interaction.channel,
    evidenceBasis: input.evidenceBasis,
    observedAt: (input.observedAt ?? new Date()).toISOString(),
    ...(input.interaction.identityRef
      ? { identityRef: input.interaction.identityRef }
      : {}),
    ...(input.interaction.conversationRef
      ? { conversationRef: input.interaction.conversationRef }
      : {}),
    ...(input.interaction.messageRef
      ? { messageRef: input.interaction.messageRef }
      : {}),
  };
}
