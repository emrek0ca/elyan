ALTER TYPE "public"."training_job_kind" ADD VALUE 'memory_extraction';--> statement-breakpoint
ALTER TYPE "public"."training_job_kind" ADD VALUE 'memory_consolidation';--> statement-breakpoint
ALTER TYPE "public"."training_job_kind" ADD VALUE 'memory_reconsolidation';--> statement-breakpoint
ALTER TYPE "public"."training_job_kind" ADD VALUE 'memory_index';--> statement-breakpoint
CREATE TABLE "billing_credit_ledger" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"entitlement_event_id" uuid,
	"task_id" uuid,
	"ai_provider_invocation_id" uuid,
	"reason" varchar(80) NOT NULL,
	"delta_credits" integer NOT NULL,
	"balance_after" integer NOT NULL,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "billing_entitlement_events" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"store_transaction_id" uuid,
	"source_provider" varchar(32) NOT NULL,
	"plan_code" varchar(64) NOT NULL,
	"event_type" varchar(64) NOT NULL,
	"status" varchar(64) NOT NULL,
	"source_reference_code" varchar(255),
	"event_fingerprint" varchar(64) NOT NULL,
	"effective_period_started_at" timestamp with time zone,
	"effective_period_ends_at" timestamp with time zone,
	"credit_grant_amount" integer DEFAULT 0 NOT NULL,
	"credit_delta" integer DEFAULT 0 NOT NULL,
	"revoke_future_entitlement" boolean DEFAULT false NOT NULL,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "billing_store_transactions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid,
	"provider" varchar(32) NOT NULL,
	"plan_code" varchar(64),
	"product_id" varchar(160),
	"purchase_token" varchar(255),
	"original_transaction_id" varchar(255),
	"transaction_id" varchar(255),
	"order_id" varchar(255),
	"linked_purchase_token" varchar(255),
	"environment" varchar(32),
	"status" varchar(64) NOT NULL,
	"raw_payload_hash" varchar(64) NOT NULL,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"verified_at" timestamp with time zone DEFAULT now() NOT NULL,
	"last_seen_at" timestamp with time zone DEFAULT now() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "brain_memory_episodes" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"account_id" uuid,
	"scope" "brain_scope" DEFAULT 'user' NOT NULL,
	"source_session_id" uuid,
	"source_task_id" uuid,
	"episode_type" varchar(80) NOT NULL,
	"summary" text NOT NULL,
	"participants" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"started_at" timestamp with time zone,
	"ended_at" timestamp with time zone,
	"confidence" integer DEFAULT 50 NOT NULL,
	"importance_score" integer DEFAULT 50 NOT NULL,
	"is_pinned" boolean DEFAULT false NOT NULL,
	"privacy_level" varchar(32) DEFAULT 'safe' NOT NULL,
	"lifecycle_status" varchar(32) DEFAULT 'active' NOT NULL,
	"deleted_at" timestamp with time zone,
	"deleted_reason" varchar(240),
	"supersedes_episode_id" uuid,
	"embedding_model" varchar(160),
	"stale_at" timestamp with time zone,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "brain_memory_facts" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"account_id" uuid,
	"scope" "brain_scope" DEFAULT 'user' NOT NULL,
	"fact_type" varchar(48) DEFAULT 'semantic' NOT NULL,
	"canonical_key" varchar(160) NOT NULL,
	"key" varchar(160) NOT NULL,
	"value" text NOT NULL,
	"confidence" integer DEFAULT 50 NOT NULL,
	"importance_score" integer DEFAULT 50 NOT NULL,
	"is_pinned" boolean DEFAULT false NOT NULL,
	"conflict_status" varchar(32) DEFAULT 'active' NOT NULL,
	"lifecycle_status" varchar(32) DEFAULT 'active' NOT NULL,
	"last_verified_at" timestamp with time zone,
	"deleted_at" timestamp with time zone,
	"deleted_reason" varchar(240),
	"stale_at" timestamp with time zone,
	"supersedes_fact_id" uuid,
	"embedding_model" varchar(160),
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "brain_memory_links" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"source_episode_id" uuid,
	"source_fact_id" uuid,
	"target_episode_id" uuid,
	"target_fact_id" uuid,
	"link_type" varchar(64) NOT NULL,
	"confidence" integer DEFAULT 50 NOT NULL,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "brain_memory_runs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid,
	"scope" "brain_scope" DEFAULT 'user' NOT NULL,
	"run_kind" varchar(64) NOT NULL,
	"status" varchar(32) DEFAULT 'completed' NOT NULL,
	"source_training_job_id" uuid,
	"processed_count" integer DEFAULT 0 NOT NULL,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"started_at" timestamp with time zone DEFAULT now() NOT NULL,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
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
ALTER TABLE "billing_credit_ledger" ADD CONSTRAINT "billing_credit_ledger_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "billing_credit_ledger" ADD CONSTRAINT "billing_credit_ledger_entitlement_event_id_billing_entitlement_events_id_fk" FOREIGN KEY ("entitlement_event_id") REFERENCES "public"."billing_entitlement_events"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "billing_credit_ledger" ADD CONSTRAINT "billing_credit_ledger_task_id_tasks_id_fk" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "billing_credit_ledger" ADD CONSTRAINT "billing_credit_ledger_ai_provider_invocation_id_ai_provider_invocations_id_fk" FOREIGN KEY ("ai_provider_invocation_id") REFERENCES "public"."ai_provider_invocations"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "billing_entitlement_events" ADD CONSTRAINT "billing_entitlement_events_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "billing_entitlement_events" ADD CONSTRAINT "billing_entitlement_events_store_transaction_id_billing_store_transactions_id_fk" FOREIGN KEY ("store_transaction_id") REFERENCES "public"."billing_store_transactions"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "billing_store_transactions" ADD CONSTRAINT "billing_store_transactions_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "brain_memory_episodes" ADD CONSTRAINT "brain_memory_episodes_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "brain_memory_episodes" ADD CONSTRAINT "brain_memory_episodes_source_task_id_tasks_id_fk" FOREIGN KEY ("source_task_id") REFERENCES "public"."tasks"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "brain_memory_facts" ADD CONSTRAINT "brain_memory_facts_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "brain_memory_links" ADD CONSTRAINT "brain_memory_links_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "brain_memory_links" ADD CONSTRAINT "brain_memory_links_source_episode_id_brain_memory_episodes_id_fk" FOREIGN KEY ("source_episode_id") REFERENCES "public"."brain_memory_episodes"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "brain_memory_links" ADD CONSTRAINT "brain_memory_links_source_fact_id_brain_memory_facts_id_fk" FOREIGN KEY ("source_fact_id") REFERENCES "public"."brain_memory_facts"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "brain_memory_links" ADD CONSTRAINT "brain_memory_links_target_episode_id_brain_memory_episodes_id_fk" FOREIGN KEY ("target_episode_id") REFERENCES "public"."brain_memory_episodes"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "brain_memory_links" ADD CONSTRAINT "brain_memory_links_target_fact_id_brain_memory_facts_id_fk" FOREIGN KEY ("target_fact_id") REFERENCES "public"."brain_memory_facts"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "brain_memory_runs" ADD CONSTRAINT "brain_memory_runs_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "brain_memory_runs" ADD CONSTRAINT "brain_memory_runs_source_training_job_id_training_jobs_id_fk" FOREIGN KEY ("source_training_job_id") REFERENCES "public"."training_jobs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "input_actions" ADD CONSTRAINT "input_actions_operator_step_id_operator_steps_id_fk" FOREIGN KEY ("operator_step_id") REFERENCES "public"."operator_steps"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "operator_runs" ADD CONSTRAINT "operator_runs_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "operator_runs" ADD CONSTRAINT "operator_runs_device_id_devices_id_fk" FOREIGN KEY ("device_id") REFERENCES "public"."devices"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "operator_runs" ADD CONSTRAINT "operator_runs_task_id_tasks_id_fk" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "operator_steps" ADD CONSTRAINT "operator_steps_operator_run_id_operator_runs_id_fk" FOREIGN KEY ("operator_run_id") REFERENCES "public"."operator_runs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "operator_steps" ADD CONSTRAINT "operator_steps_screen_observation_id_screen_observations_id_fk" FOREIGN KEY ("screen_observation_id") REFERENCES "public"."screen_observations"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "screen_observations" ADD CONSTRAINT "screen_observations_operator_run_id_operator_runs_id_fk" FOREIGN KEY ("operator_run_id") REFERENCES "public"."operator_runs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "billing_credit_ledger_user_idx" ON "billing_credit_ledger" USING btree ("user_id","created_at");--> statement-breakpoint
CREATE INDEX "billing_credit_ledger_entitlement_idx" ON "billing_credit_ledger" USING btree ("entitlement_event_id");--> statement-breakpoint
CREATE UNIQUE INDEX "billing_credit_ledger_invocation_reason_uidx" ON "billing_credit_ledger" USING btree ("ai_provider_invocation_id","reason");--> statement-breakpoint
CREATE INDEX "billing_entitlement_events_user_idx" ON "billing_entitlement_events" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "billing_entitlement_events_provider_idx" ON "billing_entitlement_events" USING btree ("source_provider");--> statement-breakpoint
CREATE UNIQUE INDEX "billing_entitlement_events_fingerprint_uidx" ON "billing_entitlement_events" USING btree ("event_fingerprint");--> statement-breakpoint
CREATE INDEX "billing_store_transactions_provider_idx" ON "billing_store_transactions" USING btree ("provider");--> statement-breakpoint
CREATE INDEX "billing_store_transactions_user_idx" ON "billing_store_transactions" USING btree ("user_id");--> statement-breakpoint
CREATE UNIQUE INDEX "billing_store_transactions_provider_txn_uidx" ON "billing_store_transactions" USING btree ("provider","transaction_id");--> statement-breakpoint
CREATE UNIQUE INDEX "billing_store_transactions_provider_purchase_uidx" ON "billing_store_transactions" USING btree ("provider","purchase_token");--> statement-breakpoint
CREATE INDEX "billing_store_transactions_provider_original_idx" ON "billing_store_transactions" USING btree ("provider","original_transaction_id");--> statement-breakpoint
CREATE INDEX "brain_memory_episodes_user_idx" ON "brain_memory_episodes" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "brain_memory_episodes_scope_idx" ON "brain_memory_episodes" USING btree ("scope");--> statement-breakpoint
CREATE INDEX "brain_memory_episodes_task_idx" ON "brain_memory_episodes" USING btree ("source_task_id");--> statement-breakpoint
CREATE INDEX "brain_memory_episodes_session_idx" ON "brain_memory_episodes" USING btree ("source_session_id");--> statement-breakpoint
CREATE INDEX "brain_memory_episodes_stale_idx" ON "brain_memory_episodes" USING btree ("stale_at");--> statement-breakpoint
CREATE INDEX "brain_memory_episodes_pinned_idx" ON "brain_memory_episodes" USING btree ("is_pinned");--> statement-breakpoint
CREATE INDEX "brain_memory_episodes_lifecycle_idx" ON "brain_memory_episodes" USING btree ("lifecycle_status");--> statement-breakpoint
CREATE INDEX "brain_memory_facts_user_idx" ON "brain_memory_facts" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "brain_memory_facts_scope_idx" ON "brain_memory_facts" USING btree ("scope");--> statement-breakpoint
CREATE INDEX "brain_memory_facts_canonical_idx" ON "brain_memory_facts" USING btree ("user_id","canonical_key");--> statement-breakpoint
CREATE INDEX "brain_memory_facts_conflict_idx" ON "brain_memory_facts" USING btree ("conflict_status");--> statement-breakpoint
CREATE INDEX "brain_memory_facts_stale_idx" ON "brain_memory_facts" USING btree ("stale_at");--> statement-breakpoint
CREATE INDEX "brain_memory_facts_pinned_idx" ON "brain_memory_facts" USING btree ("is_pinned");--> statement-breakpoint
CREATE INDEX "brain_memory_facts_lifecycle_idx" ON "brain_memory_facts" USING btree ("lifecycle_status");--> statement-breakpoint
CREATE INDEX "brain_memory_links_user_idx" ON "brain_memory_links" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "brain_memory_links_type_idx" ON "brain_memory_links" USING btree ("link_type");--> statement-breakpoint
CREATE INDEX "brain_memory_runs_user_idx" ON "brain_memory_runs" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "brain_memory_runs_kind_idx" ON "brain_memory_runs" USING btree ("run_kind");--> statement-breakpoint
CREATE INDEX "brain_memory_runs_status_idx" ON "brain_memory_runs" USING btree ("status");--> statement-breakpoint
CREATE INDEX "brain_memory_runs_started_idx" ON "brain_memory_runs" USING btree ("started_at");--> statement-breakpoint
CREATE INDEX "input_actions_step_idx" ON "input_actions" USING btree ("operator_step_id");--> statement-breakpoint
CREATE INDEX "operator_runs_user_idx" ON "operator_runs" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "operator_runs_device_idx" ON "operator_runs" USING btree ("device_id");--> statement-breakpoint
CREATE INDEX "operator_runs_task_idx" ON "operator_runs" USING btree ("task_id");--> statement-breakpoint
CREATE UNIQUE INDEX "operator_runs_run_key_uidx" ON "operator_runs" USING btree ("run_key");--> statement-breakpoint
CREATE UNIQUE INDEX "operator_steps_run_step_uidx" ON "operator_steps" USING btree ("operator_run_id","step_index");--> statement-breakpoint
CREATE INDEX "screen_observations_run_idx" ON "screen_observations" USING btree ("operator_run_id");--> statement-breakpoint
CREATE INDEX "screen_observations_hash_idx" ON "screen_observations" USING btree ("screenshot_hash");