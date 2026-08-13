-- Mükerrer öğrenme kaydını YAPISAL olarak engelle.
--
-- Bir sohbet turu birden fazla kez işlenebiliyor: sağlayıcı fallback'i işi
-- ikinci kuyruğa alıyor. Canlıda aynı taskId chat-worker-1'de iki, chat-worker-2'de
-- bir kez koştu; üçünde de persistedCount=6. Öğrenme yazımı idempotent olmadığı
-- için aynı olgu korpusa üç kez girdi.
--
-- Ölçüm (2026-08-13, üretim): task kapsamlı 1426 kaydın 494'ü mükerrer — %35.
-- Bu tablo öğrenme/eğitim korpusunun KENDİSİ olduğu için mükerrer satır yalnız
-- yer kaplamıyor; aynı olguyu birden çok kez saydırarak modeli yanıltıyor.
--
-- SIRA ÖNEMLİ: mevcut mükerrerler dururken UNIQUE index oluşmaz. Önce temizlik,
-- sonra kısıt. Temizlikte her gruptan EN YENİ satır korunur (created_at, id).
-- Beklenen silinen satır sayısı: 494 (ölçüm anındaki değer).

DELETE FROM learning_events a
USING learning_events b
WHERE a.task_id IS NOT NULL
  AND a.task_id = b.task_id
  AND a.type = b.type
  AND a.key = b.key
  AND (a.created_at, a.id) < (b.created_at, b.id);

CREATE UNIQUE INDEX IF NOT EXISTS learning_events_task_key_uidx
  ON learning_events (task_id, type, key)
  WHERE task_id IS NOT NULL;
