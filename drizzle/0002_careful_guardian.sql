CREATE TABLE "billing_checkout_sessions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"reference_id" varchar(160) NOT NULL,
	"user_id" uuid NOT NULL,
	"plan_code" varchar(64) NOT NULL,
	"provider" varchar(32) DEFAULT 'iyzico' NOT NULL,
	"mode" varchar(32) DEFAULT 'subscription' NOT NULL,
	"provider_token" varchar(255),
	"provider_payment_id" varchar(255),
	"provider_subscription_reference_code" varchar(160),
	"provider_customer_reference_code" varchar(160),
	"provider_pricing_plan_reference_code" varchar(160),
	"status" varchar(64) DEFAULT 'pending' NOT NULL,
	"launch_url" text,
	"payment_page_url" text,
	"callback_url" text,
	"success_url" text,
	"cancel_url" text,
	"raw_last_payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "billing_checkout_sessions_reference_id_unique" UNIQUE("reference_id")
);
--> statement-breakpoint
CREATE TABLE "billing_plan_mappings" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"provider" varchar(32) DEFAULT 'iyzico' NOT NULL,
	"plan_code" varchar(64) NOT NULL,
	"product_reference_code" varchar(160) NOT NULL,
	"pricing_plan_reference_code" varchar(160) NOT NULL,
	"product_name" varchar(160) NOT NULL,
	"pricing_plan_name" varchar(160) NOT NULL,
	"currency_code" varchar(8) NOT NULL,
	"price_minor" integer NOT NULL,
	"billing_period" varchar(16) DEFAULT 'monthly' NOT NULL,
	"synced_at" timestamp with time zone DEFAULT now() NOT NULL,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "billing_plan_mappings_plan_code_unique" UNIQUE("plan_code")
);
--> statement-breakpoint
CREATE TABLE "billing_profiles" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"full_name" varchar(160) NOT NULL,
	"email" varchar(320) NOT NULL,
	"phone" varchar(32) NOT NULL,
	"identity_number" varchar(32) NOT NULL,
	"address_line_1" varchar(255) NOT NULL,
	"city" varchar(120) NOT NULL,
	"country" varchar(120) NOT NULL,
	"zip_code" varchar(32) NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "billing_profiles_user_id_unique" UNIQUE("user_id")
);
--> statement-breakpoint
CREATE TABLE "billing_webhook_events" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"event_key" varchar(255) NOT NULL,
	"provider" varchar(32) DEFAULT 'iyzico' NOT NULL,
	"event_type" varchar(120) NOT NULL,
	"user_id" uuid,
	"checkout_reference_id" varchar(160),
	"provider_subscription_reference_code" varchar(160),
	"provider_customer_reference_code" varchar(160),
	"status" varchar(64),
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"received_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "billing_webhook_events_event_key_unique" UNIQUE("event_key")
);
--> statement-breakpoint
ALTER TABLE "subscriptions" ADD COLUMN "billing_provider" varchar(32) DEFAULT 'iyzico' NOT NULL;--> statement-breakpoint
ALTER TABLE "subscriptions" ADD COLUMN "provider_customer_reference_code" varchar(160);--> statement-breakpoint
ALTER TABLE "subscriptions" ADD COLUMN "provider_subscription_reference_code" varchar(160);--> statement-breakpoint
ALTER TABLE "subscriptions" ADD COLUMN "provider_pricing_plan_reference_code" varchar(160);--> statement-breakpoint
ALTER TABLE "subscriptions" ADD COLUMN "current_period_started_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "subscriptions" ADD COLUMN "trial_ends_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "subscriptions" ADD COLUMN "canceled_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "subscriptions" ADD COLUMN "cancel_at_period_end" boolean DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE "billing_checkout_sessions" ADD CONSTRAINT "billing_checkout_sessions_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "billing_profiles" ADD CONSTRAINT "billing_profiles_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "billing_webhook_events" ADD CONSTRAINT "billing_webhook_events_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "billing_checkout_sessions_user_idx" ON "billing_checkout_sessions" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "billing_checkout_sessions_provider_token_idx" ON "billing_checkout_sessions" USING btree ("provider_token");--> statement-breakpoint
CREATE INDEX "billing_checkout_sessions_provider_subscription_idx" ON "billing_checkout_sessions" USING btree ("provider_subscription_reference_code");--> statement-breakpoint
CREATE INDEX "billing_plan_mappings_provider_idx" ON "billing_plan_mappings" USING btree ("provider");--> statement-breakpoint
CREATE INDEX "billing_profiles_user_idx" ON "billing_profiles" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "billing_webhook_events_provider_idx" ON "billing_webhook_events" USING btree ("provider");--> statement-breakpoint
CREATE INDEX "billing_webhook_events_user_idx" ON "billing_webhook_events" USING btree ("user_id");