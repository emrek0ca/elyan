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
  "privacy_level" varchar(32) DEFAULT 'safe' NOT NULL,
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
  "last_verified_at" timestamp with time zone,
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
ALTER TABLE "brain_memory_episodes" ADD CONSTRAINT "brain_memory_episodes_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "brain_memory_episodes" ADD CONSTRAINT "brain_memory_episodes_source_task_id_tasks_id_fk" FOREIGN KEY ("source_task_id") REFERENCES "public"."tasks"("id") ON DELETE set null ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "brain_memory_facts" ADD CONSTRAINT "brain_memory_facts_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "brain_memory_links" ADD CONSTRAINT "brain_memory_links_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "brain_memory_links" ADD CONSTRAINT "brain_memory_links_source_episode_id_brain_memory_episodes_id_fk" FOREIGN KEY ("source_episode_id") REFERENCES "public"."brain_memory_episodes"("id") ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "brain_memory_links" ADD CONSTRAINT "brain_memory_links_source_fact_id_brain_memory_facts_id_fk" FOREIGN KEY ("source_fact_id") REFERENCES "public"."brain_memory_facts"("id") ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "brain_memory_links" ADD CONSTRAINT "brain_memory_links_target_episode_id_brain_memory_episodes_id_fk" FOREIGN KEY ("target_episode_id") REFERENCES "public"."brain_memory_episodes"("id") ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "brain_memory_links" ADD CONSTRAINT "brain_memory_links_target_fact_id_brain_memory_facts_id_fk" FOREIGN KEY ("target_fact_id") REFERENCES "public"."brain_memory_facts"("id") ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "brain_memory_runs" ADD CONSTRAINT "brain_memory_runs_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "brain_memory_runs" ADD CONSTRAINT "brain_memory_runs_source_training_job_id_training_jobs_id_fk" FOREIGN KEY ("source_training_job_id") REFERENCES "public"."training_jobs"("id") ON DELETE set null ON UPDATE no action;
--> statement-breakpoint
CREATE INDEX "brain_memory_episodes_user_idx" ON "brain_memory_episodes" USING btree ("user_id");
--> statement-breakpoint
CREATE INDEX "brain_memory_episodes_scope_idx" ON "brain_memory_episodes" USING btree ("scope");
--> statement-breakpoint
CREATE INDEX "brain_memory_episodes_task_idx" ON "brain_memory_episodes" USING btree ("source_task_id");
--> statement-breakpoint
CREATE INDEX "brain_memory_episodes_session_idx" ON "brain_memory_episodes" USING btree ("source_session_id");
--> statement-breakpoint
CREATE INDEX "brain_memory_episodes_stale_idx" ON "brain_memory_episodes" USING btree ("stale_at");
--> statement-breakpoint
CREATE INDEX "brain_memory_facts_user_idx" ON "brain_memory_facts" USING btree ("user_id");
--> statement-breakpoint
CREATE INDEX "brain_memory_facts_scope_idx" ON "brain_memory_facts" USING btree ("scope");
--> statement-breakpoint
CREATE INDEX "brain_memory_facts_canonical_idx" ON "brain_memory_facts" USING btree ("user_id","canonical_key");
--> statement-breakpoint
CREATE INDEX "brain_memory_facts_conflict_idx" ON "brain_memory_facts" USING btree ("conflict_status");
--> statement-breakpoint
CREATE INDEX "brain_memory_facts_stale_idx" ON "brain_memory_facts" USING btree ("stale_at");
--> statement-breakpoint
CREATE INDEX "brain_memory_facts_pinned_idx" ON "brain_memory_facts" USING btree ("is_pinned");
--> statement-breakpoint
CREATE INDEX "brain_memory_links_user_idx" ON "brain_memory_links" USING btree ("user_id");
--> statement-breakpoint
CREATE INDEX "brain_memory_links_type_idx" ON "brain_memory_links" USING btree ("link_type");
--> statement-breakpoint
CREATE INDEX "brain_memory_runs_user_idx" ON "brain_memory_runs" USING btree ("user_id");
--> statement-breakpoint
CREATE INDEX "brain_memory_runs_kind_idx" ON "brain_memory_runs" USING btree ("run_kind");
--> statement-breakpoint
CREATE INDEX "brain_memory_runs_status_idx" ON "brain_memory_runs" USING btree ("status");
--> statement-breakpoint
CREATE INDEX "brain_memory_runs_started_idx" ON "brain_memory_runs" USING btree ("started_at");
--> statement-breakpoint
ALTER TABLE "brain_memory_episodes" ADD COLUMN IF NOT EXISTS "embedding" vector(256);
--> statement-breakpoint
ALTER TABLE "brain_memory_facts" ADD COLUMN IF NOT EXISTS "embedding" vector(256);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "brain_memory_episodes_embedding_ivfflat_idx"
ON "brain_memory_episodes"
USING ivfflat ("embedding" vector_cosine_ops)
WITH (lists = 100);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "brain_memory_facts_embedding_ivfflat_idx"
ON "brain_memory_facts"
USING ivfflat ("embedding" vector_cosine_ops)
WITH (lists = 100);
