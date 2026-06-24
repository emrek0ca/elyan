ALTER TABLE "audit_logs" ADD COLUMN "request_id" varchar(160);--> statement-breakpoint
ALTER TABLE "billing_checkout_sessions" ADD COLUMN "idempotency_key" varchar(160);--> statement-breakpoint
ALTER TABLE "billing_checkout_sessions" ADD COLUMN "idempotency_fingerprint" varchar(64);--> statement-breakpoint
ALTER TABLE "tasks" ADD COLUMN "runtime_connection_id" uuid;--> statement-breakpoint
ALTER TABLE "tasks" ADD COLUMN "idempotency_key" varchar(160);--> statement-breakpoint
ALTER TABLE "tasks" ADD COLUMN "idempotency_fingerprint" varchar(64);--> statement-breakpoint
ALTER TABLE "tasks" ADD CONSTRAINT "tasks_runtime_connection_id_runtime_connections_id_fk" FOREIGN KEY ("runtime_connection_id") REFERENCES "public"."runtime_connections"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "audit_logs_request_idx" ON "audit_logs" USING btree ("request_id");--> statement-breakpoint
CREATE UNIQUE INDEX "billing_checkout_user_idempotency_key_uidx" ON "billing_checkout_sessions" USING btree ("user_id","idempotency_key");--> statement-breakpoint
CREATE UNIQUE INDEX "devices_user_type_external_device_uidx" ON "devices" USING btree ("user_id","type","external_device_id");--> statement-breakpoint
CREATE UNIQUE INDEX "tasks_user_idempotency_key_uidx" ON "tasks" USING btree ("user_id","idempotency_key");