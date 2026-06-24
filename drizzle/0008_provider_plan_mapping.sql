ALTER TABLE "billing_plan_mappings" DROP CONSTRAINT "billing_plan_mappings_plan_code_unique";--> statement-breakpoint
CREATE UNIQUE INDEX "billing_plan_mappings_provider_plan_code_unique" ON "billing_plan_mappings" USING btree ("provider","plan_code");--> statement-breakpoint
