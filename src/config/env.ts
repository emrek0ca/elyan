import { z } from "zod";

export type SharedBrainProvider =
  | "ollama"
  | "vllm"
  | "llamacpp"
  | "groq"
  | "gemini"
  | "openai"
  | "claude"
  | "openrouter";

const booleanFlag = (defaultValue: boolean) =>
  z
    .preprocess((value) => {
      if (typeof value === "boolean") {
        return value;
      }

      if (typeof value === "string") {
        const normalized = value.trim().toLowerCase();

        if (["true", "1", "yes", "on"].includes(normalized)) {
          return true;
        }

        if (["false", "0", "no", "off"].includes(normalized)) {
          return false;
        }
      }

      return value;
    }, z.boolean())
    .default(defaultValue);

const optionalBlankableUrl = () =>
  z.preprocess((value) => {
    if (typeof value === "string" && value.trim() === "") {
      return undefined;
    }

    return value;
  }, z.string().url().optional());

const envSchema = z.object({
  NODE_ENV: z
    .enum(["development", "test", "production"])
    .default("development"),
  HOST: z.string().default("0.0.0.0"),
  PORT: z.coerce.number().int().positive().default(4000),
  LOG_LEVEL: z
    .enum(["fatal", "error", "warn", "info", "debug", "trace", "silent"])
    .default("info"),
  APP_BASE_URL: z.string().url(),
  DATABASE_URL: z.string().min(1),
  JWT_SECRET: z.string().min(32),
  ACCESS_TOKEN_TTL: z.string().default("15m"),
  REFRESH_TOKEN_TTL: z.string().default("30d"),
  RUNTIME_TOKEN_TTL: z.string().default("12h"),
  PAIRING_TTL_MINUTES: z.coerce.number().int().positive().default(10),
  RUNTIME_SECRET_PEPPER: z.string().min(16),
  CORS_ORIGIN: z.string().default("*"),
  REDIS_URL: z.string().url().optional(),
  RELIABILITY_REDIS_REQUIRED: booleanFlag(false),
  BLOB_STORAGE_BUCKET: z.string().optional(),
  BLOB_STORAGE_REGION: z.string().optional(),
  BLOB_STORAGE_ENDPOINT: z.string().url().optional(),
  BLOB_STORAGE_ACCESS_KEY_ID: z.string().optional(),
  BLOB_STORAGE_SECRET_ACCESS_KEY: z.string().optional(),
  BLOB_STORAGE_FORCE_PATH_STYLE: booleanFlag(false),
  BLOB_STORAGE_SIGNED_URL_TTL_SECONDS: z.coerce
    .number()
    .int()
    .positive()
    .default(600),
  BLOB_HMAC_SECRET: z.string().optional(),
  RATE_LIMIT_REDIS_ENABLED: booleanFlag(false),
  REALTIME_REDIS_FANOUT_ENABLED: booleanFlag(true),
  REALTIME_REDIS_CHANNEL_PREFIX: z
    .string()
    .trim()
    .min(1)
    .default("elyan:realtime"),
  REALTIME_EVENT_RETENTION_HOURS: z.coerce
    .number()
    .int()
    .positive()
    .default(48),
  // Kaç ters vekil katmanına güvenileceği. `trustProxy: true` İNTERNETTEN
  // gelen `X-Forwarded-For` başlığını olduğu gibi kabul eder; hız sınırı
  // IP'ye bakarken bu, başlığı uydurarak sınırı tamamen atlatmak demektir.
  // Varsayılan 1 = yalnız kutunun üstündeki nginx/caddy.
  TRUST_PROXY_HOPS: z.coerce.number().int().min(0).max(4).default(1),
  // Pahalı rotalar (LLM çıkarımı, konuşma, görsel üretimi) için ayrı ve çok
  // daha sıkı dakikalık tavan. Global 600/dk bu rotalarda hem sağlayıcı
  // bütçesini hem sunucuyu tek kullanıcıyla tüketmeye yetiyordu.
  // 60/dk = sürekli 1 istek/sn. Hiçbir insan kullanımı buna yaklaşmaz, ama
  // otomatik kötüye kullanımı ve kaçak maliyeti durdurur. Daha düşük bir
  // tavan (20) normal test/geliştirme akışını bile kesiyordu.
  RATE_LIMIT_EXPENSIVE_PER_MINUTE: z.coerce.number().int().positive().default(60),
  RATE_LIMIT_AUTH_PER_MINUTE: z.coerce.number().int().positive().default(30),
  // Olay döngüsü gecikmesi bu eşiği aşarsa yeni istekler 503 + Retry-After
  // ile geri çevrilir. Yük altında yavaşça çökmek yerine hızlıca reddetmek,
  // sunucunun ayakta kalmasının tek yolu.
  LOAD_SHED_EVENT_LOOP_LAG_MS: z.coerce.number().int().positive().default(900),
  LOAD_SHED_HEAP_USED_RATIO: z.coerce.number().min(0.5).max(0.99).default(0.92),
  LOAD_SHED_ENABLED: booleanFlag(true),
  SSE_MAX_STREAMS_PER_USER: z.coerce.number().int().positive().default(4),
  SSE_REPLAY_LIMIT: z.coerce.number().int().positive().max(2_000).default(500),
  SSE_HEARTBEAT_MS: z.coerce.number().int().positive().default(15_000),
  /* Yavaş SSE client backpressure sınırı: soket yazma buffer'ı bu bayt
   * sınırını aşarsa bağlantı kapatılır (client Last-Event-ID ile replay'den
   * kaldığı yerden devam eder). Sınırsız buffer = bellek sızıntısı. */
  SSE_MAX_BUFFERED_BYTES: z.coerce.number().int().positive().default(1_048_576),
  /* PostgreSQL bağlantı havuzu ve zaman aşımı sınırları. */
  DB_POOL_MAX: z.coerce.number().int().positive().max(200).default(20),
  DB_CONNECT_TIMEOUT_SECONDS: z.coerce.number().int().positive().default(10),
  DB_IDLE_TIMEOUT_SECONDS: z.coerce.number().int().positive().default(30),
  BRAIN_CIRCUIT_FAILURE_THRESHOLD: z.coerce
    .number()
    .int()
    .positive()
    .default(3),
  BRAIN_CIRCUIT_OPEN_MS: z.coerce.number().int().positive().default(30_000),
  TASK_DISPATCH_LOCK_TTL_MS: z.coerce
    .number()
    .int()
    .positive()
    .default(120_000),
  ELYAN_TASK_DISPATCH_WORKER_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(32)
    .default(4),
  ELYAN_DESKTOP_TASK_DEVICE_BACKLOG_MAX: z.coerce
    .number()
    .int()
    .positive()
    .max(100)
    .default(8),
  ELYAN_ROUTE_MODEL_GLOBAL_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(256)
    .default(32),
  ELYAN_ROUTE_MODEL_USER_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(4)
    .default(1),
  ELYAN_PLAN_REVISION_GLOBAL_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(64)
    .default(6),
  ELYAN_PLAN_REVISION_USER_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(4)
    .default(1),
  ELYAN_CHAT_QUEUE_ENABLED: booleanFlag(false),
  ELYAN_CHAT_WORKER_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(32)
    .default(4),
  ELYAN_CHAT_PRIMARY_GLOBAL_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(64)
    .default(6),
  ELYAN_CHAT_FALLBACK_GLOBAL_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(64)
    .default(4),
  ELYAN_CHAT_GLOBAL_BACKLOG_MAX: z.coerce
    .number()
    .int()
    .positive()
    .max(200_000)
    .default(1_000),
  ELYAN_CHAT_USER_BACKLOG_MAX: z.coerce
    .number()
    .int()
    .positive()
    .max(100)
    .default(3),
  ELYAN_GROQ_RPM_LIMIT: z.coerce
    .number()
    .int()
    .positive()
    .max(100_000)
    .default(30),
  ELYAN_GROQ_TPM_LIMIT: z.coerce
    .number()
    .int()
    .positive()
    .max(100_000_000)
    .default(8_000),
  ELYAN_GEMINI_RPM_LIMIT: z.coerce
    .number()
    .int()
    .positive()
    .max(100_000)
    .default(10),
  REQUEST_BUDGET_WINDOW_MS: z.coerce.number().int().positive().default(60_000),
  AUTH_REQUEST_BUDGET_MAX: z.coerce.number().int().positive().default(10),
  CHAT_REQUEST_BUDGET_MAX: z.coerce.number().int().positive().default(60),
  TASK_REQUEST_BUDGET_MAX: z.coerce.number().int().positive().default(60),
  GOOGLE_CLIENT_ID: z.string().optional(),
  GOOGLE_CLIENT_SECRET: z.string().optional(),
  GMAIL_MCP_CLIENT_ID: z.string().optional(),
  GMAIL_MCP_CLIENT_SECRET: z.string().optional(),
  GOOGLE_DRIVE_MCP_CLIENT_ID: z.string().optional(),
  GOOGLE_DRIVE_MCP_CLIENT_SECRET: z.string().optional(),
  GOOGLE_CALENDAR_MCP_CLIENT_ID: z.string().optional(),
  GOOGLE_CALENDAR_MCP_CLIENT_SECRET: z.string().optional(),
  GOOGLE_SERVER_CLIENT_ID: z.string().optional(),
  GOOGLE_REVERSED_CLIENT_ID: z.string().optional(),
  NOTION_CLIENT_ID: z.string().optional(),
  NOTION_CLIENT_SECRET: z.string().optional(),
  SLACK_CLIENT_ID: z.string().optional(),
  SLACK_CLIENT_SECRET: z.string().optional(),
  DISCORD_CLIENT_ID: z.string().optional(),
  DISCORD_CLIENT_SECRET: z.string().optional(),
  GITHUB_CLIENT_ID: z.string().optional(),
  GITHUB_CLIENT_SECRET: z.string().optional(),
  LINEAR_CLIENT_ID: z.string().optional(),
  LINEAR_CLIENT_SECRET: z.string().optional(),
  DROPBOX_CLIENT_ID: z.string().optional(),
  DROPBOX_CLIENT_SECRET: z.string().optional(),
  TRELLO_CLIENT_ID: z.string().optional(),
  TRELLO_CLIENT_SECRET: z.string().optional(),
  JIRA_CLIENT_ID: z.string().optional(),
  JIRA_CLIENT_SECRET: z.string().optional(),
  CLICKUP_CLIENT_ID: z.string().optional(),
  CLICKUP_CLIENT_SECRET: z.string().optional(),
  APPLE_CLIENT_ID: z.string().optional(),
  APPLE_SERVICE_ID: z.string().optional(),
  APPLE_TEAM_ID: z.string().optional(),
  APPLE_IAP_SHARED_SECRET: z.string().optional(),
  APPLE_APP_STORE_ISSUER_ID: z.string().optional(),
  APPLE_APP_STORE_KEY_ID: z.string().optional(),
  APPLE_APP_STORE_PRIVATE_KEY: z.string().optional(),
  APPLE_APP_STORE_PRIVATE_KEY_PATH: z.string().optional(),
  APPLE_APP_BUNDLE_ID: z.string().optional(),
  APPLE_APP_ID: z.coerce.number().int().positive().optional(),
  APPLE_SOLO_PRODUCT_ID: z
    .string()
    .default("com.elyan.elyanMobile.solo.monthly"),
  APPLE_PRO_PRODUCT_ID: z.string().default("com.elyan.elyanMobile.pro.monthly"),
  APNS_KEY_ID: z.string().optional(),
  APNS_PRIVATE_KEY: z.string().optional(),
  APNS_PRIVATE_KEY_PATH: z.string().optional(),
  APNS_ENVIRONMENT: z.enum(["sandbox", "production"]).default("sandbox"),
  ANDROID_APP_LINK_PACKAGE_NAME: z.string().optional(),
  ANDROID_SHA256_CERT_FINGERPRINTS: z.string().optional(),
  GOOGLE_PLAY_PACKAGE_NAME: z.string().optional(),
  GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL: z.string().optional(),
  GOOGLE_PLAY_PRIVATE_KEY: z.string().optional(),
  OPENAI_API_KEY: z.string().optional(),
  OPENAI_BASE_URL: z.string().url().optional(),
  OPENAI_FRONTIER_MODEL: z.string().default("gpt-5.6-terra"),
  OPENAI_TRANSCRIBE_MODEL: z.string().default("gpt-4o-transcribe"),
  OPENAI_TTS_MODEL: z.string().default("gpt-4o-mini-tts"),
  ANTHROPIC_API_KEY: z.string().optional(),
  ANTHROPIC_BASE_URL: z.string().url().optional(),
  GROQ_API_KEY: z.string().optional(),
  GROQ_BASE_URL: z.string().url().default("https://api.groq.com/openai/v1"),
  GROQ_TRANSCRIBE_MODEL: z.string().default("whisper-large-v3-turbo"),
  GROQ_REASONING_MODEL: z.string().default("openai/gpt-oss-120b"),
  GROQ_FAST_MODEL: z.string().default("openai/gpt-oss-20b"),
  GROQ_FALLBACK_MODEL: z.string().default("qwen/qwen3.6-27b"),
  // Yönlendirme/niyet iş yükleri: KATI JSON üretmeli, bu yüzden bilinçli
  // olarak reasoning-DIŞI bir model (gizli düşünme turu JSON'u boş bırakıyor).
  GROQ_ROUTING_MODEL: z.string().default("llama-3.1-8b-instant"),
  GROQ_VISION_MODEL: z
    .string()
    .default("qwen/qwen3.6-27b"),
  GROQ_VISION_SENSITIVE_DATA_ATTESTED: booleanFlag(false),
  // Groq Compound: yerleşik ajan sistemi (web arama + kod yürütme). OpenAI
  // uyumlu /chat/completions üzerinden `groq/compound` (derin) ve
  // `groq/compound-mini` (hızlı) modelleriyle çalışır. Varsayılan AÇIK:
  // yalnız public planning/deep-refine iş yüklerinde birincil model olur,
  // hemen ardından mevcut gpt-oss zinciri fallback kalır (kalite gerilemez).
  GROQ_COMPOUND_ENABLED: booleanFlag(true),
  GROQ_COMPOUND_RESEARCH_ENABLED: booleanFlag(true),
  GROQ_COMPOUND_DEEP_ENABLED: booleanFlag(true),
  GROQ_COMPOUND_MODEL: z.string().default("groq/compound"),
  GROQ_COMPOUND_MINI_MODEL: z.string().default("groq/compound-mini"),
  // Arama davranışı ince ayarı (opsiyonel). Virgülle ayrılmış alan adı
  // listeleri ve ülke ipucu isteğin KÖKÜNDEKİ `search_settings`'e taşınır.
  //
  // ÜLKE ISO KODU DEĞİL, ADIDIR: compound'un arama katmanı (Tavily) `tr`
  // değerini reddediyor, `turkey` bekliyor. Yanlış değer her compound
  // çağrısını 400 ile düşürür.
  GROQ_COMPOUND_SEARCH_COUNTRY: z.string().optional(),
  GROQ_COMPOUND_INCLUDE_DOMAINS: z.string().optional(),
  GROQ_COMPOUND_EXCLUDE_DOMAINS: z.string().optional(),
  GEMINI_API_KEY: z.string().optional(),
  GEMINI_BASE_URL: z
    .string()
    .url()
    .default("https://generativelanguage.googleapis.com/v1beta/openai"),
  GEMINI_INTERACTIONS_BASE_URL: z
    .string()
    .url()
    .default("https://generativelanguage.googleapis.com/v1beta"),
  GEMINI_TEXT_MODEL: z.string().default("gemini-3.6-flash"),
  GEMINI_FAST_MODEL: z.string().default("gemini-3.5-flash-lite"),
  GEMINI_REASONING_MODEL: z.string().default("gemini-3.6-flash"),
  GEMINI_VISION_MODEL: z.string().default("gemini-3.6-flash"),
  GEMINI_VISION_SENSITIVE_DATA_ATTESTED: booleanFlag(false),
  GEMINI_IMAGE_MODEL: z.string().default("gemini-3.1-flash-image"),
  GEMINI_IMAGE_PRO_MODEL: z.string().default("gemini-3-pro-image"),
  GEMINI_IMAGE_SIZE: z.enum(["1K", "2K", "4K"]).default("1K"),
  GEMINI_IMAGE_PRO_ENABLED: booleanFlag(false),
  GEMINI_IMAGE_DAILY_GLOBAL_LIMIT: z.coerce
    .number()
    .int()
    .positive()
    .max(10_000)
    .default(50),
  GEMINI_IMAGE_PRO_DAILY_GLOBAL_LIMIT: z.coerce
    .number()
    .int()
    .positive()
    .max(1_000)
    .default(5),
  GEMINI_IMAGE_4K_DAILY_GLOBAL_LIMIT: z.coerce
    .number()
    .int()
    .positive()
    .max(1_000)
    .default(2),
  ELYAN_GEMINI_FREE_FEATURES_ENABLED: booleanFlag(true),
  GEMINI_FREE_ONLY: booleanFlag(true),
  GEMINI_FREE_DATA_USAGE_ATTESTED: booleanFlag(false),
  GEMINI_PAID_FALLBACK_ENABLED: booleanFlag(false),
  GEMINI_PAID_DATA_PROCESSING_ATTESTED: booleanFlag(false),
  GEMINI_FREE_MODEL_ALLOWLIST: z
    .string()
    .default("gemini-3.5-flash-lite,gemini-3.1-flash-lite"),
  GEMINI_FREE_DAILY_REQUEST_LIMIT: z.coerce
    .number()
    .int()
    .positive()
    .max(10_000)
    .default(200),
  GEMINI_FREE_DAILY_INPUT_TOKEN_LIMIT: z.coerce
    .number()
    .int()
    .positive()
    .max(10_000_000)
    .default(250_000),
  GEMINI_FREE_DAILY_OUTPUT_TOKEN_LIMIT: z.coerce
    .number()
    .int()
    .positive()
    .max(2_000_000)
    .default(50_000),
  GEMINI_FREE_USER_DAILY_REQUEST_LIMIT: z.coerce
    .number()
    .int()
    .positive()
    .max(1_000)
    .default(25),
  GEMINI_FREE_UTILITY_SAMPLE_PERCENT: z.coerce
    .number()
    .int()
    .min(0)
    .max(100)
    .default(10),
  OPENROUTER_API_KEY: z.string().optional(),
  OPENROUTER_BASE_URL: z.string().url().optional(),
  IYZICO_API_KEY: z.string().optional(),
  IYZICO_SECRET_KEY: z.string().optional(),
  IYZICO_MERCHANT_ID: z.string().optional(),
  TOKEN_ENCRYPTION_KEY: z.string().optional(),
  IYZICO_BASE_URL: z.string().url().default("https://api.iyzipay.com"),
  IYZICO_PUBLIC_BASE_URL: z.string().url().optional(),
  IYZICO_LOCALE: z.enum(["tr", "en"]).default("tr"),
  IYZICO_PRODUCT_NAME: z.string().default("Elyan Subscriptions"),
  ELYAN_SHARED_BRAIN_PROVIDER: z
    .enum([
      "ollama",
      "vllm",
      "llamacpp",
      "groq",
      "gemini",
      "openai",
      "claude",
      "openrouter",
    ])
    .default("ollama"),
  ELYAN_SHARED_BRAIN_BASE_URL: z
    .string()
    .url()
    .default("http://127.0.0.1:11434"),
  ELYAN_SHARED_BRAIN_FALLBACK_PROVIDER: z.preprocess(
    (value) => {
      if (typeof value === "string" && value.trim() === "") {
        return undefined;
      }

      return value;
    },
    z
      .enum([
        "ollama",
        "vllm",
        "llamacpp",
        "groq",
        "gemini",
        "openai",
        "claude",
        "openrouter",
      ])
      .optional(),
  ),
  ELYAN_SHARED_BRAIN_FALLBACK_BASE_URL: optionalBlankableUrl(),
  ELYAN_SHARED_BRAIN_MODEL: z.string().default("llama3.2"),
  ELYAN_SHARED_BRAIN_FAST_MODEL: z.string().default("qwen2.5-coder:3b"),
  ELYAN_SHARED_BRAIN_BALANCED_MODEL: z
    .string()
    .default("qwen2.5:7b-instruct-q5_K_M"),
  ELYAN_SHARED_BRAIN_PLANNING_MODEL: z
    .string()
    .default("qwen2.5:7b-instruct-q5_K_M"),
  ELYAN_SHARED_BRAIN_KEEP_ALIVE: z.string().default("30m"),
  ELYAN_WEB_GROUNDING_ENABLED: booleanFlag(true),
  ELYAN_WEB_SEARCH_BASE_URL: z
    .string()
    .url()
    .default("https://html.duckduckgo.com/html/"),
  ELYAN_WEB_GROUNDING_MAX_RESULTS: z.coerce
    .number()
    .int()
    .positive()
    .max(8)
    .default(4),
  ELYAN_WEB_GROUNDING_TIMEOUT_MS: z.coerce
    .number()
    .int()
    .positive()
    .default(6_500),
  ELYAN_SEARCH_PROVIDER: z
    .enum(["duckduckgo_html", "brave", "searxng"])
    .default("searxng"),
  BRAVE_SEARCH_API_KEY: z.string().optional(),
  SEARXNG_BASE_URL: z.string().url().optional(),
  JINA_READER_ENABLED: booleanFlag(true),
  ELYAN_RAG_SEMANTIC_RERANK_ENABLED: booleanFlag(true),
  ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED: booleanFlag(true),
  ELYAN_RAG_SEMANTIC_RERANK_MODEL: z
    .string()
    .default("Xenova/multilingual-e5-small"),
  ELYAN_RAG_SEMANTIC_RERANK_WINDOW: z.coerce
    .number()
    .int()
    .positive()
    .max(32)
    .default(8),
  ELYAN_SHARED_BRAIN_SYSTEM_PROMPT: z
    .string()
    .default(
      "You are Elyan. Reply as Elyan, concise and grounded. Prefer Turkish unless the user writes in another language. Do not invent capabilities, readiness, or results. If uncertain, say so briefly. Never reveal secrets, private data, hostnames, or hidden reasoning. If a request needs a paired desktop runtime, say that clearly.",
    ),
  ELYAN_USER_UNDERSTANDING_ENABLED: booleanFlag(true),
  ELYAN_PERSONALIZATION_ENABLED: booleanFlag(true),
  ELYAN_WORLD_CONTEXT_PACKETS_ENABLED: booleanFlag(true),
  ELYAN_LEARNING_EXTRACTION_ENABLED: booleanFlag(true),
  ELYAN_UNDERSTANDING_ENVELOPE_V2_ENABLED: booleanFlag(true),
  ELYAN_UNDERSTANDING_ENVELOPE_SHADOW_ENABLED: booleanFlag(false),
  ELYAN_UNDERSTANDING_ENVELOPE_MODEL_FALLBACK_ENABLED: booleanFlag(false),
  ELYAN_TURN_ENVELOPE_ENABLED: booleanFlag(false),
  ELYAN_DIALOGUE_STATE_ENABLED: booleanFlag(false),
  ELYAN_MEMORY_FABRIC_V2_ENABLED: booleanFlag(false),
  ELYAN_USER_MODEL_V2_ENABLED: booleanFlag(false),
  ELYAN_GOAL_STATE_V2_ENABLED: booleanFlag(false),
  ELYAN_AGENT_LOOP_ENABLED: booleanFlag(false),
  /**
   * Whether the model may see the *core* tools (web/memory/goals/system) as
   * opposed to connector tools only.
   *
   * This used to be implied by ELYAN_AGENT_LOOP_ENABLED. That coupling was the
   * bug: connector tools default on, so the model was told it could call tools
   * while its catalogue held nothing but Gmail/Calendar/Drive — no web search,
   * no memory, no goals. Multi-step research and planning were impossible by
   * construction, not by model quality.
   *
   * Kept separate so tool visibility can be turned on without also switching on
   * the multi-turn loop; otherwise one flag changes three behaviours at once and
   * a regression cannot be attributed.
   */
  ELYAN_CORE_TOOLS_ENABLED: booleanFlag(true),
  /** Semantic tool/connector routing from the shared understanding worker. */
  ELYAN_SEMANTIC_TOOL_SELECTION_ENABLED: booleanFlag(true),
  // Enables server-side connector tools (Gmail/Calendar/Drive read) through the
  // agent loop, restricted to connector tool_requests only. Independent of the
  // full agent loop so connectors can ship without turning on write/goal tools.
  ELYAN_CONNECTOR_TOOLS_ENABLED: booleanFlag(true),
  // Official MCP SDK transport plus RFC 9728/RFC 7591 OAuth discovery. The
  // runtime is optional per connection and fails closed when a server is absent.
  ELYAN_MCP_SDK_ENABLED: booleanFlag(true),
  // Uzak MCP sunucularının canlı araç kataloğunu paylaşılan beyne ilan eder ve
  // çağrıları sunucu tarafında çalıştırır. Okuma araçları doğrudan; yazma ve
  // belirsiz yan etkiler mevcut onay politikasıyla korunur.
  ELYAN_MCP_DYNAMIC_TOOLS_ENABLED: booleanFlag(true),
  // Emits source-typed connector block envelopes. Set false to suppress the
  // block surface while retaining safe prose connector replies and tool access.
  ELYAN_SOURCE_TYPED_CONNECTOR_BLOCKS_ENABLED: booleanFlag(true),
  // Emits a user-visible `tool_call` telemetry block (which tool ran, how long,
  // what it found) alongside connector data blocks. Set false to hide it.
  ELYAN_TOOL_CALL_BLOCK_ENABLED: booleanFlag(true),
  // YEREL ARAÇ ÇAĞRISI DÖNGÜSÜ (model → tool_call → sonuç → model).
  // Varsayılan KAPALI: ana sohbet yolu bugün çalışıyor ve döngü ikinci bir
  // sağlayıcı gidiş-dönüşü açıyor. Canlı doğrulamadan sonra açılır.
  ELYAN_SERVER_TOOL_LOOP_ENABLED: booleanFlag(false),
  // Hard-blocks every reply until the user grants AI-data-sharing consent.
  // OFF by default: the in-app consent flow is not wired yet, so enforcing it
  // walls off all answers. Re-enable once the consent UX ships.
  ELYAN_AI_DATA_SHARING_CONSENT_REQUIRED: booleanFlag(false),
  ELYAN_PROACTIVE_ENGINE_ENABLED: booleanFlag(false),
  // Push delivery. The sender stays inert unless FCM credentials are present,
  // so leaving the flag on in an unconfigured environment is harmless.
  ELYAN_PUSH_ENABLED: booleanFlag(true),
  FCM_PROJECT_ID: z.string().optional(),
  FCM_CLIENT_EMAIL: z.string().optional(),
  FCM_PRIVATE_KEY: z.string().optional(),
  // Night watch: work runs during quiet hours, notifications do not.
  ELYAN_NIGHT_WATCH_ENABLED: booleanFlag(false),
  ELYAN_NIGHT_WATCH_MAX_JOBS_PER_NIGHT: z.coerce
    .number()
    .int()
    .min(0)
    .max(20)
    .default(4),
  ELYAN_MORNING_DIGEST_HOUR: z.coerce.number().int().min(0).max(23).default(8),
  // Autonomous suggestion generation from observed signals.
  ELYAN_PROACTIVE_OBSERVER_ENABLED: booleanFlag(false),
  ELYAN_PROACTIVE_OBSERVER_INTERVAL_MS: z.coerce
    .number()
    .int()
    .positive()
    .default(15 * 60_000),
  ELYAN_CLOUD_VISION_ENABLED: booleanFlag(true),
  ELYAN_COST_GUARD_ENABLED: booleanFlag(true),
  ELYAN_MODEL_CANARY_ENABLED: booleanFlag(false),
  ELYAN_MODEL_PRIMARY_ENABLED: booleanFlag(false),
  ELYAN_WEIGHT_TRAINING_ENABLED: booleanFlag(false),
  ELYAN_BEHAVIOR_LEARNING_ENABLED: booleanFlag(true),
  ELYAN_BLOCKS_V11_ENABLED: booleanFlag(false),
  ELYAN_SCALABLE_STATE_READS_ENABLED: booleanFlag(true),
  ELYAN_COGNITIVE_FOUNDATION_V2_ENABLED: booleanFlag(false),
  ELYAN_COGNITIVE_SHADOW_READ_ENABLED: booleanFlag(false),
  ELYAN_TENANT_RLS_ENFORCEMENT_ENABLED: booleanFlag(false),
  ELYAN_COGNITIVE_FOUNDATION_ROLLOUT_PERCENT: z.coerce
    .number()
    .int()
    .min(0)
    .max(100)
    .default(0),
  ELYAN_AGENT_ENGINE_V2_ENABLED: booleanFlag(false),
  ELYAN_AGENT_ENGINE_SHADOW_ENABLED: booleanFlag(false),
  ELYAN_AGENT_ENGINE_ROLLOUT_PERCENT: z.coerce
    .number()
    .int()
    .min(0)
    .max(100)
    .default(0),
  ELYAN_AGENT_ENGINE_GLOBAL_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(64)
    .default(4),
  ELYAN_AGENT_ENGINE_USER_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(8)
    .default(1),
  ELYAN_AGENT_ENGINE_GLOBAL_BACKPRESSURE_MAX: z.coerce
    .number()
    .int()
    .positive()
    .max(200_000)
    .default(2_000),
  ELYAN_AGENT_ENGINE_USER_BACKPRESSURE_MAX: z.coerce
    .number()
    .int()
    .positive()
    .max(2_000)
    .default(20),
  ELYAN_SPEECH_GLOBAL_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(256)
    .default(24),
  ELYAN_SPEECH_USER_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(4)
    .default(1),
  ELYAN_SPEECH_IP_RPM_LIMIT: z.coerce
    .number()
    .int()
    .positive()
    .max(10_000)
    .default(240),
  // Live voice. Off by default: while this is false the turn-based
  // POST /v1/speech/transcriptions path is the only speech route and behaves
  // exactly as it does today (CANLI-SES-PLANI.md §4, trap 2).
  ELYAN_VOICE_STREAMING_ENABLED: booleanFlag(false),
  // A streaming session has no "file" to size-check, so the meter is audio
  // seconds. Counted per user over a rolling window; the socket is closed the
  // moment the budget is gone rather than being allowed to bill on.
  ELYAN_VOICE_STREAMING_USER_SECONDS_PER_HOUR: z.coerce
    .number()
    .int()
    .positive()
    .max(36_000)
    .default(1_800),
  // One live mic per user. A second socket would double the provider spend for
  // a session the user cannot even see twice.
  ELYAN_VOICE_STREAMING_USER_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(4)
    .default(1),
  ELYAN_VOICE_STREAMING_GLOBAL_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(256)
    .default(16),
  ELYAN_MEDIA_NORMALIZE_GLOBAL_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(128)
    .default(12),
  ELYAN_MEDIA_NORMALIZE_USER_CONCURRENCY: z.coerce
    .number()
    .int()
    .positive()
    .max(8)
    .default(2),
  ELYAN_CONTINUOUS_LEARNING_V2_ENABLED: booleanFlag(false),
  ELYAN_CONTINUOUS_LEARNING_SHADOW_ENABLED: booleanFlag(false),
  ELYAN_CONTINUOUS_LEARNING_DAILY_BATCH_LIMIT: z.coerce
    .number()
    .int()
    .positive()
    .max(20_000)
    .default(2_000),
  ELYAN_CONTINUOUS_LEARNING_REPLAY_RATIO: z.coerce
    .number()
    .int()
    .min(0)
    .max(80)
    .default(20),
  ELYAN_CLAIM_CONFIDENCE_V1_ENABLED: booleanFlag(false),
  ELYAN_CLAIM_CONFIDENCE_SHADOW_ENABLED: booleanFlag(false),
  ELYAN_SELF_CHECK_MODEL_FALLBACK_ENABLED: booleanFlag(false),
  ELYAN_UNDERSTANDING_DEBUG: booleanFlag(false),
});

