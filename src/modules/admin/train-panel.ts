import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { FastifyPluginAsync, FastifyReply, FastifyRequest } from "fastify";

const panelRoot = join(process.cwd(), "train-panel");
const assetCache = new Map<string, string>();

async function readPanelAsset(name: string): Promise<string> {
  const cached = assetCache.get(name);
  if (cached) {
    return cached;
  }

  const content = await readFile(join(panelRoot, name), "utf8");
  assetCache.set(name, content);
  return content;
}

function sendText(reply: FastifyReply, contentType: string, body: string) {
  reply.header("cache-control", "no-store, max-age=0");
  return reply.type(contentType).send(body);
}

export const trainPanelRoutes: FastifyPluginAsync = async (app) => {
  const serveIndex = async (_request: FastifyRequest, reply: FastifyReply) => {
    const html = await readPanelAsset("index.html");
    return sendText(reply, "text/html; charset=utf-8", html);
  };

  app.get("/train", serveIndex);
  app.get("/train/", serveIndex);

  app.get("/train/app.js", async (_request, reply) => {
    const appJs = await readPanelAsset("app.js");
    return sendText(reply, "application/javascript; charset=utf-8", appJs);
  });

  app.get("/train/styles.css", async (_request, reply) => {
    const css = await readPanelAsset("styles.css");
    return sendText(reply, "text/css; charset=utf-8", css);
  });
};
