import type { FastifyPluginAsync } from "fastify";

export const aiRoutes: FastifyPluginAsync = async (app) => {
  app.get("/providers", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    return {
      providers: [
        {
          code: "openai",
          role: "intent_understanding",
        },
        {
          code: "claude",
          role: "planning",
        },
        {
          code: "ollama",
          role: "local_assist",
        },
        {
          code: "groq",
          role: "fast_routing",
        },
      ],
      note: "AI may assist planning and tool selection. Desktop runtime performs real execution.",
    };
  });
};