type ParsedEnv = z.infer<typeof envSchema>;

export type AppEnv = ParsedEnv & {
  IYZICO_PUBLIC_BASE_URL: string;
  GOOGLE_CLIENT_ID: string;
  GOOGLE_SERVER_CLIENT_ID: string;
  GOOGLE_REVERSED_CLIENT_ID: string;
  APPLE_CLIENT_ID: string;
  APPLE_SERVICE_ID: string;
  APPLE_TEAM_ID: string;
  APPLE_IAP_SHARED_SECRET: string;
  APPLE_APP_STORE_ISSUER_ID: string;
  APPLE_APP_STORE_KEY_ID: string;
  APPLE_APP_STORE_PRIVATE_KEY: string;
  APPLE_APP_STORE_PRIVATE_KEY_PATH: string;
  APPLE_APP_BUNDLE_ID: string;
  APPLE_APP_ID: number;
  APPLE_SOLO_PRODUCT_ID: string;
  APPLE_PRO_PRODUCT_ID: string;
  APNS_KEY_ID: string;
  APNS_PRIVATE_KEY: string;
  APNS_PRIVATE_KEY_PATH: string;
  APNS_ENVIRONMENT: "sandbox" | "production";
  ANDROID_APP_LINK_PACKAGE_NAME: string;
  ANDROID_SHA256_CERT_FINGERPRINTS: string;
  GOOGLE_PLAY_PACKAGE_NAME: string;
  GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL: string;
  GOOGLE_PLAY_PRIVATE_KEY: string;
  OPENAI_API_KEY: string;
  OPENAI_BASE_URL: string;
  OPENAI_FRONTIER_MODEL: string;
  OPENAI_TRANSCRIBE_MODEL: string;
  OPENAI_TTS_MODEL: string;
  ANTHROPIC_API_KEY: string;
  ANTHROPIC_BASE_URL: string;
  GROQ_API_KEY: string;
  GROQ_BASE_URL: string;
  GROQ_TRANSCRIBE_MODEL: string;
  GROQ_REASONING_MODEL: string;
  GROQ_FAST_MODEL: string;
  GROQ_FALLBACK_MODEL: string;
  GROQ_ROUTING_MODEL: string;
  GROQ_VISION_MODEL: string;
  GROQ_VISION_SENSITIVE_DATA_ATTESTED?: boolean;
  GROQ_COMPOUND_ENABLED?: boolean;
  GROQ_COMPOUND_RESEARCH_ENABLED?: boolean;
  GROQ_COMPOUND_DEEP_ENABLED?: boolean;
  GROQ_COMPOUND_MODEL: string;
  GROQ_COMPOUND_MINI_MODEL: string;
  GROQ_COMPOUND_SEARCH_COUNTRY?: string;
  GROQ_COMPOUND_INCLUDE_DOMAINS?: string;
  GROQ_COMPOUND_EXCLUDE_DOMAINS?: string;
  GEMINI_API_KEY: string;
  GEMINI_BASE_URL: string;
  GEMINI_INTERACTIONS_BASE_URL: string;
  GEMINI_TEXT_MODEL: string;
  GEMINI_FAST_MODEL: string;
  GEMINI_REASONING_MODEL: string;
  GEMINI_VISION_MODEL: string;
  GEMINI_VISION_SENSITIVE_DATA_ATTESTED?: boolean;
  GEMINI_IMAGE_MODEL: string;
  GEMINI_IMAGE_PRO_MODEL: string;
  GEMINI_IMAGE_SIZE: "1K" | "2K" | "4K";
  GEMINI_IMAGE_PRO_ENABLED: boolean;
  GEMINI_IMAGE_DAILY_GLOBAL_LIMIT: number;
  GEMINI_IMAGE_PRO_DAILY_GLOBAL_LIMIT: number;
  GEMINI_IMAGE_4K_DAILY_GLOBAL_LIMIT: number;
  ELYAN_GEMINI_FREE_FEATURES_ENABLED: boolean;
  GEMINI_FREE_ONLY: boolean;
  GEMINI_FREE_DATA_USAGE_ATTESTED: boolean;
  GEMINI_FREE_MODEL_ALLOWLIST: string;
  GEMINI_FREE_DAILY_REQUEST_LIMIT: number;
  GEMINI_FREE_DAILY_INPUT_TOKEN_LIMIT: number;
  GEMINI_FREE_DAILY_OUTPUT_TOKEN_LIMIT: number;
  GEMINI_FREE_USER_DAILY_REQUEST_LIMIT: number;
  GEMINI_FREE_UTILITY_SAMPLE_PERCENT: number;
  OPENROUTER_API_KEY: string;
  OPENROUTER_BASE_URL: string;
  TOKEN_ENCRYPTION_KEY?: string;
  ELYAN_SHARED_BRAIN_PROVIDER: SharedBrainProvider;
  REDIS_URL?: string;
  RELIABILITY_REDIS_REQUIRED: boolean;
  BLOB_STORAGE_BUCKET: string;
  BLOB_STORAGE_REGION: string;
  BLOB_STORAGE_ENDPOINT: string;
  BLOB_STORAGE_ACCESS_KEY_ID: string;
  BLOB_STORAGE_SECRET_ACCESS_KEY: string;
  BLOB_STORAGE_FORCE_PATH_STYLE: boolean;
  BLOB_STORAGE_SIGNED_URL_TTL_SECONDS: number;
  BLOB_HMAC_SECRET: string;
  RATE_LIMIT_REDIS_ENABLED: boolean;
  TRUST_PROXY_HOPS: number;
  RATE_LIMIT_EXPENSIVE_PER_MINUTE: number;
  RATE_LIMIT_AUTH_PER_MINUTE: number;
  LOAD_SHED_EVENT_LOOP_LAG_MS: number;
  LOAD_SHED_HEAP_USED_RATIO: number;
  LOAD_SHED_ENABLED: boolean;
  REALTIME_REDIS_FANOUT_ENABLED: boolean;
  REALTIME_REDIS_CHANNEL_PREFIX: string;
  REALTIME_EVENT_RETENTION_HOURS: number;
  SSE_MAX_STREAMS_PER_USER: number;
  SSE_REPLAY_LIMIT: number;
  SSE_HEARTBEAT_MS: number;
  SSE_MAX_BUFFERED_BYTES: number;
  DB_POOL_MAX: number;
  DB_CONNECT_TIMEOUT_SECONDS: number;
  DB_IDLE_TIMEOUT_SECONDS: number;
  BRAIN_CIRCUIT_FAILURE_THRESHOLD: number;
  BRAIN_CIRCUIT_OPEN_MS: number;
  TASK_DISPATCH_LOCK_TTL_MS: number;
  REQUEST_BUDGET_WINDOW_MS: number;
  AUTH_REQUEST_BUDGET_MAX: number;
  CHAT_REQUEST_BUDGET_MAX: number;
  TASK_REQUEST_BUDGET_MAX: number;
  ELYAN_SHARED_BRAIN_BASE_URL: string;
  ELYAN_SHARED_BRAIN_FALLBACK_PROVIDER?: SharedBrainProvider;
  ELYAN_SHARED_BRAIN_FALLBACK_BASE_URL?: string;
  ELYAN_SHARED_BRAIN_MODEL: string;
  ELYAN_SHARED_BRAIN_FAST_MODEL: string;
  ELYAN_SHARED_BRAIN_BALANCED_MODEL: string;
  ELYAN_SHARED_BRAIN_PLANNING_MODEL: string;
  ELYAN_SHARED_BRAIN_KEEP_ALIVE: string;
  ELYAN_WEB_GROUNDING_ENABLED: boolean;
  ELYAN_WEB_SEARCH_BASE_URL: string;
  ELYAN_WEB_GROUNDING_MAX_RESULTS: number;
  ELYAN_WEB_GROUNDING_TIMEOUT_MS: number;
  ELYAN_SEARCH_PROVIDER: "duckduckgo_html" | "brave" | "searxng";
  BRAVE_SEARCH_API_KEY?: string;
  SEARXNG_BASE_URL?: string;
  JINA_READER_ENABLED: boolean;
  ELYAN_RAG_SEMANTIC_RERANK_ENABLED: boolean;
  ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED: boolean;
  ELYAN_RAG_SEMANTIC_RERANK_MODEL: string;
  ELYAN_RAG_SEMANTIC_RERANK_WINDOW: number;
  ELYAN_TURN_ENVELOPE_ENABLED: boolean;
  ELYAN_DIALOGUE_STATE_ENABLED: boolean;
  ELYAN_MEMORY_FABRIC_V2_ENABLED: boolean;
  ELYAN_USER_MODEL_V2_ENABLED: boolean;
  ELYAN_GOAL_STATE_V2_ENABLED: boolean;
  ELYAN_AGENT_LOOP_ENABLED: boolean;
  ELYAN_CORE_TOOLS_ENABLED: boolean;
  ELYAN_SEMANTIC_TOOL_SELECTION_ENABLED: boolean;
  ELYAN_CONNECTOR_TOOLS_ENABLED: boolean;
  ELYAN_MCP_SDK_ENABLED: boolean;
  ELYAN_MCP_DYNAMIC_TOOLS_ENABLED: boolean;
  ELYAN_SOURCE_TYPED_CONNECTOR_BLOCKS_ENABLED: boolean;
  ELYAN_TOOL_CALL_BLOCK_ENABLED: boolean;
  ELYAN_SERVER_TOOL_LOOP_ENABLED: boolean;
  ELYAN_AI_DATA_SHARING_CONSENT_REQUIRED: boolean;
  ELYAN_PROACTIVE_ENGINE_ENABLED: boolean;
  ELYAN_PUSH_ENABLED: boolean;
  FCM_PROJECT_ID?: string;
  FCM_CLIENT_EMAIL?: string;
  FCM_PRIVATE_KEY?: string;
  ELYAN_NIGHT_WATCH_ENABLED: boolean;
  ELYAN_NIGHT_WATCH_MAX_JOBS_PER_NIGHT: number;
  ELYAN_MORNING_DIGEST_HOUR: number;
  ELYAN_PROACTIVE_OBSERVER_ENABLED: boolean;
  ELYAN_PROACTIVE_OBSERVER_INTERVAL_MS: number;
  ELYAN_CLOUD_VISION_ENABLED: boolean;
  ELYAN_COST_GUARD_ENABLED: boolean;
  ELYAN_MODEL_CANARY_ENABLED: boolean;
  ELYAN_MODEL_PRIMARY_ENABLED: boolean;
  ELYAN_WEIGHT_TRAINING_ENABLED: boolean;
  ELYAN_BEHAVIOR_LEARNING_ENABLED: boolean;
  ELYAN_BLOCKS_V11_ENABLED: boolean;
  ELYAN_SCALABLE_STATE_READS_ENABLED: boolean;
  ELYAN_COGNITIVE_FOUNDATION_V2_ENABLED: boolean;
  ELYAN_COGNITIVE_SHADOW_READ_ENABLED: boolean;
  ELYAN_TENANT_RLS_ENFORCEMENT_ENABLED: boolean;
  ELYAN_COGNITIVE_FOUNDATION_ROLLOUT_PERCENT: number;
  ELYAN_AGENT_ENGINE_V2_ENABLED: boolean;
  ELYAN_AGENT_ENGINE_SHADOW_ENABLED: boolean;
  ELYAN_AGENT_ENGINE_ROLLOUT_PERCENT: number;
  ELYAN_CONTINUOUS_LEARNING_V2_ENABLED: boolean;
  ELYAN_CONTINUOUS_LEARNING_SHADOW_ENABLED: boolean;
  ELYAN_CONTINUOUS_LEARNING_DAILY_BATCH_LIMIT: number;
  ELYAN_CONTINUOUS_LEARNING_REPLAY_RATIO: number;
  ELYAN_WORLD_CONTEXT_PACKETS_ENABLED: boolean;
  ELYAN_SHARED_BRAIN_SYSTEM_PROMPT: string;
};

