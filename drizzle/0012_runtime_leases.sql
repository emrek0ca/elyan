ALTER TABLE "tasks" ADD COLUMN "dispatch_lease_id" varchar(120);
--> statement-breakpoint
ALTER TABLE "tasks" ADD COLUMN "dispatch_lease_issued_at" timestamp with time zone;
--> statement-breakpoint
ALTER TABLE "tasks" ADD COLUMN "dispatch_lease_expires_at" timestamp with time zone;
--> statement-breakpoint
ALTER TABLE "tasks" ADD COLUMN "dispatch_ack_at" timestamp with time zone;
--> statement-breakpoint
ALTER TABLE "tasks" ADD COLUMN "dispatch_attempt_count" integer DEFAULT 0 NOT NULL;
