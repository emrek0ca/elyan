-- 0015-0018 already own billing and brain-memory schema. This generated
-- migration keeps only the training enum and desktop operator deltas.
ALTER TYPE "public"."training_job_kind" ADD VALUE 'memory_extraction';
--> statement-breakpoint
ALTER TYPE "public"."training_job_kind" ADD VALUE 'memory_consolidation';
--> statement-breakpoint
ALTER TYPE "public"."training_job_kind" ADD VALUE 'memory_reconsolidation';
--> statement-breakpoint
ALTER TYPE "public"."training_job_kind" ADD VALUE 'memory_index';
--> statement-breakpoint
CREATE TABLE "input_actions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"operator_step_id" uuid NOT NULL,
	"action_type" varchar(64) NOT NULL,
	"target_bbox" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"text_redacted" boolean DEFAULT false NOT NULL,
	"status" varchar(40) DEFAULT 'pending' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "operator_runs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"device_id" uuid NOT NULL,
	"task_id" uuid,
	"run_key" varchar(120) NOT NULL,
	"task" text NOT NULL,
	"status" varchar(40) DEFAULT 'running' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "operator_steps" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"operator_run_id" uuid NOT NULL,
	"step_index" integer NOT NULL,
	"screen_observation_id" uuid,
	"proposed_action" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"executed_action" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"result" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"requires_approval" boolean DEFAULT false NOT NULL,
	"approved_by_user" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "screen_observations" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"operator_run_id" uuid,
	"screenshot_hash" varchar(128) NOT NULL,
	"elements_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"active_app" varchar(255),
	"active_window" varchar(500),
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "input_actions" ADD CONSTRAINT "input_actions_operator_step_id_operator_steps_id_fk" FOREIGN KEY ("operator_step_id") REFERENCES "public"."operator_steps"("id") ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "operator_runs" ADD CONSTRAINT "operator_runs_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "operator_runs" ADD CONSTRAINT "operator_runs_device_id_devices_id_fk" FOREIGN KEY ("device_id") REFERENCES "public"."devices"("id") ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "operator_runs" ADD CONSTRAINT "operator_runs_task_id_tasks_id_fk" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE set null ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "operator_steps" ADD CONSTRAINT "operator_steps_operator_run_id_operator_runs_id_fk" FOREIGN KEY ("operator_run_id") REFERENCES "public"."operator_runs"("id") ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "operator_steps" ADD CONSTRAINT "operator_steps_screen_observation_id_screen_observations_id_fk" FOREIGN KEY ("screen_observation_id") REFERENCES "public"."screen_observations"("id") ON DELETE set null ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "screen_observations" ADD CONSTRAINT "screen_observations_operator_run_id_operator_runs_id_fk" FOREIGN KEY ("operator_run_id") REFERENCES "public"."operator_runs"("id") ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint
CREATE INDEX "input_actions_step_idx" ON "input_actions" USING btree ("operator_step_id");
--> statement-breakpoint
CREATE INDEX "operator_runs_user_idx" ON "operator_runs" USING btree ("user_id");
--> statement-breakpoint
CREATE INDEX "operator_runs_device_idx" ON "operator_runs" USING btree ("device_id");
--> statement-breakpoint
CREATE INDEX "operator_runs_task_idx" ON "operator_runs" USING btree ("task_id");
--> statement-breakpoint
CREATE UNIQUE INDEX "operator_runs_run_key_uidx" ON "operator_runs" USING btree ("run_key");
--> statement-breakpoint
CREATE UNIQUE INDEX "operator_steps_run_step_uidx" ON "operator_steps" USING btree ("operator_run_id", "step_index");
--> statement-breakpoint
CREATE INDEX "screen_observations_run_idx" ON "screen_observations" USING btree ("operator_run_id");
--> statement-breakpoint
CREATE INDEX "screen_observations_hash_idx" ON "screen_observations" USING btree ("screenshot_hash");
