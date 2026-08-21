import type { SpeechAct } from "./speech-act.js";

/**
 * KONUŞMA EYLEMİ ÖLÇÜM KORPUSU.
 *
 * Amaç: "kullanıcı yapmamı mı istiyor, hakkında mı soruyor?" ayrımının gerçekten
 * çalıştığını KANITLAMAK. Bu ayrım olmadan yetenek eşleşmesi tek başına karar
 * veremiyor — ölçüldü (2026-08-22): "Chrome nedir" → close_app 0.961/marj 0.320.
 *
 * `heldout_` ile başlayan gruplar TUTULAN KÜMEdir: prototip metinleri yazarken
 * bu cümlelere BAKILMAZ. Genelleme payı (korpus − tutulan) buradan ölçülür;
 * `eval:routing` aynı ayrımda 40.6 puanlık bir uçurum gösterdi ve bütün
 * arızaların kaynağı oydu.
 *
 * Kural: bir vakayı "testi geçirmek için" etiketini değiştirerek düzeltmek
 * YASAK. İnsan da ayıramıyorsa vaka korpustan çıkarılır.
 */
export type SpeechActEvalCase = {
  utterance: string;
  expected: SpeechAct;
  group: string;
  note?: string;
};

export const SPEECH_ACT_EVAL_CASES: SpeechActEvalCase[] = [
  // --- Gerçek komutlar (canlıda doğru çalışması gerekenler) ---
  { utterance: "Terminali kapat", expected: "command", group: "command" },
  { utterance: "Chrome u kapat", expected: "command", group: "command" },
  { utterance: "Safariden youtube u aç", expected: "command", group: "command" },
  { utterance: "Masaüstünde deneme123 adında klasör oluştur", expected: "command", group: "command" },
  { utterance: "Gökhan türkmen den şarkı çal", expected: "command", group: "command" },
  { utterance: "Müslüm gürsesden bir şeyler çal", expected: "command", group: "command" },
  { utterance: "Serdar ortaçtan bir şeyler çal", expected: "command", group: "command" },
  { utterance: "Sezen aksudan bir sarki ac", expected: "command", group: "command" },
  { utterance: "ekran görüntüsü al", expected: "command", group: "command" },
  { utterance: "bu dosyayı arşive taşı", expected: "command", group: "command" },

  // --- Sorular: yetenek uzayında KOMUTLA aynı komşulukta olanlar ---
  // Bunlar canlıda yanlış yönlendirmeye yol açan sınıf. `eval:routing`
  // "aşırı özgüven" metriği de aynı vakaları sayıyor.
  { utterance: "Chrome nedir", expected: "question", group: "question_near_command" },
  { utterance: "pdf nedir açıkla", expected: "question", group: "question_near_command" },
  { utterance: "whatsapp nasıl kullanılır", expected: "question", group: "question_near_command" },
  { utterance: "Takvimime nasıl etkinlik eklerim", expected: "question", group: "question_near_command" },
  { utterance: "Bilgisayarımı nasıl hızlandırırım", expected: "question", group: "question_near_command" },
  { utterance: "anlık mesajlaşma uygulamaları güvenli mi sence", expected: "question", group: "question_near_command" },
  { utterance: "Mail nasıl yazılır", expected: "question", group: "question_near_command" },

  // --- Sıradan sorular ---
  { utterance: "Bugün hava nasıl", expected: "question", group: "question" },
  { utterance: "bugün ne yapsam", expected: "question", group: "question" },

  // --- Sohbet / bilgi verme ---
  { utterance: "Merhaba", expected: "statement", group: "statement" },
  { utterance: "Teşekkürler", expected: "statement", group: "statement" },
  { utterance: "bugün çok yorgunum", expected: "statement", group: "statement" },

  // --- Onay / ret ---
  { utterance: "evet devam et", expected: "confirmation", group: "confirmation" },
  { utterance: "iptal et", expected: "confirmation", group: "confirmation" },

  // --- Düzeltme ---
  { utterance: "hayır öyle değil, daha kısa olsun", expected: "correction", group: "correction" },
  { utterance: "bunu değil diğerini yap", expected: "correction", group: "correction" },

  // ======================= TUTULAN KÜME =======================
  // Prototip metinleri yazılırken BU CÜMLELERE BAKILMADI.
  { utterance: "spotify aç bakalım", expected: "command", group: "heldout_command" },
  { utterance: "şu pencereyi öne getir", expected: "command", group: "heldout_command" },
  { utterance: "abime whatsapptan selam yolla", expected: "command", group: "heldout_command" },
  { utterance: "perşembe öğlen için ajandama bir şey koy", expected: "command", group: "heldout_command" },
  { utterance: "bilgisayarımın şarjı ne alemde", expected: "question", group: "heldout_question" },
  { utterance: "terminal ne işe yarar", expected: "question", group: "heldout_question" },
  { utterance: "klasör oluşturmanın kısayolu var mı", expected: "question", group: "heldout_question" },
  { utterance: "spotify ücretli mi", expected: "question", group: "heldout_question" },
  { utterance: "iyi geceler", expected: "statement", group: "heldout_statement" },
  { utterance: "anladım eyvallah", expected: "statement", group: "heldout_statement" },
  { utterance: "yok böyle olmamış", expected: "correction", group: "heldout_correction" },
  { utterance: "tamam onayla", expected: "confirmation", group: "heldout_confirmation" },
];
