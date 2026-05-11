import { and, desc, eq, inArray, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import type { AiProvider, ArtifactInput, TaskStatus } from "../../contracts/domain.js";
import { artifacts, devices, taskEvents, tasks } from "../../db/schema.js";
import { conflict, notFound } from "../../lib/errors.js";
import type { RuntimeAuthTokenPayload } from "../../types/auth.js";
import { assertTaskTransition, isTerminalTaskStatus } from "./transitions.js";

async function insertTaskEvent(
  app: FastifyInstance,
  input: {
    taskId: string;
    status: TaskStatus;
    message?: string;
    payload?: Record<string, unknown>;
  },
) {
  await app.db.insert(taskEvents).values({
    taskId: input.taskId,
    status: input.status,
    message: input.message,
    payload: input.payload,
  });
}

async function persistArtifacts(app: FastifyInstance, taskId: string, items: ArtifactInput[]) {
  if (!items.length) {
    return [];
  }

  return app.db
    .insert(artifacts)
    .values(
      items.map((artifact) => ({
        taskId,
        kind: artifact.kind,
        name: artifact.name,
        contentType: artifact.contentType,
        storageKey: artifact.storageKey,
        textContent: artifact.textContent,
        payload: artifact.payload,
        metadata: artifact.metadata ?? {},
      })),
    )
    .returning();
}

async function getOwnedDesktopDevice(app: FastifyInstance, userId: string, targetDeviceId: string) {
  const rows = await app.db
    .select({
      id: devices.id,
      userId: devices.userId,
      type: devices.type,
      label: devices.label,
      isActive: devices.isActive,
    })
    .from(devices)
    .where(and(eq(devices.id, targetDeviceId), eq(devices.userId, userId)))
    .limit(1);

  const device = rows[0];

  if (!device || device.type !== "desktop") {
    throw notFound("Target desktop runtime not found");
  }

  if (!device.isActive) {
    throw conflict("Target desktop runtime is inactive");
  }

  return device;
}

async function getTaskForUser(app: FastifyInstance, taskId: string, userId: string) {
  const rows = await app.db.select().from(tasks).where(and(eq(tasks.id, taskId), eq(tasks.userId, userId))).limit(1);
  const task = rows[0];

  if (!task) {
    throw notFound("Task not found");
  }

  return task;
}

async function getTaskForRuntime(app: FastifyInstance, taskId: string, auth: RuntimeAuthTokenPayload) {
  const rows = await app.db
    .select()
    .from(tasks)
    .where(and(eq(tasks.id, taskId), eq(tasks.userId, auth.sub), eq(tasks.targetDeviceId, auth.deviceId)))
    .limit(1);

  const task = rows[0];

  if (!task) {
    throw notFound("Task not found for this runtime");
  }

  return task;
}

function publishTaskEvent(app: FastifyInstance, task: typeof tasks.$inferSelect, topic: string, payload: unknown): void {
  app.services.eventBus.publish({
    topic,
    userId: task.userId,
    deviceId: task.targetDeviceId,
    taskId: task.id,
    payload,
  });
}

export async function createTask(
  app: FastifyInstance,
  input: {
    userId: string;
    targetDeviceId: string;
    title: string;
    payload: Record<string, unknown>;
    requestedCapabilities: string[];
    preferredAiProvider?: AiProvider;
  },
) {
  await getOwnedDesktopDevice(app, input.userId, input.targetDeviceId);

  const activeCounts = await app.db
    .select({
      count: sql<number>`count(*)`,
    })
    .from(tasks)
    .where(
      and(
        eq(tasks.targetDeviceId, input.targetDeviceId),
        inArray(tasks.status, ["queued", "planning", "running", "waiting_approval"]),
      ),
    );

  const queuePosition = Number(activeCounts[0]?.count ?? 0) + 1;
  const rows = await app.db
    .insert(tasks)
    .values({
      userId: input.userId,
      targetDeviceId: input.targetDeviceId,
      title: input.title,
      payload: input.payload,
      requestedCapabilities: input.requestedCapabilities,
      preferredAiProvider: input.preferredAiProvider,
      queuePosition,
    })
    .returning();

  const task = rows[0];

  await insertTaskEvent(app, {
    taskId: task.id,
    status: "queued",
    message: "Task queued",
  });

  publishTaskEvent(app, task, "task.queued", {
    task,
  });

  const dispatched = app.services.realtimeHub.sendToRuntime(task.targetDeviceId, {
    type: "task.dispatch",
    task,
  });

  return {
    task,
    dispatched,
  };
}

export async function listTasks(
  app: FastifyInstance,
  input: {
    userId: string;
    targetDeviceId?: string;
    statuses?: TaskStatus[];
    limit: number;
  },
) {
  const conditions = [eq(tasks.userId, input.userId)];

  if (input.targetDeviceId) {
    conditions.push(eq(tasks.targetDeviceId, input.targetDeviceId));
  }

  if (input.statuses?.length) {
    conditions.push(inArray(tasks.status, input.statuses));
  }

  return app.db.select().from(tasks).where(and(...conditions)).orderBy(desc(tasks.createdAt)).limit(input.limit);
}

export async function getTaskDetail(app: FastifyInstance, taskId: string, userId: string) {
  const task = await getTaskForUser(app, taskId, userId);
  const events = await app.db
    .select()
    .from(taskEvents)
    .where(eq(taskEvents.taskId, task.id))
    .orderBy(taskEvents.createdAt);
  const taskArtifacts = await app.db
    .select()
    .from(artifacts)
    .where(eq(artifacts.taskId, task.id))
    .orderBy(artifacts.createdAt);

  return {
    task,
    events,
    artifacts: taskArtifacts,
  };
}

export async function cancelTask(app: FastifyInstance, taskId: string, userId: string) {
  const task = await getTaskForUser(app, taskId, userId);

  if (isTerminalTaskStatus(task.status)) {
    throw conflict("Task is already terminal");
  }

  const rows = await app.db
    .update(tasks)
    .set({
      status: "canceled",
      canceledAt: new Date(),
      updatedAt: new Date(),
    })
    .where(eq(tasks.id, task.id))
    .returning();

  const updatedTask = rows[0];

  await insertTaskEvent(app, {
    taskId: task.id,
    status: "canceled",
    message: "Task canceled by user",
  });

  publishTaskEvent(app, updatedTask, "task.canceled", {
    task: updatedTask,
  });

  app.services.realtimeHub.sendToRuntime(updatedTask.targetDeviceId, {
    type: "task.cancel",
    taskId: updatedTask.id,
  });

  return {
    task: updatedTask,
  };
}

export async function resolveTaskApproval(
  app: FastifyInstance,
  input: {
    taskId: string;
    userId: string;
    approved: boolean;
    notes?: string;
  },
) {
  const task = await getTaskForUser(app, input.taskId, input.userId);

  if (task.status !== "waiting_approval") {
    throw conflict("Task is not waiting for approval");
  }

  if (!input.approved) {
    return cancelTask(app, task.id, task.userId);
  }

  await insertTaskEvent(app, {
    taskId: task.id,
    status: task.status,
    message: "Approval granted by user",
    payload: {
      notes: input.notes,
    },
  });

  publishTaskEvent(app, task, "task.approval_granted", {
    taskId: task.id,
    approved: true,
    notes: input.notes,
  });

  app.services.realtimeHub.sendToRuntime(task.targetDeviceId, {
    type: "task.approval",
    taskId: task.id,
    approved: true,
    notes: input.notes,
  });

  return {
    taskId: task.id,
    status: task.status,
    approved: true,
  };
}

export async function updateTaskFromRuntime(
  app: FastifyInstance,
  auth: RuntimeAuthTokenPayload,
  taskId: string,
  input: {
    status: TaskStatus;
    message?: string;
    summary?: string;
    error?: string;
    approvalRequest?: Record<string, unknown>;
    result?: Record<string, unknown>;
    artifacts: ArtifactInput[];
  },
) {
  const task = await getTaskForRuntime(app, taskId, auth);
  assertTaskTransition(task.status, input.status);

  const updates: Partial<typeof tasks.$inferInsert> = {
    status: input.status,
    summary: input.summary ?? task.summary,
    error: input.error ?? task.error,
    approvalRequest: input.approvalRequest ?? task.approvalRequest,
    result: input.result ?? task.result,
    updatedAt: new Date(),
  };

  if (input.status === "running" && !task.startedAt) {
    updates.startedAt = new Date();
  }

  if (input.status === "completed") {
    updates.completedAt = new Date();
  }

  if (input.status === "canceled") {
    updates.canceledAt = new Date();
  }

  const rows = await app.db.update(tasks).set(updates).where(eq(tasks.id, task.id)).returning();
  const updatedTask = rows[0];
  const storedArtifacts = await persistArtifacts(app, task.id, input.artifacts);

  await insertTaskEvent(app, {
    taskId: task.id,
    status: input.status,
    message: input.message,
    payload: {
      summary: input.summary,
      error: input.error,
      approvalRequest: input.approvalRequest,
      artifactCount: storedArtifacts.length,
    },
  });

  publishTaskEvent(app, updatedTask, "task.updated", {
    task: updatedTask,
    artifactCount: storedArtifacts.length,
  });

  return {
    task: updatedTask,
    storedArtifacts,
  };
}

export async function appendTaskArtifacts(
  app: FastifyInstance,
  auth: RuntimeAuthTokenPayload,
  taskId: string,
  items: ArtifactInput[],
) {
  const task = await getTaskForRuntime(app, taskId, auth);
  const storedArtifacts = await persistArtifacts(app, task.id, items);

  await insertTaskEvent(app, {
    taskId: task.id,
    status: task.status,
    message: "Artifacts appended",
    payload: {
      artifactCount: storedArtifacts.length,
    },
  });

  publishTaskEvent(app, task, "task.artifacts", {
    taskId: task.id,
    artifacts: storedArtifacts,
  });

  return {
    taskId: task.id,
    artifacts: storedArtifacts,
  };
}
