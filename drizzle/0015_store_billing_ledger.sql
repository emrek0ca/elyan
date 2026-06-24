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
ALTER TABLE "billing_store_transactions" ADD CONSTRAINT "billing_store_transactions_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "billing_entitlement_events" ADD CONSTRAINT "billing_entitlement_events_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "billing_entitlement_events" ADD CONSTRAINT "billing_entitlement_events_store_transaction_id_billing_store_transactions_id_fk" FOREIGN KEY ("store_transaction_id") REFERENCES "public"."billing_store_transactions"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "billing_credit_ledger" ADD CONSTRAINT "billing_credit_ledger_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "billing_credit_ledger" ADD CONSTRAINT "billing_credit_ledger_entitlement_event_id_billing_entitlement_events_id_fk" FOREIGN KEY ("entitlement_event_id") REFERENCES "public"."billing_entitlement_events"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "billing_credit_ledger" ADD CONSTRAINT "billing_credit_ledger_task_id_tasks_id_fk" FOREIGN KEY ("task_id") REFERENCES "public"."tasks"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "billing_credit_ledger" ADD CONSTRAINT "billing_credit_ledger_ai_provider_invocation_id_ai_provider_invocations_id_fk" FOREIGN KEY ("ai_provider_invocation_id") REFERENCES "public"."ai_provider_invocations"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "billing_store_transactions_provider_idx" ON "billing_store_transactions" USING btree ("provider");--> statement-breakpoint
CREATE INDEX "billing_store_transactions_user_idx" ON "billing_store_transactions" USING btree ("user_id");--> statement-breakpoint
CREATE UNIQUE INDEX "billing_store_transactions_provider_txn_uidx" ON "billing_store_transactions" USING btree ("provider","transaction_id");--> statement-breakpoint
CREATE UNIQUE INDEX "billing_store_transactions_provider_purchase_uidx" ON "billing_store_transactions" USING btree ("provider","purchase_token");--> statement-breakpoint
CREATE INDEX "billing_store_transactions_provider_original_idx" ON "billing_store_transactions" USING btree ("provider","original_transaction_id");--> statement-breakpoint
CREATE INDEX "billing_entitlement_events_user_idx" ON "billing_entitlement_events" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "billing_entitlement_events_provider_idx" ON "billing_entitlement_events" USING btree ("source_provider");--> statement-breakpoint
CREATE UNIQUE INDEX "billing_entitlement_events_fingerprint_uidx" ON "billing_entitlement_events" USING btree ("event_fingerprint");--> statement-breakpoint
CREATE INDEX "billing_credit_ledger_user_idx" ON "billing_credit_ledger" USING btree ("user_id","created_at");--> statement-breakpoint
CREATE INDEX "billing_credit_ledger_entitlement_idx" ON "billing_credit_ledger" USING btree ("entitlement_event_id");--> statement-breakpoint
CREATE UNIQUE INDEX "billing_credit_ledger_invocation_reason_uidx" ON "billing_credit_ledger" USING btree ("ai_provider_invocation_id","reason");--> statement-breakpoint
WITH eligible_subscriptions AS (
	SELECT
		id AS subscription_id,
		user_id,
		plan_code,
		status,
		billing_provider,
		provider_subscription_reference_code,
		provider_customer_reference_code,
		current_period_started_at,
		period_ends_at,
		ai_credits_monthly
	FROM "subscriptions"
	WHERE plan_code <> 'free'
	  AND status IN ('active', 'trialing')
	  AND ai_credits_monthly > 0
), inserted_events AS (
	INSERT INTO "billing_entitlement_events" (
		"user_id",
		"source_provider",
		"plan_code",
		"event_type",
		"status",
		"source_reference_code",
		"event_fingerprint",
		"effective_period_started_at",
		"effective_period_ends_at",
		"credit_grant_amount",
		"credit_delta",
		"revoke_future_entitlement",
		"payload"
	)
	SELECT
		user_id,
		billing_provider,
		plan_code,
		'migration_backfill',
		status,
		coalesce(provider_subscription_reference_code, provider_customer_reference_code, subscription_id::text),
		md5(user_id::text || ':' || plan_code || ':' || coalesce(provider_subscription_reference_code, provider_customer_reference_code, subscription_id::text) || ':migration_backfill'),
		current_period_started_at,
		period_ends_at,
		ai_credits_monthly,
		0,
		false,
		jsonb_build_object('source', 'migration_backfill')
	FROM eligible_subscriptions
	ON CONFLICT ("event_fingerprint") DO NOTHING
	RETURNING id, user_id, credit_grant_amount
)
INSERT INTO "billing_credit_ledger" (
	"user_id",
	"entitlement_event_id",
	"reason",
	"delta_credits",
	"balance_after",
	"metadata"
)
SELECT
	user_id,
	id,
	'migration_backfill',
	credit_grant_amount,
	credit_grant_amount,
	jsonb_build_object('source', 'migration_backfill')
FROM inserted_events;