function isLocalOnlyHostname(hostname: string): boolean {
  const normalized = hostname.trim().toLowerCase();

  return (
    normalized === "localhost" ||
    normalized === "0.0.0.0" ||
    normalized === "::" ||
    normalized === "::1" ||
    normalized.startsWith("127.")
  );
}

export function getDatabaseReachability(env: Pick<AppEnv, "DATABASE_URL">): {
  connectionUrlScheme: string;
  connectionUrlHost: string;
  connectionUrlPort: number | null;
  localOnlyHost: boolean;
  warning: string | null;
} {
  const url = new URL(env.DATABASE_URL);
  const localOnly = isLocalOnlyHostname(url.hostname);

  return {
    connectionUrlScheme: url.protocol.replace(/:$/, ""),
    connectionUrlHost: url.hostname,
    connectionUrlPort: url.port ? Number(url.port) : null,
    localOnlyHost: localOnly,
    warning: localOnly
      ? "DATABASE_URL points at a local-only host. That is fine for a host-run backend, but a docker-compose backend container must use the postgres service hostname instead."
      : null,
  };
}

export function getBaseUrlReachability(
  env: Pick<AppEnv, "APP_BASE_URL" | "HOST" | "PORT">,
): {
  advertisedBaseUrl: string;
  advertisedHost: string;
  listenHost: string;
  port: number;
  externalClientsCanReachAdvertisedBaseUrl: boolean;
  warning: string | null;
} {
  const advertisedUrl = new URL(env.APP_BASE_URL);
  const advertisedHost = advertisedUrl.hostname;
  const localOnly = isLocalOnlyHostname(advertisedHost);

  return {
    advertisedBaseUrl: env.APP_BASE_URL,
    advertisedHost,
    listenHost: env.HOST,
    port: env.PORT,
    externalClientsCanReachAdvertisedBaseUrl: !localOnly,
    warning: localOnly
      ? "APP_BASE_URL uses a local-only host. Physical mobile devices and other machines cannot reach this backend through localhost or 127.x.x.x."
      : null,
  };
}

