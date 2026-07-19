ALTER TABLE "users"
  ADD COLUMN IF NOT EXISTS "approval_mode" varchar(32)
  DEFAULT 'read_only_auto' NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'users_approval_mode_check'
  ) THEN
    ALTER TABLE "users"
      ADD CONSTRAINT "users_approval_mode_check"
      CHECK (
        "approval_mode" IN (
          'always_ask',
          'read_only_auto',
          'trusted_idempotent_writes'
        )
      );
  END IF;
END $$;
