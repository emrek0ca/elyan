CREATE TYPE "public"."ai_provider" AS ENUM('openai', 'claude', 'ollama', 'groq');--> statement-breakpoint
CREATE TYPE "public"."artifact_kind" AS ENUM('markdown', 'file', 'summary', 'screenshot', 'structured_output');--> statement-breakpoint
CREATE TYPE "public"."device_type" AS ENUM('mobile', 'desktop');--> statement-breakpoint
CREATE TYPE "public"."pair_session_status" AS ENUM('pending', 'claimed', 'expired');--> statement-breakpoint
CREATE TYPE "public"."runtime_connection_status" AS ENUM('online', 'busy', 'idle', 'offline');--> statement-breakpoint
CREATE TYPE "public"."subscription_status" AS ENUM('free', 'trialing', 'active', 'past_due', 'canceled');--> statement-breakpoint
CREATE TYPE "public"."task_status" AS ENUM('queued', 'running', 'waiting_approval', 'completed', 'failed', 'canceled');--> statement-breakpoint
CREATE TABLE "artifacts" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"task_id" uuid NOT NULL,
	"kind" "artifact_kind" NOT NULL,
	"name" varchar(255) NOT NULL,
	"content_type" varchar(255) NOT NULL,
	"storage_key" text,
	"text_content" text,
	"payload" jsonb,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "devices" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid,
	"type" "device_type" NOT NULL,
	"label" varchar(120) NOT NULL,
	"platform" varchar(120) NOT NULL,
	"runtime_version" varchar(80),
	"app_version" varchar(80),
	"device_key_hash" text,
	"is_active" boolean DEFAULT true NOT NULL,
	"paired_at" timestamp with time zone,
	"last_seen_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "pair_sessions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"desktop_device_id" uuid NOT NULL,
	"claimed_by_user_id" uuid,
	"status" "pair_session_status" DEFAULT 'pending' NOT NULL,
	"pairing_code" varchar(24) NOT NULL,
	"pairing_token_hash" text NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	"claimed_at" timestamp with time zone,
	"consumed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "pair_sessions_pairing_code_unique" UNIQUE("pairing_code")
);
--> statement-breakpoint
CREATE TABLE "runtime_connections" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"device_id" uuid NOT NULL,
	"user_id" uuid NOT NULL,
	"status" "runtime_connection_status" DEFAULT 'online' NOT NULL,
	"socket_session_id" varchar(120),
	"current_task_id" uuid,
	"capabilities" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"connected_at" timestamp with time zone DEFAULT now() NOT NULL,
	"last_heartbeat_at" timestamp with time zone DEFAULT now() NOT NULL,
	"disconnected_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "sessions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"refresh_token_hash" text NOT NULL,
	"user_agent" text,
	"ip_address" varchar(64),
	"expires_at" timestamp with time zone NOT NULL,
	"revoked_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"last_used_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "subscriptions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"plan_code" varchar(64) DEFAULT 'free' NOT NULL,
	"status" "subscription_status" DEFAULT 'free' NOT NULL,
	"task_limit_monthly" integer DEFAULT 100 NOT NULL,
	"ai_credits_monthly" integer DEFAULT 0 NOT NULL,
	"period_ends_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "subscriptions_user_id_unique" UNIQUE("user_id")
);
--> statement-breakpoint
CREATE TABLE "task_events" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"task_id" uuid NOT NULL,
	"status" "task_status" NOT NULL,
	"message" text,
	"payload" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "tasks" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"target_device_id" uuid NOT NULL,
	"title" varchar(200) NOT NULL,
	"payload" jsonb NOT NULL,
	"requested_capabilities" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"preferred_ai_provider" "ai_provider",
	"status" "task_status" DEFAULT 'queued' NOT NULL,
	"queue_position" integer DEFAULT 0 NOT NULL,
	"summary" text,
	"error" text,
	"approval_request" jsonb,
	"result" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"canceled_at" timestamp with time zone,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "usage_records" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"task_id" uuid,
	"metric" varchar(80) NOT NULL,
	"quantity" integer DEFAULT 0 NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "users" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"email" varchar(320) NOT NULL,
	"password_hash" text NOT NULL,
	"display_name" varchar(120),
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "users_email_unique" UNIQUE("email")
);
--> statement-breakpoint
ALTER TABLE "artifacts" ADD CONSTRAINT "artifacts_task_id_tasks_id_fk" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "devices" ADD CONSTRAINT "devices_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "pair_sessions" ADD CONSTRAINT "pair_sessions_desktop_device_id_devices_id_fk" FOREIGN KEY ("desktop_device_id") REFERENCES "public"."devices"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "pair_sessions" ADD CONSTRAINT "pair_sessions_claimed_by_user_id_users_id_fk" FOREIGN KEY ("claimed_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runtime_connections" ADD CONSTRAINT "runtime_connections_device_id_devices_id_fk" FOREIGN KEY ("device_id") REFERENCES "public"."devices"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "runtime_connections" ADD CONSTRAINT "runtime_connections_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "sessions" ADD CONSTRAINT "sessions_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "subscriptions" ADD CONSTRAINT "subscriptions_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "task_events" ADD CONSTRAINT "task_events_task_id_tasks_id_fk" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_target_device_id_devices_id_fk" FOREIGN KEY ("target_device_id") REFERENCES "public"."devices"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "usage_records" ADD CONSTRAINT "usage_records_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "usage_records" ADD CONSTRAINT "usage_records_task_id_tasks_id_fk" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "artifacts_task_idx" ON "artifacts" USING btree ("task_id");--> statement-breakpoint
CREATE INDEX "devices_user_idx" ON "devices" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "devices_type_idx" ON "devices" USING btree ("type");--> statement-breakpoint
CREATE INDEX "pair_sessions_desktop_idx" ON "pair_sessions" USING btree ("desktop_device_id");--> statement-breakpoint
CREATE INDEX "pair_sessions_status_idx" ON "pair_sessions" USING btree ("status");--> statement-breakpoint
CREATE INDEX "runtime_connections_device_idx" ON "runtime_connections" USING btree ("device_id");--> statement-breakpoint
CREATE INDEX "runtime_connections_user_idx" ON "runtime_connections" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "sessions_user_idx" ON "sessions" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "subscriptions_user_idx" ON "subscriptions" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "task_events_task_idx" ON "task_events" USING btree ("task_id");--> statement-breakpoint
CREATE INDEX "tasks_user_idx" ON "tasks" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "tasks_target_device_idx" ON "tasks" USING btree ("target_device_id");--> statement-breakpoint
CREATE INDEX "tasks_status_idx" ON "tasks" USING btree ("status");--> statement-breakpoint
CREATE INDEX "usage_records_user_idx" ON "usage_records" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "usage_records_task_idx" ON "usage_records" USING btree ("task_id");--> statement-breakpoint
CREATE INDEX "users_email_idx" ON "users" USING btree ("email");