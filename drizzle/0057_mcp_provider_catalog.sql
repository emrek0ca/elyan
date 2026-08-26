-- Resmî uzak MCP sunucuları için sağlayıcı değerleri.
--
-- `connection_provider` bir pgEnum; katalog girdisi eklemek bu değerlerin
-- var olmasını gerektiriyor. Ekleme ADDİTİF ve geri uyumludur: mevcut
-- satırlar etkilenmez. `IF NOT EXISTS` yeniden çalıştırmayı güvenli kılar
-- (bkz. bootstrap-v1'deki 'apple' emsali).
ALTER TYPE "public"."connection_provider" ADD VALUE IF NOT EXISTS 'sentry';
ALTER TYPE "public"."connection_provider" ADD VALUE IF NOT EXISTS 'cloudflare';
ALTER TYPE "public"."connection_provider" ADD VALUE IF NOT EXISTS 'supabase';
ALTER TYPE "public"."connection_provider" ADD VALUE IF NOT EXISTS 'vercel';
