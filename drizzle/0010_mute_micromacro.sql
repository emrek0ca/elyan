ALTER TYPE "public"."connection_provider" ADD VALUE 'apple' BEFORE 'notion';--> statement-breakpoint
CREATE TABLE "auth_identities" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"provider" "connection_provider" NOT NULL,
	"provider_subject" varchar(160) NOT NULL,
	"email" varchar(320),
	"display_name" varchar(120),
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "billing_plan_mappings" DROP CONSTRAINT "billing_plan_mappings_plan_code_unique";--> statement-breakpoint
ALTER TABLE "training_jobs" ADD COLUMN "metadata" jsonb DEFAULT '{}'::jsonb NOT NULL;--> statement-breakpoint
ALTER TABLE "auth_identities" ADD CONSTRAINT "auth_identities_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "auth_identities_user_idx" ON "auth_identities" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "auth_identities_provider_idx" ON "auth_identities" USING btree ("provider");--> statement-breakpoint
CREATE UNIQUE INDEX "auth_identities_provider_subject_uidx" ON "auth_identities" USING btree ("provider","provider_subject");--> statement-breakpoint
CREATE UNIQUE INDEX "auth_identities_user_provider_uidx" ON "auth_identities" USING btree ("user_id","provider");--> statement-breakpoint
CREATE UNIQUE INDEX "billing_plan_mappings_provider_plan_code_unique" ON "billing_plan_mappings" USING btree ("provider","plan_code");--> statement-breakpoint
CREATE UNIQUE INDEX "usage_records_task_metric_uidx" ON "usage_records" USING btree ("task_id","metric");