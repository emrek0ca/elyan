import type { FastifyPluginAsync } from "fastify";
import { getUserAuth } from "../../lib/request-auth.js";
import {
  advanceGoalBodySchema,
  createGoalBodySchema,
  goalParamsSchema,
  listGoalsQuerySchema,
  updateGoalBodySchema,
} from "./schemas.js";
import { advanceGoal, createGoal, listGoals, updateGoal } from "./service.js";

export const goalRoutes: FastifyPluginAsync = async (app) => {
  app.get("/", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;

    const auth = getUserAuth(request);
    const query = listGoalsQuerySchema.parse(request.query ?? {});
    return listGoals(app, {
      userId: auth.sub,
      status: query.status,
      sessionId: query.sessionId,
      limit: query.limit,
    });
  });

  app.post("/", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;

    const auth = getUserAuth(request);
    const body = createGoalBodySchema.parse(request.body);
    return createGoal(app, {
      userId: auth.sub,
      sessionId: body.sessionId,
      taskId: body.taskId,
      title: body.title,
      description: body.description,
      maxSteps: body.maxSteps,
      scheduleHint: body.scheduleHint,
      dueAt: body.dueAt ? new Date(body.dueAt) : null,
    });
  });

  app.patch("/:goalId", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;

    const auth = getUserAuth(request);
    const params = goalParamsSchema.parse(request.params);
    const body = updateGoalBodySchema.parse(request.body);
    return updateGoal(app, {
      userId: auth.sub,
      goalId: params.goalId,
      status: body.status,
      title: body.title,
      description: body.description,
      scheduleHint: body.scheduleHint,
      dueAt: typeof body.dueAt === "string" ? new Date(body.dueAt) : body.dueAt,
    });
  });

  app.post("/:goalId/advance", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;

    const auth = getUserAuth(request);
    const params = goalParamsSchema.parse(request.params);
    const body = advanceGoalBodySchema.parse(request.body);
    return advanceGoal(app, {
      userId: auth.sub,
      goalId: params.goalId,
      step: body.step,
      ofSteps: body.ofSteps,
      advancedTo: body.advancedTo,
      blocker: body.blocker,
      done: body.done,
    });
  });
};
