CREATE TYPE "public"."ai_invocation_status" AS ENUM('success', 'timeout', 'fallback', 'error');--> statement-breakpoint
CREATE TYPE "public"."audit_actor_type" AS ENUM('user', 'runtime', 'system');--> statement-breakpoint
CREATE TYPE "public"."audit_status" AS ENUM('success', 'failure');--> statement-breakpoint
CREATE TYPE "public"."connection_provider" AS ENUM('google', 'notion', 'slack', 'discord', 'github', 'linear', 'telegram', 'dropbox', 'trello', 'jira', 'clickup', 'webhooks', 'custom_api', 'openai', 'claude', 'groq', 'ollama', 'openrouter');--> statement-breakpoint
CREATE TYPE "public"."integration_auth_type" AS ENUM('oauth2', 'api_key', 'webhook', 'none');--> statement-breakpoint
CREATE TYPE "public"."integration_connection_status" AS ENUM('pending', 'connected', 'error', 'revoked');--> statement-breakpoint
CREATE TYPE "public"."mcp_auth_type" AS ENUM('none', 'bearer', 'oauth2', 'api_key');--> statement-breakpoint
CREATE TYPE "public"."mcp_server_status" AS ENUM('configured', 'connected', 'degraded', 'revoked');--> statement-breakpoint
CREATE TYPE "public"."mcp_transport" AS ENUM('stdio', 'remote', 'oauth_remote', 'streamable_http');--> statement-breakpoint
CREATE TYPE "public"."oauth_state_status" AS ENUM('pending', 'completed', 'expired');--> statement-breakpoint
CREATE TYPE "public"."user_role" AS ENUM('user', 'admin');--> statement-breakpoint
ALTER TYPE "public"."ai_provider" ADD VALUE 'openrouter';--> statement-breakpoint
ALTER TYPE "public"."task_status" ADD VALUE 'planning' BEFORE 'running';--> statement-breakpoint
CREATE TABLE "ai_provider_credentials" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"provider" "ai_provider" NOT NULL,
	"label" varchar(120),
	"encrypted_payload" text NOT NULL,
	"default_model" varchar(160),
	"base_url" text,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "ai_provider_invocations" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"task_id" uuid,
	"provider" "ai_provider" NOT NULL,
	"model" varchar(160) NOT NULL,
	"workload" varchar(80) NOT NULL,
	"route" varchar(80) NOT NULL,
	"status" "ai_invocation_status" NOT NULL,
	"prompt_tokens" integer DEFAULT 0 NOT NULL,
	"completion_tokens" integer DEFAULT 0 NOT NULL,
	"total_tokens" integer DEFAULT 0 NOT NULL,
	"latency_ms" integer,
	"fallback_from_provider" "ai_provider",
	"fallback_from_model" varchar(160),
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "audit_logs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid,
	"actor_type" "audit_actor_type" NOT NULL,
	"actor_id" varchar(160),
	"action" varchar(160) NOT NULL,
	"resource_type" varchar(120) NOT NULL,
	"resource_id" varchar(160),
	"status" "audit_status" NOT NULL,
	"ip_address" varchar(64),
	"user_agent" text,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "integration_connections" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"provider" "connection_provider" NOT NULL,
	"auth_type" "integration_auth_type" NOT NULL,
	"status" "integration_connection_status" DEFAULT 'pending' NOT NULL,
	"display_name" varchar(160),
	"external_account_id" varchar(160),
	"scopes" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"capabilities" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"last_synced_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "integration_credentials" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"connection_id" uuid NOT NULL,
	"encrypted_payload" text NOT NULL,
	"expires_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "mcp_servers" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"integration_connection_id" uuid,
	"name" varchar(160) NOT NULL,
	"transport" "mcp_transport" NOT NULL,
	"auth_type" "mcp_auth_type" DEFAULT 'none' NOT NULL,
	"status" "mcp_server_status" DEFAULT 'configured' NOT NULL,
	"base_url" text,
	"command" text,
	"args" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"config" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"capabilities" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"last_seen_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "oauth_states" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"provider" "connection_provider" NOT NULL,
	"status" "oauth_state_status" DEFAULT 'pending' NOT NULL,
	"state" varchar(160) NOT NULL,
	"redirect_uri" text,
	"requested_scopes" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"code_verifier" text,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	"consumed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "oauth_states_state_unique" UNIQUE("state")
);
--> statement-breakpoint
ALTER TABLE "devices" ADD COLUMN "external_device_id" varchar(160);--> statement-breakpoint
ALTER TABLE "users" ADD COLUMN "role" "user_role" DEFAULT 'user' NOT NULL;--> statement-breakpoint
ALTER TABLE "ai_provider_credentials" ADD CONSTRAINT "ai_provider_credentials_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ai_provider_invocations" ADD CONSTRAINT "ai_provider_invocations_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ai_provider_invocations" ADD CONSTRAINT "ai_provider_invocations_task_id_tasks_id_fk" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "audit_logs" ADD CONSTRAINT "audit_logs_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "integration_connections" ADD CONSTRAINT "integration_connections_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "integration_credentials" ADD CONSTRAINT "integration_credentials_connection_id_integration_connections_id_fk" FOREIGN KEY ("connection_id") REFERENCES "public"."integration_connections"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "mcp_servers" ADD CONSTRAINT "mcp_servers_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "mcp_servers" ADD CONSTRAINT "mcp_servers_integration_connection_id_integration_connections_id_fk" FOREIGN KEY ("integration_connection_id") REFERENCES "public"."integration_connections"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "oauth_states" ADD CONSTRAINT "oauth_states_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "ai_provider_credentials_user_idx" ON "ai_provider_credentials" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "ai_provider_credentials_provider_idx" ON "ai_provider_credentials" USING btree ("provider");--> statement-breakpoint
CREATE INDEX "ai_provider_invocations_user_idx" ON "ai_provider_invocations" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "ai_provider_invocations_task_idx" ON "ai_provider_invocations" USING btree ("task_id");--> statement-breakpoint
CREATE INDEX "ai_provider_invocations_provider_idx" ON "ai_provider_invocations" USING btree ("provider");--> statement-breakpoint
CREATE INDEX "audit_logs_user_idx" ON "audit_logs" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "audit_logs_actor_idx" ON "audit_logs" USING btree ("actor_type","actor_id");--> statement-breakpoint
CREATE INDEX "integration_connections_user_idx" ON "integration_connections" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "integration_connections_provider_idx" ON "integration_connections" USING btree ("provider");--> statement-breakpoint
CREATE INDEX "integration_credentials_connection_idx" ON "integration_credentials" USING btree ("connection_id");--> statement-breakpoint
CREATE INDEX "mcp_servers_user_idx" ON "mcp_servers" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "mcp_servers_integration_idx" ON "mcp_servers" USING btree ("integration_connection_id");--> statement-breakpoint
CREATE INDEX "oauth_states_state_idx" ON "oauth_states" USING btree ("state");--> statement-breakpoint
CREATE INDEX "oauth_states_user_idx" ON "oauth_states" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "devices_external_device_idx" ON "devices" USING btree ("external_device_id");