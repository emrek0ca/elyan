import { and, eq, inArray } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import type { TaskStatus } from "../../contracts/domain.js";
import { tasks } from "../../db/schema.js";

export const activeTaskStatuses: TaskStatus[] = ["queued", "planning", "running", "waiting_approval"];

export async function resequenceDeviceQueue(app: FastifyInstance, targetDeviceId: string): Promise<void> {
  const activeRows = await app.db
    .select({
      id: tasks.id,
    })
    .from(tasks)
    .where(and(eq(tasks.targetDeviceId, targetDeviceId), inArray(tasks.status, activeTaskStatuses)))
    .orderBy(tasks.createdAt);

  for (const [index, row] of activeRows.entries()) {
    await app.db
      .update(tasks)
      .set({
        queuePosition: index + 1,
        updatedAt: new Date(),
      })
      .where(eq(tasks.id, row.id));
  }
}
