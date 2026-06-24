CREATE TABLE "learning_events" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"account_id" uuid,
	"task_id" uuid,
	"type" varchar(64) NOT NULL,
	"key" varchar(120) NOT NULL,
	"value" text NOT NULL,
	"confidence" integer DEFAULT 50 NOT NULL,
	"scope" varchar(32) DEFAULT 'user' NOT NULL,
	"source" varchar(64) DEFAULT 'interaction' NOT NULL,
	"privacy_level" varchar(32) DEFAULT 'safe' NOT NULL,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"expires_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "learning_events" ADD CONSTRAINT "learning_events_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "learning_events" ADD CONSTRAINT "learning_events_task_id_tasks_id_fk" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "learning_events_user_idx" ON "learning_events" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "learning_events_account_idx" ON "learning_events" USING btree ("account_id");--> statement-breakpoint
CREATE INDEX "learning_events_task_idx" ON "learning_events" USING btree ("task_id");--> statement-breakpoint
CREATE INDEX "learning_events_lookup_idx" ON "learning_events" USING btree ("user_id","scope","type","key");--> statement-breakpoint
CREATE INDEX "learning_events_expires_idx" ON "learning_events" USING btree ("expires_at");