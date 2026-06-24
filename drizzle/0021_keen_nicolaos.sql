ALTER TABLE "public"."ai_provider_credentials" ALTER COLUMN "provider" SET DATA TYPE text;--> statement-breakpoint
ALTER TABLE "public"."ai_provider_invocations" ALTER COLUMN "provider" SET DATA TYPE text;--> statement-breakpoint
ALTER TABLE "public"."ai_provider_invocations" ALTER COLUMN "fallback_from_provider" SET DATA TYPE text;--> statement-breakpoint
ALTER TABLE "public"."tasks" ALTER COLUMN "preferred_ai_provider" SET DATA TYPE text;--> statement-breakpoint
DROP TYPE "public"."ai_provider";--> statement-breakpoint
CREATE TYPE "public"."ai_provider" AS ENUM('groq');--> statement-breakpoint
ALTER TABLE "public"."ai_provider_credentials" ALTER COLUMN "provider" SET DATA TYPE "public"."ai_provider" USING "provider"::"public"."ai_provider";--> statement-breakpoint
ALTER TABLE "public"."ai_provider_invocations" ALTER COLUMN "provider" SET DATA TYPE "public"."ai_provider" USING "provider"::"public"."ai_provider";--> statement-breakpoint
ALTER TABLE "public"."ai_provider_invocations" ALTER COLUMN "fallback_from_provider" SET DATA TYPE "public"."ai_provider" USING "fallback_from_provider"::"public"."ai_provider";--> statement-breakpoint
ALTER TABLE "public"."tasks" ALTER COLUMN "preferred_ai_provider" SET DATA TYPE "public"."ai_provider" USING "preferred_ai_provider"::"public"."ai_provider";