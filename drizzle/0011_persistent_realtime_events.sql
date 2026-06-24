CREATE TABLE "realtime_events" (
	"id" serial PRIMARY KEY NOT NULL,
	"topic" varchar(120) NOT NULL,
	"user_id" uuid,
	"device_id" uuid,
	"task_id" uuid,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "realtime_events" ADD CONSTRAINT "realtime_events_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "realtime_events" ADD CONSTRAINT "realtime_events_device_id_devices_id_fk" FOREIGN KEY ("device_id") REFERENCES "public"."devices"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "realtime_events" ADD CONSTRAINT "realtime_events_task_id_tasks_id_fk" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "realtime_events_user_idx" ON "realtime_events" USING btree ("user_id","id");--> statement-breakpoint
CREATE INDEX "realtime_events_device_idx" ON "realtime_events" USING btree ("device_id","id");--> statement-breakpoint
CREATE INDEX "realtime_events_task_idx" ON "realtime_events" USING btree ("task_id","id");
