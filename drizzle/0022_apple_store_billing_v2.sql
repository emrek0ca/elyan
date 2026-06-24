ALTER TABLE "billing_store_transactions"
  ADD COLUMN IF NOT EXISTS "app_account_token" uuid;

WITH ranked_transactions AS (
  SELECT
    "id",
    row_number() OVER (
      PARTITION BY "provider", "original_transaction_id"
      ORDER BY "last_seen_at" DESC, "verified_at" DESC, "created_at" DESC
    ) AS row_rank
  FROM "billing_store_transactions"
  WHERE "original_transaction_id" IS NOT NULL
)
DELETE FROM "billing_store_transactions"
WHERE "id" IN (
  SELECT "id"
  FROM ranked_transactions
  WHERE row_rank > 1
);

CREATE UNIQUE INDEX IF NOT EXISTS "billing_store_transactions_provider_original_uidx"
  ON "billing_store_transactions" USING btree ("provider", "original_transaction_id")
  WHERE "original_transaction_id" IS NOT NULL;
