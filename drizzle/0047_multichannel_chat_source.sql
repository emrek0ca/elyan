ALTER TYPE "public"."chat_session_source"
  ADD VALUE IF NOT EXISTS 'email';

ALTER TYPE "public"."chat_session_source"
  ADD VALUE IF NOT EXISTS 'whatsapp';
