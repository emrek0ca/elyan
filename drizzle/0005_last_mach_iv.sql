CREATE TYPE "public"."brain_scope" AS ENUM('user', 'shared');--> statement-breakpoint
CREATE TYPE "public"."dataset_format" AS ENUM('chat_jsonl', 'instruction_jsonl', 'preference_jsonl', 'document_corpus');--> statement-breakpoint
CREATE TYPE "public"."dataset_source" AS ENUM('huggingface', 'task_feedback', 'manual_curation', 'document_import');--> statement-breakpoint
CREATE TYPE "public"."dataset_status" AS ENUM('draft', 'ready', 'archived', 'failed');--> statement-breakpoint
CREATE TYPE "public"."knowledge_document_status" AS ENUM('processing', 'ready', 'failed', 'archived');--> statement-breakpoint
CREATE TYPE "public"."knowledge_source_type" AS ENUM('manual', 'task_artifact', 'external_url', 'dataset', 'feedback');--> statement-breakpoint
CREATE TYPE "public"."model_artifact_status" AS ENUM('draft', 'ready', 'archived', 'failed');--> statement-breakpoint
CREATE TYPE "public"."training_job_kind" AS ENUM('sft', 'lora', 'dpo', 'retrieval_index');--> statement-breakpoint
CREATE TYPE "public"."training_job_status" AS ENUM('queued', 'running', 'completed', 'failed', 'canceled');--> statement-breakpoint
CREATE TABLE "dataset_manifests" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"owner_user_id" uuid,
	"scope" "brain_scope" DEFAULT 'user' NOT NULL,
	"name" varchar(160) NOT NULL,
	"source" "dataset_source" NOT NULL,
	"format" "dataset_format" NOT NULL,
	"status" "dataset_status" DEFAULT 'draft' NOT NULL,
	"description" text,
	"locator" text,
	"language_tags" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"record_count" integer DEFAULT 0 NOT NULL,
	"token_estimate" integer DEFAULT 0 NOT NULL,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "knowledge_chunks" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"document_id" uuid NOT NULL,
	"owner_user_id" uuid,
	"scope" "brain_scope" DEFAULT 'user' NOT NULL,
	"ordinal" integer NOT NULL,
	"content" text NOT NULL,
	"token_estimate" integer DEFAULT 0 NOT NULL,
	"embedding_model" varchar(160),
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "knowledge_documents" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"owner_user_id" uuid,
	"scope" "brain_scope" DEFAULT 'user' NOT NULL,
	"title" varchar(200) NOT NULL,
	"source_type" "knowledge_source_type" NOT NULL,
	"status" "knowledge_document_status" DEFAULT 'processing' NOT NULL,
	"source_uri" text,
	"content_hash" varchar(64) NOT NULL,
	"summary" text,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "model_artifacts" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"owner_user_id" uuid,
	"scope" "brain_scope" DEFAULT 'user' NOT NULL,
	"training_job_id" uuid,
	"name" varchar(160) NOT NULL,
	"provider" varchar(80) DEFAULT 'manual' NOT NULL,
	"base_model" varchar(160) NOT NULL,
	"adapter_kind" varchar(80) DEFAULT 'lora' NOT NULL,
	"status" "model_artifact_status" DEFAULT 'draft' NOT NULL,
	"storage_uri" text,
	"checksum" varchar(128),
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "training_jobs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"owner_user_id" uuid,
	"scope" "brain_scope" DEFAULT 'user' NOT NULL,
	"name" varchar(160) NOT NULL,
	"kind" "training_job_kind" NOT NULL,
	"status" "training_job_status" DEFAULT 'queued' NOT NULL,
	"base_model" varchar(160) NOT NULL,
	"dataset_manifest_id" uuid,
	"config" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"metrics" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"error" text,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "dataset_manifests" ADD CONSTRAINT "dataset_manifests_owner_user_id_users_id_fk" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "knowledge_chunks" ADD CONSTRAINT "knowledge_chunks_document_id_knowledge_documents_id_fk" FOREIGN KEY ("document_id") REFERENCES "public"."knowledge_documents"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "knowledge_chunks" ADD CONSTRAINT "knowledge_chunks_owner_user_id_users_id_fk" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "knowledge_documents" ADD CONSTRAINT "knowledge_documents_owner_user_id_users_id_fk" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_artifacts" ADD CONSTRAINT "model_artifacts_owner_user_id_users_id_fk" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_artifacts" ADD CONSTRAINT "model_artifacts_training_job_id_training_jobs_id_fk" FOREIGN KEY ("training_job_id") REFERENCES "public"."training_jobs"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "training_jobs" ADD CONSTRAINT "training_jobs_owner_user_id_users_id_fk" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "training_jobs" ADD CONSTRAINT "training_jobs_dataset_manifest_id_dataset_manifests_id_fk" FOREIGN KEY ("dataset_manifest_id") REFERENCES "public"."dataset_manifests"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "dataset_manifests_owner_idx" ON "dataset_manifests" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "dataset_manifests_scope_idx" ON "dataset_manifests" USING btree ("scope");--> statement-breakpoint
CREATE INDEX "dataset_manifests_status_idx" ON "dataset_manifests" USING btree ("status");--> statement-breakpoint
CREATE INDEX "knowledge_chunks_document_idx" ON "knowledge_chunks" USING btree ("document_id");--> statement-breakpoint
CREATE INDEX "knowledge_chunks_owner_idx" ON "knowledge_chunks" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "knowledge_chunks_scope_idx" ON "knowledge_chunks" USING btree ("scope");--> statement-breakpoint
CREATE UNIQUE INDEX "knowledge_chunks_document_ordinal_uidx" ON "knowledge_chunks" USING btree ("document_id","ordinal");--> statement-breakpoint
CREATE INDEX "knowledge_documents_owner_idx" ON "knowledge_documents" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "knowledge_documents_scope_idx" ON "knowledge_documents" USING btree ("scope");--> statement-breakpoint
CREATE INDEX "knowledge_documents_status_idx" ON "knowledge_documents" USING btree ("status");--> statement-breakpoint
CREATE UNIQUE INDEX "knowledge_documents_content_hash_uidx" ON "knowledge_documents" USING btree ("scope","owner_user_id","content_hash");--> statement-breakpoint
CREATE INDEX "model_artifacts_owner_idx" ON "model_artifacts" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "model_artifacts_scope_idx" ON "model_artifacts" USING btree ("scope");--> statement-breakpoint
CREATE INDEX "model_artifacts_status_idx" ON "model_artifacts" USING btree ("status");--> statement-breakpoint
CREATE INDEX "model_artifacts_training_job_idx" ON "model_artifacts" USING btree ("training_job_id");--> statement-breakpoint
CREATE INDEX "training_jobs_owner_idx" ON "training_jobs" USING btree ("owner_user_id");--> statement-breakpoint
CREATE INDEX "training_jobs_scope_idx" ON "training_jobs" USING btree ("scope");--> statement-breakpoint
CREATE INDEX "training_jobs_status_idx" ON "training_jobs" USING btree ("status");--> statement-breakpoint
CREATE INDEX "training_jobs_dataset_idx" ON "training_jobs" USING btree ("dataset_manifest_id");