import { z } from 'zod';

const envSchema = z.object({
  SEARXNG_URL: z.string().url().default('http://localhost:8080'),
  OLLAMA_URL: z.string().url().default('http://127.0.0.1:11434'),
  OPENAI_API_KEY: z.string().optional(),
  ANTHROPIC_API_KEY: z.string().optional(),
  GROQ_API_KEY: z.string().optional(),
  ELYAN_MCP_SERVERS: z.string().optional(),
  ELYAN_DISABLED_MCP_SERVERS: z.string().optional(),
  ELYAN_DISABLED_MCP_TOOLS: z.string().optional(),
  ELYAN_ALLOWED_ORIGINS: z.string().optional(),
  DATABASE_URL: z.string().optional(),
  PORT: z.string().optional(),
  NEXTAUTH_URL: z.string().url().optional(),
  NEXTAUTH_SECRET: z.string().optional(),
  ELYAN_CONTROL_PLANE_STATE_PATH: z
    .string()
    .default('storage/control-plane/state.json'),
  ELYAN_RUNTIME_SETTINGS_PATH: z
    .string()
    .default('storage/runtime/settings.json'),
  ELYAN_STORAGE_DIR: z.string().default('storage'),
  TELEGRAM_BOT_TOKEN: z.string().optional(),
  TELEGRAM_WEBHOOK_SECRET: z.string().optional(),
  WHATSAPP_CLOUD_ACCESS_TOKEN: z.string().optional(),
  WHATSAPP_CLOUD_PHONE_NUMBER_ID: z.string().optional(),
  WHATSAPP_CLOUD_VERIFY_TOKEN: z.string().optional(),
  WHATSAPP_CLOUD_APP_SECRET: z.string().optional(),
  WHATSAPP_CLOUD_API_VERSION: z.string().optional(),
  BLUEBUBBLES_SERVER_URL: z.string().url().optional(),
  BLUEBUBBLES_SERVER_GUID: z.string().optional(),
  BLUEBUBBLES_REPLY_URL: z.string().url().optional(),
  BLUEBUBBLES_WEBHOOK_SECRET: z.string().optional(),
  PICOVOICE_ACCESS_KEY: z.string().optional(),
  GITHUB_OWNER: z.string().optional(),
  GITHUB_REPO: z.string().optional(),
  GITHUB_TOKEN: z.string().optional(),
  GOOGLE_CLIENT_ID: z.string().optional(),
  GOOGLE_CLIENT_SECRET: z.string().optional(),
  GITHUB_CLIENT_ID: z.string().optional(),
  GITHUB_CLIENT_SECRET: z.string().optional(),
  NOTION_CLIENT_ID: z.string().optional(),
  NOTION_CLIENT_SECRET: z.string().optional(),
  IYZICO_ENV: z.enum(['sandbox', 'production']).default('sandbox'),
  IYZICO_API_KEY: z.string().optional(),
  IYZICO_SECRET_KEY: z.string().optional(),
  IYZICO_MERCHANT_ID: z.string().optional(),
  IYZICO_SANDBOX_API_KEY: z.string().optional(),
  IYZICO_SANDBOX_SECRET_KEY: z.string().optional(),
  IYZICO_SANDBOX_MERCHANT_ID: z.string().optional(),
  IYZICO_SANDBOX_API_BASE_URL: z.string().url().default('https://sandbox-api.iyzipay.com'),
  IYZICO_BASE_URL: z.string().url().default('https://api.iyzipay.com'),
});

export type ElyanEnv = z.infer<typeof envSchema>;
export type EnvInspectionResult =
  | { ok: true; data: ElyanEnv }
  | { ok: false; issues: Record<string, string[] | undefined> };

export function inspectEnv(source: NodeJS.ProcessEnv = process.env): EnvInspectionResult {
  const parsed = envSchema.safeParse(source);

  if (!parsed.success) {
    return {
      ok: false,
      issues: parsed.error.flatten().fieldErrors,
    };
  }

  return {
    ok: true,
    data: parsed.data,
  };
}

/**
 * Validates the current process.env against the strict schema.
 * Throws an explicit, readable error at server startup or route execution
 * if environment validation fails, satisfying V1 hardening requirements.
 */
function validateEnv() {
  const inspected = inspectEnv();

  if (!inspected.ok) {
    console.error('❌ Invalid environment variables:', inspected.issues);
    throw new Error('Elyan Boot Failure: Invalid environment matching requirements.');
  }

  return inspected.data;
}

export const env = validateEnv();