export function loadEnv(source: NodeJS.ProcessEnv = process.env): AppEnv {
  const parsed = envSchema.parse(source);
  return {
    ...parsed,
    GOOGLE_CLIENT_ID: parsed.GOOGLE_CLIENT_ID ?? "",
    GOOGLE_SERVER_CLIENT_ID: parsed.GOOGLE_SERVER_CLIENT_ID ?? "",
    GOOGLE_REVERSED_CLIENT_ID: parsed.GOOGLE_REVERSED_CLIENT_ID ?? "",
    APPLE_CLIENT_ID: parsed.APPLE_CLIENT_ID ?? "",
    APPLE_SERVICE_ID: parsed.APPLE_SERVICE_ID ?? "",
    APPLE_TEAM_ID: parsed.APPLE_TEAM_ID ?? "",
    APPLE_IAP_SHARED_SECRET: parsed.APPLE_IAP_SHARED_SECRET ?? "",
    APPLE_APP_STORE_ISSUER_ID: parsed.APPLE_APP_STORE_ISSUER_ID ?? "",
    APPLE_APP_STORE_KEY_ID: parsed.APPLE_APP_STORE_KEY_ID ?? "",
    APPLE_APP_STORE_PRIVATE_KEY: parsed.APPLE_APP_STORE_PRIVATE_KEY ?? "",
    APPLE_APP_STORE_PRIVATE_KEY_PATH:
      parsed.APPLE_APP_STORE_PRIVATE_KEY_PATH ?? "",
    APPLE_APP_BUNDLE_ID: parsed.APPLE_APP_BUNDLE_ID ?? "",
    APPLE_APP_ID: parsed.APPLE_APP_ID ?? 0,
    APPLE_SOLO_PRODUCT_ID: parsed.APPLE_SOLO_PRODUCT_ID,
    APPLE_PRO_PRODUCT_ID: parsed.APPLE_PRO_PRODUCT_ID,
    APNS_KEY_ID: parsed.APNS_KEY_ID ?? "",
    APNS_PRIVATE_KEY: parsed.APNS_PRIVATE_KEY ?? "",
    APNS_PRIVATE_KEY_PATH: parsed.APNS_PRIVATE_KEY_PATH ?? "",
    APNS_ENVIRONMENT: parsed.APNS_ENVIRONMENT,
    ANDROID_APP_LINK_PACKAGE_NAME: parsed.ANDROID_APP_LINK_PACKAGE_NAME ?? "",
    ANDROID_SHA256_CERT_FINGERPRINTS:
      parsed.ANDROID_SHA256_CERT_FINGERPRINTS ?? "",
    GOOGLE_PLAY_PACKAGE_NAME: parsed.GOOGLE_PLAY_PACKAGE_NAME ?? "",
    GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL:
      parsed.GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL ?? "",
    GOOGLE_PLAY_PRIVATE_KEY: parsed.GOOGLE_PLAY_PRIVATE_KEY ?? "",
    BLOB_STORAGE_BUCKET: parsed.BLOB_STORAGE_BUCKET ?? "",
    BLOB_STORAGE_REGION: parsed.BLOB_STORAGE_REGION ?? "",
    BLOB_STORAGE_ENDPOINT: parsed.BLOB_STORAGE_ENDPOINT ?? "",
    BLOB_STORAGE_ACCESS_KEY_ID: parsed.BLOB_STORAGE_ACCESS_KEY_ID ?? "",
    BLOB_STORAGE_SECRET_ACCESS_KEY: parsed.BLOB_STORAGE_SECRET_ACCESS_KEY ?? "",
    BLOB_STORAGE_FORCE_PATH_STYLE: parsed.BLOB_STORAGE_FORCE_PATH_STYLE,
    BLOB_STORAGE_SIGNED_URL_TTL_SECONDS:
      parsed.BLOB_STORAGE_SIGNED_URL_TTL_SECONDS,
    BLOB_HMAC_SECRET: parsed.BLOB_HMAC_SECRET ?? "",
    OPENAI_API_KEY: parsed.OPENAI_API_KEY ?? "",
    OPENAI_BASE_URL: parsed.OPENAI_BASE_URL ?? "https://api.openai.com/v1",
    OPENAI_FRONTIER_MODEL: parsed.OPENAI_FRONTIER_MODEL,
    OPENAI_TRANSCRIBE_MODEL: parsed.OPENAI_TRANSCRIBE_MODEL,
    OPENAI_TTS_MODEL: parsed.OPENAI_TTS_MODEL,
    ANTHROPIC_API_KEY: parsed.ANTHROPIC_API_KEY ?? "",
    ANTHROPIC_BASE_URL:
      parsed.ANTHROPIC_BASE_URL ?? "https://api.anthropic.com/v1",
    GROQ_API_KEY: parsed.GROQ_API_KEY ?? "",
    GROQ_BASE_URL: parsed.GROQ_BASE_URL ?? "https://api.groq.com/openai/v1",
    GROQ_TRANSCRIBE_MODEL: parsed.GROQ_TRANSCRIBE_MODEL,
    GROQ_REASONING_MODEL: parsed.GROQ_REASONING_MODEL,
    GROQ_FAST_MODEL: parsed.GROQ_FAST_MODEL,
    GROQ_FALLBACK_MODEL: parsed.GROQ_FALLBACK_MODEL,
    GROQ_ROUTING_MODEL: parsed.GROQ_ROUTING_MODEL,
    GROQ_VISION_MODEL: parsed.GROQ_VISION_MODEL,
    GROQ_VISION_SENSITIVE_DATA_ATTESTED:
      parsed.GROQ_VISION_SENSITIVE_DATA_ATTESTED,
    GROQ_COMPOUND_ENABLED: parsed.GROQ_COMPOUND_ENABLED,
    GROQ_COMPOUND_RESEARCH_ENABLED: parsed.GROQ_COMPOUND_RESEARCH_ENABLED,
    GROQ_COMPOUND_DEEP_ENABLED: parsed.GROQ_COMPOUND_DEEP_ENABLED,
    GROQ_COMPOUND_MODEL: parsed.GROQ_COMPOUND_MODEL,
    GROQ_COMPOUND_MINI_MODEL: parsed.GROQ_COMPOUND_MINI_MODEL,
    GROQ_COMPOUND_SEARCH_COUNTRY: parsed.GROQ_COMPOUND_SEARCH_COUNTRY,
    GROQ_COMPOUND_INCLUDE_DOMAINS: parsed.GROQ_COMPOUND_INCLUDE_DOMAINS,
    GROQ_COMPOUND_EXCLUDE_DOMAINS: parsed.GROQ_COMPOUND_EXCLUDE_DOMAINS,
    GEMINI_API_KEY: parsed.GEMINI_API_KEY ?? "",
    GEMINI_BASE_URL:
      parsed.GEMINI_BASE_URL ??
      "https://generativelanguage.googleapis.com/v1beta/openai",
    GEMINI_INTERACTIONS_BASE_URL:
      parsed.GEMINI_INTERACTIONS_BASE_URL ??
      "https://generativelanguage.googleapis.com/v1beta",
    GEMINI_TEXT_MODEL: parsed.GEMINI_TEXT_MODEL,
    GEMINI_FAST_MODEL: parsed.GEMINI_FAST_MODEL,
    GEMINI_REASONING_MODEL: parsed.GEMINI_REASONING_MODEL,
    GEMINI_VISION_MODEL: parsed.GEMINI_VISION_MODEL,
    GEMINI_VISION_SENSITIVE_DATA_ATTESTED:
      parsed.GEMINI_VISION_SENSITIVE_DATA_ATTESTED,
    GEMINI_IMAGE_MODEL: parsed.GEMINI_IMAGE_MODEL,
    GEMINI_IMAGE_PRO_MODEL: parsed.GEMINI_IMAGE_PRO_MODEL,
    GEMINI_IMAGE_SIZE: parsed.GEMINI_IMAGE_SIZE,
    GEMINI_IMAGE_PRO_ENABLED: parsed.GEMINI_IMAGE_PRO_ENABLED,
    GEMINI_IMAGE_DAILY_GLOBAL_LIMIT: parsed.GEMINI_IMAGE_DAILY_GLOBAL_LIMIT,
    GEMINI_IMAGE_PRO_DAILY_GLOBAL_LIMIT:
      parsed.GEMINI_IMAGE_PRO_DAILY_GLOBAL_LIMIT,
    GEMINI_IMAGE_4K_DAILY_GLOBAL_LIMIT:
      parsed.GEMINI_IMAGE_4K_DAILY_GLOBAL_LIMIT,
    ELYAN_GEMINI_FREE_FEATURES_ENABLED:
      parsed.ELYAN_GEMINI_FREE_FEATURES_ENABLED,
    GEMINI_FREE_ONLY: parsed.GEMINI_FREE_ONLY,
    GEMINI_FREE_DATA_USAGE_ATTESTED: parsed.GEMINI_FREE_DATA_USAGE_ATTESTED,
    GEMINI_FREE_MODEL_ALLOWLIST: parsed.GEMINI_FREE_MODEL_ALLOWLIST,
    GEMINI_FREE_DAILY_REQUEST_LIMIT: parsed.GEMINI_FREE_DAILY_REQUEST_LIMIT,
    GEMINI_FREE_DAILY_INPUT_TOKEN_LIMIT:
      parsed.GEMINI_FREE_DAILY_INPUT_TOKEN_LIMIT,
    GEMINI_FREE_DAILY_OUTPUT_TOKEN_LIMIT:
      parsed.GEMINI_FREE_DAILY_OUTPUT_TOKEN_LIMIT,
    GEMINI_FREE_USER_DAILY_REQUEST_LIMIT:
      parsed.GEMINI_FREE_USER_DAILY_REQUEST_LIMIT,
    GEMINI_FREE_UTILITY_SAMPLE_PERCENT:
      parsed.GEMINI_FREE_UTILITY_SAMPLE_PERCENT,
    OPENROUTER_API_KEY: parsed.OPENROUTER_API_KEY ?? "",
    OPENROUTER_BASE_URL:
      parsed.OPENROUTER_BASE_URL ?? "https://openrouter.ai/api/v1",
    TOKEN_ENCRYPTION_KEY: parsed.TOKEN_ENCRYPTION_KEY ?? "",
    IYZICO_PUBLIC_BASE_URL:
      parsed.IYZICO_PUBLIC_BASE_URL ?? parsed.APP_BASE_URL,
    ELYAN_SHARED_BRAIN_PROVIDER: parsed.ELYAN_SHARED_BRAIN_PROVIDER,
    ELYAN_SHARED_BRAIN_BASE_URL: parsed.ELYAN_SHARED_BRAIN_BASE_URL,
    ELYAN_SHARED_BRAIN_FALLBACK_PROVIDER:
      parsed.ELYAN_SHARED_BRAIN_FALLBACK_PROVIDER,
    ELYAN_SHARED_BRAIN_FALLBACK_BASE_URL:
      parsed.ELYAN_SHARED_BRAIN_FALLBACK_BASE_URL,
    ELYAN_SHARED_BRAIN_MODEL: parsed.ELYAN_SHARED_BRAIN_MODEL,
    ELYAN_SHARED_BRAIN_FAST_MODEL: parsed.ELYAN_SHARED_BRAIN_FAST_MODEL,
    ELYAN_SHARED_BRAIN_BALANCED_MODEL: parsed.ELYAN_SHARED_BRAIN_BALANCED_MODEL,
    ELYAN_SHARED_BRAIN_PLANNING_MODEL: parsed.ELYAN_SHARED_BRAIN_PLANNING_MODEL,
    ELYAN_SHARED_BRAIN_KEEP_ALIVE: parsed.ELYAN_SHARED_BRAIN_KEEP_ALIVE,
    ELYAN_WEB_GROUNDING_ENABLED: parsed.ELYAN_WEB_GROUNDING_ENABLED,
    ELYAN_WEB_SEARCH_BASE_URL: parsed.ELYAN_WEB_SEARCH_BASE_URL,
    ELYAN_WEB_GROUNDING_MAX_RESULTS: parsed.ELYAN_WEB_GROUNDING_MAX_RESULTS,
    ELYAN_WEB_GROUNDING_TIMEOUT_MS: parsed.ELYAN_WEB_GROUNDING_TIMEOUT_MS,
    ELYAN_SEARCH_PROVIDER: parsed.ELYAN_SEARCH_PROVIDER,
    BRAVE_SEARCH_API_KEY: parsed.BRAVE_SEARCH_API_KEY,
    SEARXNG_BASE_URL: parsed.SEARXNG_BASE_URL,
    JINA_READER_ENABLED: parsed.JINA_READER_ENABLED,
    ELYAN_RAG_SEMANTIC_RERANK_ENABLED: parsed.ELYAN_RAG_SEMANTIC_RERANK_ENABLED,
    ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED:
      parsed.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED,
    ELYAN_RAG_SEMANTIC_RERANK_MODEL: parsed.ELYAN_RAG_SEMANTIC_RERANK_MODEL,
    ELYAN_RAG_SEMANTIC_RERANK_WINDOW: parsed.ELYAN_RAG_SEMANTIC_RERANK_WINDOW,
    ELYAN_TURN_ENVELOPE_ENABLED: parsed.ELYAN_TURN_ENVELOPE_ENABLED,
    ELYAN_DIALOGUE_STATE_ENABLED: parsed.ELYAN_DIALOGUE_STATE_ENABLED,
    ELYAN_MEMORY_FABRIC_V2_ENABLED: parsed.ELYAN_MEMORY_FABRIC_V2_ENABLED,
    ELYAN_USER_MODEL_V2_ENABLED: parsed.ELYAN_USER_MODEL_V2_ENABLED,
    ELYAN_GOAL_STATE_V2_ENABLED: parsed.ELYAN_GOAL_STATE_V2_ENABLED,
    ELYAN_AGENT_LOOP_ENABLED: parsed.ELYAN_AGENT_LOOP_ENABLED,
    ELYAN_CORE_TOOLS_ENABLED: parsed.ELYAN_CORE_TOOLS_ENABLED,
    ELYAN_SEMANTIC_TOOL_SELECTION_ENABLED:
      parsed.ELYAN_SEMANTIC_TOOL_SELECTION_ENABLED,
    ELYAN_CONNECTOR_TOOLS_ENABLED: parsed.ELYAN_CONNECTOR_TOOLS_ENABLED,
    ELYAN_MCP_SDK_ENABLED: parsed.ELYAN_MCP_SDK_ENABLED,
    ELYAN_MCP_DYNAMIC_TOOLS_ENABLED: parsed.ELYAN_MCP_DYNAMIC_TOOLS_ENABLED,
    ELYAN_SOURCE_TYPED_CONNECTOR_BLOCKS_ENABLED:
      parsed.ELYAN_SOURCE_TYPED_CONNECTOR_BLOCKS_ENABLED,
    ELYAN_TOOL_CALL_BLOCK_ENABLED: parsed.ELYAN_TOOL_CALL_BLOCK_ENABLED,
    ELYAN_SERVER_TOOL_LOOP_ENABLED: parsed.ELYAN_SERVER_TOOL_LOOP_ENABLED,
    ELYAN_AI_DATA_SHARING_CONSENT_REQUIRED:
      parsed.ELYAN_AI_DATA_SHARING_CONSENT_REQUIRED,
    ELYAN_PROACTIVE_ENGINE_ENABLED: parsed.ELYAN_PROACTIVE_ENGINE_ENABLED,
    ELYAN_PUSH_ENABLED: parsed.ELYAN_PUSH_ENABLED,
    FCM_PROJECT_ID: parsed.FCM_PROJECT_ID,
    FCM_CLIENT_EMAIL: parsed.FCM_CLIENT_EMAIL,
    FCM_PRIVATE_KEY: parsed.FCM_PRIVATE_KEY,
    ELYAN_NIGHT_WATCH_ENABLED: parsed.ELYAN_NIGHT_WATCH_ENABLED,
    ELYAN_NIGHT_WATCH_MAX_JOBS_PER_NIGHT:
      parsed.ELYAN_NIGHT_WATCH_MAX_JOBS_PER_NIGHT,
    ELYAN_MORNING_DIGEST_HOUR: parsed.ELYAN_MORNING_DIGEST_HOUR,
    ELYAN_PROACTIVE_OBSERVER_ENABLED: parsed.ELYAN_PROACTIVE_OBSERVER_ENABLED,
    ELYAN_PROACTIVE_OBSERVER_INTERVAL_MS:
      parsed.ELYAN_PROACTIVE_OBSERVER_INTERVAL_MS,
    ELYAN_CLOUD_VISION_ENABLED: parsed.ELYAN_CLOUD_VISION_ENABLED,
    ELYAN_COST_GUARD_ENABLED: parsed.ELYAN_COST_GUARD_ENABLED,
    ELYAN_MODEL_CANARY_ENABLED: parsed.ELYAN_MODEL_CANARY_ENABLED,
    ELYAN_MODEL_PRIMARY_ENABLED: parsed.ELYAN_MODEL_PRIMARY_ENABLED,
    ELYAN_WEIGHT_TRAINING_ENABLED: parsed.ELYAN_WEIGHT_TRAINING_ENABLED,
    ELYAN_BEHAVIOR_LEARNING_ENABLED: parsed.ELYAN_BEHAVIOR_LEARNING_ENABLED,
    ELYAN_BLOCKS_V11_ENABLED: parsed.ELYAN_BLOCKS_V11_ENABLED,
    ELYAN_SCALABLE_STATE_READS_ENABLED:
      parsed.ELYAN_SCALABLE_STATE_READS_ENABLED,
    ELYAN_COGNITIVE_FOUNDATION_V2_ENABLED:
      parsed.ELYAN_COGNITIVE_FOUNDATION_V2_ENABLED,
    ELYAN_COGNITIVE_SHADOW_READ_ENABLED:
      parsed.ELYAN_COGNITIVE_SHADOW_READ_ENABLED,
    ELYAN_TENANT_RLS_ENFORCEMENT_ENABLED:
      parsed.ELYAN_TENANT_RLS_ENFORCEMENT_ENABLED,
    ELYAN_COGNITIVE_FOUNDATION_ROLLOUT_PERCENT:
      parsed.ELYAN_COGNITIVE_FOUNDATION_ROLLOUT_PERCENT,
    ELYAN_AGENT_ENGINE_V2_ENABLED: parsed.ELYAN_AGENT_ENGINE_V2_ENABLED,
    ELYAN_AGENT_ENGINE_SHADOW_ENABLED: parsed.ELYAN_AGENT_ENGINE_SHADOW_ENABLED,
    ELYAN_AGENT_ENGINE_ROLLOUT_PERCENT:
      parsed.ELYAN_AGENT_ENGINE_ROLLOUT_PERCENT,
    ELYAN_CONTINUOUS_LEARNING_V2_ENABLED:
      parsed.ELYAN_CONTINUOUS_LEARNING_V2_ENABLED,
    ELYAN_CONTINUOUS_LEARNING_SHADOW_ENABLED:
      parsed.ELYAN_CONTINUOUS_LEARNING_SHADOW_ENABLED,
    ELYAN_CONTINUOUS_LEARNING_DAILY_BATCH_LIMIT:
      parsed.ELYAN_CONTINUOUS_LEARNING_DAILY_BATCH_LIMIT,
    ELYAN_CONTINUOUS_LEARNING_REPLAY_RATIO:
      parsed.ELYAN_CONTINUOUS_LEARNING_REPLAY_RATIO,
    ELYAN_WORLD_CONTEXT_PACKETS_ENABLED:
      parsed.ELYAN_WORLD_CONTEXT_PACKETS_ENABLED,
    ELYAN_SHARED_BRAIN_SYSTEM_PROMPT: parsed.ELYAN_SHARED_BRAIN_SYSTEM_PROMPT,
  };
}
