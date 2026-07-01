-- Deferred plan downgrades (Claude-style): when a user on a higher paid plan
-- buys a lower tier mid-period, the lower plan is recorded here and applied
-- when the current paid period ends — paid days are never thrown away.
ALTER TABLE "subscriptions"
  ADD COLUMN IF NOT EXISTS "pending_plan_code" varchar(64);
ALTER TABLE "subscriptions"
  ADD COLUMN IF NOT EXISTS "pending_plan_effective_at" timestamp with time zone;
