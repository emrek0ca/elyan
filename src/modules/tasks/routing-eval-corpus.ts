import type { DesktopCapabilitySideEffectClass } from "./desktop-capability-ontology.js";

// Masaüstü yönlendirme ölçüm korpusu.
//
// Amaç: bir yetenek seçimi düzeltmesinin gerçekten işe yarayıp yaramadığını
// KANITLAMAK. Prose yaması eklerken komşu bir vakayı bozup bozmadığımızı
// yalnızca bu korpus gösterir.
//
// Kurallar:
//  - `expected: null` => bu ifade için güvenli bir yetenek YOK; sistem emin
//    olmamalı (skor eşiğin altında kalmalı ya da hiç eşleşmemeli).
//  - `alsoAcceptable` => gerçekten belirsiz ifadeler; top-1 bunlardan biriyse
//    doğru sayılır. Bunu "testi geçirmek için" genişletmek yasak; yalnızca
//    insan da ayıramıyorsa kullanılır.
//  - `mustNotMatch` => bu yetenek top-3'te GÖRÜNMEMELİ. Asıl regresyon kalkanı
//    burasıdır: "close_app'i her yere seçmesin" korkusu bu alanla ölçülür.
//  - `intent` / `sideEffectLevel` bilinçli olarak çoğunlukla boş bırakıldı:
//    en zor ve en gerçekçi ayar, elimizde yalnız ham cümlenin olduğu andır.

export type RoutingEvalCase = {
  utterance: string;
  expected: string | null;
  alsoAcceptable?: string[];
  mustNotMatch?: string[];
  intent?: string | null;
  sideEffectLevel?: DesktopCapabilitySideEffectClass | null;
  group: string;
  note?: string;
};

export const ROUTING_EVAL_CORPUS: RoutingEvalCase[] = [
  // ── Uygulama kapatma vs tarayıcı denetimi (canlı hata sınıfı) ──────────
  {
    utterance: "Chrome'u kapat",
    expected: "close_app",
    mustNotMatch: ["browser_control"],
    group: "close_vs_browser",
    note: "Canlıda browser_control{action:'close_tab'} üretmişti.",
  },
  {
    utterance: "chrome u kapat",
    expected: "close_app",
    mustNotMatch: ["browser_control"],
    group: "close_vs_browser",
  },
  {
    utterance: "chrome kapansın artık",
    expected: "close_app",
    mustNotMatch: ["browser_control"],
    group: "close_vs_browser",
  },
  {
    utterance: "tarayıcıyı kapat",
    expected: "close_app",
    mustNotMatch: ["browser_control"],
    group: "close_vs_browser",
  },
  {
    utterance: "Safari'yi kapat",
    expected: "close_app",
    mustNotMatch: ["browser_control"],
    group: "close_vs_browser",
  },
  {
    utterance: "Spotify'ı kapat",
    expected: "close_app",
    mustNotMatch: ["browser_control", "play_media"],
    group: "close_vs_browser",
  },
  {
    utterance: "Notlar uygulamasını kapat",
    expected: "close_app",
    group: "close_vs_browser",
  },
  {
    utterance: "açık olan Word'ü kapat",
    expected: "close_app",
    mustNotMatch: ["document_write"],
    group: "close_vs_browser",
  },
  {
    utterance: "Chrome'u aç",
    expected: "open_app",
    alsoAcceptable: ["browser_control"],
    mustNotMatch: ["close_app"],
    group: "close_vs_browser",
    note: "Gerçekten belirsiz: uygulamayı açmak da tarayıcı denetimi de olabilir.",
  },
  {
    utterance: "Finder'ı aç",
    expected: "open_app",
    mustNotMatch: ["close_app", "browser_control"],
    group: "close_vs_browser",
  },
  {
    utterance: "bilgisayarı kapat",
    expected: null,
    mustNotMatch: ["close_app", "browser_control", "shell_run"],
    group: "close_vs_browser",
    note: "Sistemi kapatma yeteneği YOK. close_app'e düşerse yanlış iş yapar.",
  },
  {
    utterance: "ekranı kapat",
    expected: null,
    mustNotMatch: ["close_app"],
    group: "close_vs_browser",
  },
  {
    utterance: "şu pencereyi öne al",
    expected: "desktop_operator.focus_window",
    mustNotMatch: ["close_app"],
    group: "close_vs_browser",
  },
  {
    utterance: "tarayıcı oturumunu sonlandır",
    expected: "browser_session.close",
    alsoAcceptable: ["close_app"],
    group: "close_vs_browser",
  },
  {
    utterance: "Terminali kapat",
    expected: "close_app",
    mustNotMatch: ["desktop_operator.run", "shell_session_close"],
    group: "close_vs_browser",
    note: "Canlı arıza 2026-08-10 14:46 — desktop_operator.run istenmişti.",
  },
  {
    utterance: "açtığın kabuk oturumunu sonlandır",
    expected: "shell_session_close",
    mustNotMatch: ["close_app"],
    group: "close_vs_browser",
    note: "Kardeş ayrımı: uygulama değil, Elyan'ın kendi oturumu.",
  },

  // ── Tarayıcı: açma vs arama vs araştırma ──────────────────────────────
  {
    utterance: "github.com'u aç",
    expected: "browser_control",
    mustNotMatch: ["close_app", "open_app"],
    group: "browser_open_vs_search",
  },
  {
    utterance: "şu linki aç https://example.com",
    expected: "browser_control",
    mustNotMatch: ["close_app"],
    group: "browser_open_vs_search",
  },
  {
    utterance: "yeni sekme aç",
    expected: "browser_control",
    mustNotMatch: ["close_app", "web_research"],
    group: "browser_open_vs_search",
    note: "Arama DEĞİL; action='new_tab'.",
  },
  {
    utterance: "google'da hava durumu ara",
    expected: "browser_control",
    alsoAcceptable: ["get_weather", "web_research"],
    group: "browser_open_vs_search",
  },
  {
    utterance: "YouTube'da lofi çal",
    expected: "play_media",
    alsoAcceptable: ["browser_control"],
    group: "browser_open_vs_search",
  },
  {
    utterance: "kuantum bilgisayarlar hakkında kaynak topla",
    expected: "web_research",
    mustNotMatch: ["browser_control", "close_app"],
    group: "browser_open_vs_search",
  },
  {
    utterance: "bu konuyu internetten araştır ve kaynak ver",
    expected: "web_research",
    mustNotMatch: ["browser_control"],
    group: "browser_open_vs_search",
  },
  {
    utterance: "sitedeki formu doldur ve gönder",
    expected: "browser_agent.run",
    alsoAcceptable: ["browser_session.type"],
    mustNotMatch: ["browser_control"],
    group: "browser_open_vs_search",
  },
  {
    utterance: "sayfadaki tüm başlıkları çıkar",
    expected: "browser_session.extract",
    mustNotMatch: ["browser_control", "web_research"],
    group: "browser_open_vs_search",
  },
  {
    utterance: "sayfadaki giriş butonuna tıkla",
    expected: "browser_session.click",
    mustNotMatch: ["browser_control"],
    group: "browser_open_vs_search",
  },
  {
    utterance: "arama kutusuna elyan yaz ve enter'a bas",
    expected: "browser_session.type",
    mustNotMatch: ["browser_control"],
    group: "browser_open_vs_search",
  },
  {
    utterance: "bu sayfadan pdf'i indir",
    expected: "browser_session.download",
    mustNotMatch: ["document_read", "file_write"],
    group: "browser_open_vs_search",
  },

  // ── Belge üretme vs okuma vs düz dosya yazma ──────────────────────────
  {
    utterance: "masaüstüne pdf rapor hazırla",
    expected: "document_write",
    mustNotMatch: ["file_write", "document_read"],
    group: "document",
  },
  {
    utterance: "bunu word belgesi yap",
    expected: "document_write",
    mustNotMatch: ["file_write"],
    group: "document",
  },
  {
    utterance: "şu pdf'i özetle",
    expected: "document_read",
    mustNotMatch: ["document_write"],
    group: "document",
  },
  {
    utterance: "raporun içindekileri oku bana anlat",
    expected: "document_read",
    mustNotMatch: ["document_write"],
    group: "document",
  },
  {
    utterance: "sunum hazırla 10 slayt olsun",
    expected: "presentation_write",
    mustNotMatch: ["document_write"],
    group: "document",
  },
  {
    utterance: "excel tablosu oluştur",
    expected: "spreadsheet_write",
    mustNotMatch: ["document_write", "chart_generate"],
    group: "document",
  },
  {
    utterance: "xlsx olarak kaydet",
    expected: "spreadsheet_write",
    mustNotMatch: ["file_write"],
    group: "document",
  },
  {
    utterance: "notes.txt diye bir dosya oluştur içine merhaba yaz",
    expected: "file_write",
    mustNotMatch: ["document_write"],
    group: "document",
  },
  {
    utterance: "config.json'u güncelle",
    expected: "file_patch",
    alsoAcceptable: ["file_write"],
    mustNotMatch: ["document_write"],
    group: "document",
  },
  {
    utterance: "pdf nedir açıkla",
    expected: null,
    mustNotMatch: ["document_write", "document_read"],
    group: "document",
    note: "Bilgi sorusu — hiçbir masaüstü işi yok.",
  },
  {
    utterance: "word belgesi nasıl hazırlanır",
    expected: null,
    mustNotMatch: ["document_write"],
    group: "document",
  },
  {
    utterance: "taranmış faturadaki yazıyı çıkar",
    expected: "ocr_read",
    alsoAcceptable: ["document_read", "image_read"],
    group: "document",
  },
  {
    utterance: "tek sayfalık görsel afiş çıktısı üret",
    expected: "canvas_write",
    alsoAcceptable: ["document_write", "image_generate"],
    group: "document",
  },

  // ── Dosya işlemleri ───────────────────────────────────────────────────
  {
    utterance: "projede TODO geçen yerleri bul",
    expected: "file_search",
    mustNotMatch: ["file_read", "web_research"],
    group: "files",
  },
  {
    // ETİKET GÜNCELLENDİ (2026-08-23): doğru cevap artık `file_find`.
    //
    // Bu vaka `file_find` yeteneği YOKKEN yazılmıştı ve elde `file_search`ten
    // başka seçenek olmadığı için ona etiketlenmişti. Ama `file_search` dosya
    // İÇERİĞİNDE arar; "son indirdiğim dosya" sorusunu cevaplayamaz. Yetenek
    // eklendiğinde eski etiket yanlış hale geldi.
    //
    // Bu bir teste göre ayar DEĞİL: etiket, yeteneği olmayan bir sistemin
    // mecburiyetiydi; artık doğrusu mevcut.
    utterance: "son indirdiğim dosyayı bul",
    expected: "file_find",
    alsoAcceptable: ["file_search"],
    mustNotMatch: ["file_read"],
    group: "files",
  },
  {
    utterance: "package.json'u oku",
    expected: "file_read",
    mustNotMatch: ["file_write", "document_read"],
    group: "files",
  },
  {
    utterance: "bu dosyayı masaüstüne taşı",
    expected: "file_move",
    mustNotMatch: ["file_write"],
    group: "files",
  },
  {
    utterance: "dosyanın adını rapor_final yap",
    expected: "file_move",
    mustNotMatch: ["file_write", "document_write"],
    group: "files",
  },
  {
    utterance: "Masaüstünde Cabir adında klasör oluştur",
    expected: "make_directory",
    mustNotMatch: ["file_write", "directory_tree"],
    group: "files",
    note: "Canlıda test edilen ifade.",
  },
  {
    utterance: "yeni bir klasör aç adı Arşiv olsun",
    expected: "make_directory",
    mustNotMatch: ["open_app", "directory_tree"],
    group: "files",
    note: "'aç' fiili open_app'e çekmemeli.",
  },
  {
    utterance: "proje klasörünün yapısını göster",
    expected: "directory_tree",
    mustNotMatch: ["make_directory", "file_search"],
    group: "files",
  },
  {
    utterance: "indirilenler klasöründe ne var",
    expected: "directory_tree",
    alsoAcceptable: ["file_search"],
    group: "files",
  },
  {
    utterance: "şu satırı dosyada değiştir",
    expected: "file_patch",
    mustNotMatch: ["file_write"],
    group: "files",
  },

  // ── Ekran / operatör ──────────────────────────────────────────────────
  {
    utterance: "ekranda ne var",
    expected: "analyze_screen",
    alsoAcceptable: ["desktop_operator.observe_screen"],
    group: "screen",
  },
  {
    utterance: "ekran görüntüsü al",
    expected: "desktop_operator.observe_screen",
    alsoAcceptable: ["analyze_screen"],
    group: "screen",
  },
  {
    utterance: "şu anda hangi uygulama açık",
    expected: "desktop_os.active_window",
    alsoAcceptable: ["desktop_os.processes"],
    group: "screen",
  },
  {
    utterance: "açık uygulamaları listele",
    expected: "desktop_os.processes",
    mustNotMatch: ["close_app"],
    group: "screen",
  },
  {
    utterance: "ekrandaki hatayı oku ve ne olduğunu söyle",
    expected: "analyze_screen",
    mustNotMatch: ["close_app"],
    group: "screen",
  },
  {
    utterance: "ayarlardan mikrofon iznini aç",
    expected: "desktop_os.open_permission_settings",
    alsoAcceptable: ["desktop_operator.run"],
    group: "screen",
  },
  {
    utterance: "hangi izinler eksik",
    expected: "desktop_os.permissions",
    group: "screen",
  },
  {
    utterance: "şu uygulamada ayarlara gir ve bildirimleri kapat",
    expected: "desktop_operator.run",
    mustNotMatch: ["close_app"],
    group: "screen",
    note: "'kapat' burada UI içi eylem — uygulamayı kapatmak DEĞİL.",
  },
  {
    utterance: "kaydet butonuna tıkla",
    expected: "desktop_operator.execute_action",
    alsoAcceptable: ["desktop_operator.run", "desktop_operator.locate"],
    group: "screen",
  },
  {
    utterance: "otomasyonu durdur",
    expected: "desktop_operator.cancel",
    mustNotMatch: ["close_app"],
    group: "screen",
  },

  // ── Takvim / hatırlatıcı ──────────────────────────────────────────────
  {
    utterance: "yarın 14:00'e toplantı ekle",
    expected: "add_calendar_event",
    mustNotMatch: ["add_reminder"],
    group: "calendar",
  },
  {
    utterance: "bu haftaki etkinliklerim neler",
    expected: "get_calendar_events",
    mustNotMatch: ["add_calendar_event"],
    group: "calendar",
  },
  {
    utterance: "akşam süt almayı hatırlat",
    expected: "add_reminder",
    mustNotMatch: ["add_calendar_event"],
    group: "calendar",
  },
  {
    utterance: "hatırlatıcılarımı göster",
    expected: "get_reminders",
    mustNotMatch: ["add_reminder"],
    group: "calendar",
  },
  {
    utterance: "cuma günkü toplantıyı takvimden sil",
    expected: "delete_calendar_event",
    mustNotMatch: ["add_calendar_event"],
    group: "calendar",
  },
  {
    utterance: "takvim uygulaması nasıl çalışır",
    expected: null,
    mustNotMatch: ["add_calendar_event", "get_calendar_events"],
    group: "calendar",
  },

  // ── Mesajlaşma / e-posta ──────────────────────────────────────────────
  {
    utterance: "Ahmet'e whatsapp'tan geç kalacağımı yaz",
    expected: "send_whatsapp_message",
    mustNotMatch: ["email_send"],
    group: "messaging",
  },
  {
    utterance: "bu numarayı Ayşe olarak kaydet",
    expected: "save_whatsapp_contact",
    mustNotMatch: ["send_whatsapp_message", "save_memory"],
    group: "messaging",
  },
  {
    utterance: "müşteriye e-posta taslağı hazırla",
    expected: "email_draft",
    mustNotMatch: ["email_send"],
    group: "messaging",
  },
  {
    utterance: "maili gönder",
    expected: "email_send",
    mustNotMatch: ["email_draft"],
    group: "messaging",
  },
  {
    utterance: "whatsapp nasıl kullanılır",
    expected: null,
    mustNotMatch: ["send_whatsapp_message"],
    group: "messaging",
  },

  // ── Görsel / medya ────────────────────────────────────────────────────
  {
    utterance: "bana bir kedi resmi çiz",
    expected: "image_generate",
    mustNotMatch: ["image_fetch", "image_read"],
    group: "media",
  },
  {
    utterance: "bu görseldeki arka planı değiştir",
    expected: "image_edit",
    mustNotMatch: ["image_generate"],
    group: "media",
  },
  {
    utterance: "eyfel kulesinin gerçek fotoğrafını indir",
    expected: "image_fetch",
    mustNotMatch: ["image_generate"],
    group: "media",
  },
  {
    utterance: "bu fotoğrafta ne yazıyor",
    expected: "image_read",
    alsoAcceptable: ["ocr_read"],
    mustNotMatch: ["image_generate"],
    group: "media",
  },
  {
    utterance: "şu şarkıyı çal",
    expected: "play_media",
    mustNotMatch: ["browser_control", "open_app"],
    group: "media",
  },
  {
    utterance: "bu metni sesli oku",
    expected: "text_to_speech",
    mustNotMatch: ["speech_to_text"],
    group: "media",
  },
  {
    utterance: "ses kaydını yazıya dök",
    expected: "speech_to_text",
    mustNotMatch: ["text_to_speech"],
    group: "media",
  },
  {
    utterance: "mikrofonu aç kayıt başlat",
    expected: "speech_capture",
    mustNotMatch: ["open_app", "speech_to_text"],
    group: "media",
  },
  {
    utterance: "kanalımın son video performansını raporla",
    expected: "get_youtube_channel_report",
    mustNotMatch: ["web_research", "browser_control"],
    group: "media",
  },

  // ── Geliştirme: git / shell ───────────────────────────────────────────
  {
    utterance: "git durumuna bak",
    expected: "git_status",
    mustNotMatch: ["git_commit", "shell_run"],
    group: "dev",
  },
  {
    utterance: "değişiklikleri commit'le",
    expected: "git_commit",
    mustNotMatch: ["git_status"],
    group: "dev",
  },
  {
    utterance: "ne değişmiş göster",
    expected: "git_diff",
    alsoAcceptable: ["git_status"],
    group: "dev",
  },
  {
    utterance: "yeni bir branch aç",
    expected: "git_branch",
    mustNotMatch: ["open_app", "make_directory"],
    group: "dev",
    note: "'aç' fiili yine tuzak.",
  },
  {
    utterance: "npm install çalıştır",
    expected: "shell_run",
    alsoAcceptable: ["shell_session_run"],
    group: "dev",
  },
  {
    utterance: "kalıcı terminal oturumu aç",
    expected: "shell_session_open",
    mustNotMatch: ["open_app", "shell_run"],
    group: "dev",
  },
  {
    utterance: "aynı terminalde testleri koştur",
    expected: "shell_session_run",
    alsoAcceptable: ["shell_run"],
    group: "dev",
  },
  {
    utterance: "terminal oturumunu kapat",
    expected: "shell_session_close",
    mustNotMatch: ["close_app"],
    group: "dev",
  },
  {
    utterance: "git nedir",
    expected: null,
    mustNotMatch: ["git_status", "git_commit"],
    group: "dev",
  },

  // ── Veri / analiz / matematik ─────────────────────────────────────────
  {
    utterance: "şu csv'yi analiz et",
    expected: "data_analyze",
    mustNotMatch: ["chart_generate", "file_read"],
    group: "data",
  },
  {
    utterance: "bu verinin grafiğini çiz",
    expected: "chart_generate",
    mustNotMatch: ["image_generate", "data_analyze"],
    group: "data",
    note: "Kullanıcının bildirdiği hata: image_generate'e düşüyordu.",
  },
  {
    utterance: "polinomun grafiğini çiz",
    expected: "chart_generate",
    mustNotMatch: ["image_generate"],
    group: "data",
  },
  {
    utterance: "x^2 + 3x - 4 = 0 çöz",
    expected: "math_solve",
    mustNotMatch: ["chart_generate", "text_analyze"],
    group: "data",
  },
  {
    utterance: "türevini al",
    expected: "math_solve",
    mustNotMatch: ["chart_generate"],
    group: "data",
  },
  {
    utterance: "bu latex ifadesini normalize et",
    expected: "latex_parse",
    mustNotMatch: ["math_solve", "document_write"],
    group: "data",
  },
  {
    utterance: "bulguları karar odaklı özete çevir",
    expected: "text_analyze",
    mustNotMatch: ["document_write", "web_research"],
    group: "data",
  },
  {
    utterance: "bu optimizasyon problemini qubo modeline dök",
    expected: "quantum_model_problem",
    mustNotMatch: ["math_solve"],
    group: "data",
  },
  {
    utterance: "qaoa deneyini çalıştır",
    expected: "quantum_run_experiment",
    mustNotMatch: ["shell_run"],
    group: "data",
  },
  {
    utterance: "kuantum sonucunu klasikle karşılaştır",
    expected: "quantum_compare_classical",
    group: "data",
  },
  {
    utterance: "kuantum deneyi için teknik rapor üret",
    expected: "quantum_generate_report",
    alsoAcceptable: ["document_write"],
    group: "data",
  },

  // ── Sistem / hafıza / diğer ───────────────────────────────────────────
  {
    utterance: "pil yüzde kaç",
    expected: "sys_info",
    mustNotMatch: ["desktop_os.status"],
    group: "system",
  },
  {
    utterance: "diskte ne kadar yer kalmış",
    expected: "sys_info",
    group: "system",
  },
  {
    utterance: "bugün hava nasıl",
    expected: "get_weather",
    mustNotMatch: ["web_research", "browser_control"],
    group: "system",
  },
  {
    utterance: "panodaki metni oku",
    expected: "clipboard_read",
    mustNotMatch: ["clipboard_write"],
    group: "system",
  },
  {
    utterance: "bunu panoya kopyala",
    expected: "clipboard_write",
    mustNotMatch: ["clipboard_read"],
    group: "system",
  },
  {
    utterance: "kahve sevmediğimi unutma",
    expected: "save_memory",
    mustNotMatch: ["delete_memory", "save_whatsapp_contact"],
    group: "system",
  },
  {
    utterance: "hakkımdaki şu kaydı sil",
    expected: "delete_memory",
    mustNotMatch: ["save_memory"],
    group: "system",
  },
  {
    utterance: "daha önce bu konuda ne konuşmuştuk",
    expected: "retrieve_context",
    mustNotMatch: ["web_research", "file_search"],
    group: "system",
  },
  {
    utterance: "masaüstü entegrasyon durumu ne",
    expected: "desktop_os.status",
    alsoAcceptable: ["desktop_os.permissions", "sys_info"],
    group: "system",
  },

  // ── Sohbet: hiçbir masaüstü işi olmamalı ──────────────────────────────
  {
    utterance: "naber",
    expected: null,
    mustNotMatch: ["close_app", "browser_control", "shell_run", "open_app"],
    group: "chat_only",
  },
  {
    utterance: "Atatürk kimdir",
    expected: null,
    mustNotMatch: ["web_research", "close_app", "browser_control"],
    group: "chat_only",
  },
  {
    utterance: "bugün kendimi kötü hissediyorum",
    expected: null,
    mustNotMatch: ["close_app", "save_memory", "shell_run"],
    group: "chat_only",
  },
  {
    utterance: "teşekkürler kolay gelsin",
    expected: null,
    mustNotMatch: ["close_app", "browser_control", "email_send"],
    group: "chat_only",
  },
  {
    utterance: "sen neler yapabiliyorsun",
    expected: null,
    mustNotMatch: ["shell_run", "close_app", "run_skill"],
    group: "chat_only",
  },
  {
    utterance: "bir fıkra anlat",
    expected: null,
    mustNotMatch: ["web_research", "text_analyze", "close_app"],
    group: "chat_only",
  },
];

// ── TUTULAN KÜME (held-out) ────────────────────────────────────────────
//
// Yukarıdaki korpusun %77'si, yeteneklerin kullanıcı-dili sözlüğünde birebir
// geçiyor. Yani oradaki yüksek skor büyük ölçüde EZBERİ ölçer, genellemeyi
// değil. Gerçek soru şu: sistem daha önce hiç görmediği bir cümleyi doğru
// yere gönderebiliyor mu?
//
// Bu küme onun için var. Buradaki ifadeler bilinçli olarak farklı fiillerle,
// devrik cümlelerle, konuşma diliyle, yazım hatalarıyla ve araya serpilmiş
// bağlamla yazıldı. Sözlüğe ASLA kopyalanmamalıdır — kopyalandığı an ölçüm
// aleti olmaktan çıkar.
export const ROUTING_EVAL_HELDOUT: RoutingEvalCase[] = [
  {
    utterance: "şu gugıl kroma bi son ver artık",
    expected: "close_app",
    mustNotMatch: ["browser_control"],
    group: "heldout_close",
  },
  {
    utterance: "safari çalışıyor sanırım, sonlandırır mısın onu",
    expected: "close_app",
    group: "heldout_close",
  },
  {
    utterance: "müzik programından çık",
    expected: "close_app",
    mustNotMatch: ["play_media"],
    group: "heldout_close",
  },
  {
    utterance: "makineyi tamamen kapatabilir misin",
    expected: null,
    mustNotMatch: ["close_app"],
    group: "heldout_close",
  },
  {
    utterance: "not defterini çalıştırsana",
    expected: "open_app",
    mustNotMatch: ["close_app"],
    group: "heldout_open",
  },
  {
    utterance: "wikipedia sayfasına gidelim",
    expected: "browser_control",
    mustNotMatch: ["close_app"],
    group: "heldout_open",
  },
  {
    utterance: "boş bir sekmeye ihtiyacım var",
    expected: "browser_control",
    mustNotMatch: ["web_research"],
    group: "heldout_open",
  },
  {
    utterance: "şu mevzuyu bi araştırıp kaynaklarıyla getir",
    expected: "web_research",
    mustNotMatch: ["browser_control"],
    group: "heldout_open",
  },
  {
    utterance: "bilgisayarımın şarjı ne alemde",
    expected: "sys_info",
    group: "heldout_system",
  },
  {
    utterance: "hangi programlar çalışır durumda bi bakalım",
    expected: "desktop_os.processes",
    mustNotMatch: ["close_app"],
    group: "heldout_system",
  },
  {
    utterance: "dışarısı soğuk mu bugün",
    expected: "get_weather",
    mustNotMatch: ["web_research"],
    group: "heldout_system",
  },
  {
    utterance: "kopyaladığımı bi yapıştır bakayım",
    expected: "clipboard_read",
    group: "heldout_system",
  },
  {
    utterance: "raporu word formatında istiyorum",
    expected: "document_write",
    mustNotMatch: ["file_write"],
    group: "heldout_document",
  },
  {
    utterance: "bu dökümanda neler anlatılıyor bi bak",
    expected: "document_read",
    mustNotMatch: ["document_write"],
    group: "heldout_document",
  },
  {
    utterance: "verileri hesap tablosuna dökebilir misin",
    expected: "spreadsheet_write",
    mustNotMatch: ["chart_generate"],
    group: "heldout_document",
  },
  {
    utterance: "toplantı için birkaç slayt lazım",
    expected: "presentation_write",
    mustNotMatch: ["document_write"],
    group: "heldout_document",
  },
  {
    utterance: "içine şunu yazdığın basit bir txt bırak",
    expected: "file_write",
    mustNotMatch: ["document_write"],
    group: "heldout_files",
  },
  {
    utterance: "şu kelimenin geçtiği yerleri tarayabilir misin kodda",
    expected: "file_search",
    mustNotMatch: ["web_research", "file_read"],
    group: "heldout_files",
  },
  {
    utterance: "bunu başka bir yere al, arşive koy",
    expected: "file_move",
    group: "heldout_files",
  },
  {
    utterance: "orada yeni bir dizin istiyorum",
    expected: "make_directory",
    mustNotMatch: ["directory_tree", "open_app"],
    group: "heldout_files",
  },
  {
    utterance: "bu dizinin altında neler duruyor",
    expected: "directory_tree",
    mustNotMatch: ["make_directory"],
    group: "heldout_files",
  },
  {
    utterance: "monitörde şu an ne görünüyor bana anlat",
    expected: "analyze_screen",
    mustNotMatch: ["close_app"],
    group: "heldout_screen",
  },
  {
    utterance: "uygulamanın içinde gezinip şu ayarı değiştir",
    expected: "desktop_operator.run",
    mustNotMatch: ["close_app"],
    group: "heldout_screen",
  },
  {
    utterance: "o pencereyi bana getir",
    expected: "desktop_operator.focus_window",
    mustNotMatch: ["close_app"],
    group: "heldout_screen",
  },
  {
    utterance: "perşembe öğlen için ajandama bir şey koy",
    expected: "add_calendar_event",
    mustNotMatch: ["add_reminder"],
    group: "heldout_calendar",
  },
  {
    utterance: "önümüzdeki günlerde nelerim var bakar mısın",
    expected: "get_calendar_events",
    mustNotMatch: ["add_calendar_event"],
    group: "heldout_calendar",
  },
  {
    utterance: "unutmayayım, ilaç saatinde dürt beni",
    expected: "add_reminder",
    mustNotMatch: ["add_calendar_event"],
    group: "heldout_calendar",
  },
  {
    utterance: "ekibe bir yazı gönder ama önce göreyim",
    expected: "email_draft",
    mustNotMatch: ["email_send"],
    group: "heldout_messaging",
  },
  {
    utterance: "abime bi selam yolla whatsapptan",
    expected: "send_whatsapp_message",
    mustNotMatch: ["email_send"],
    group: "heldout_messaging",
  },
  {
    utterance: "depoda son ne yaptık bi özet geç",
    expected: "git_status",
    alsoAcceptable: ["git_diff"],
    group: "heldout_dev",
  },
  {
    utterance: "yaptıklarımı kayıt altına al depoya",
    expected: "git_commit",
    mustNotMatch: ["file_write"],
    group: "heldout_dev",
  },
  {
    utterance: "şu komutu bi koştur bakalım ne diyor",
    expected: "shell_run",
    alsoAcceptable: ["shell_session_run"],
    group: "heldout_dev",
  },
  {
    utterance: "elimdeki tabloyu inceleyip özet çıkarsana",
    expected: "data_analyze",
    mustNotMatch: ["chart_generate"],
    group: "heldout_data",
  },
  {
    utterance: "bunları görselleştirsek, sütunlu bir şey olsa",
    expected: "chart_generate",
    mustNotMatch: ["image_generate"],
    group: "heldout_data",
  },
  {
    utterance: "şu denklemin kökleri neymiş bul",
    expected: "math_solve",
    mustNotMatch: ["chart_generate"],
    group: "heldout_data",
  },
  {
    utterance: "elimizdekileri bi değerlendirip riskleri yaz",
    expected: "text_analyze",
    mustNotMatch: ["web_research"],
    group: "heldout_data",
  },
  {
    utterance: "hayali bir uzay gemisi görseli olsun",
    expected: "image_generate",
    mustNotMatch: ["chart_generate", "image_fetch"],
    group: "heldout_media",
  },
  {
    utterance: "bunun asıl fotoğrafını bulup indirebilir misin",
    expected: "image_fetch",
    mustNotMatch: ["image_generate"],
    group: "heldout_media",
  },
  {
    utterance: "biraz müzik olsa fena olmaz",
    expected: "play_media",
    mustNotMatch: ["open_app", "close_app"],
    group: "heldout_media",
  },
  {
    utterance: "şunu bana yüksek sesle okuyabilir misin",
    expected: "text_to_speech",
    mustNotMatch: ["speech_to_text"],
    group: "heldout_media",
  },
  {
    utterance: "sütlü kahveyi sevmediğimi bir kenara not et",
    expected: "save_memory",
    mustNotMatch: ["file_write", "add_reminder"],
    group: "heldout_memory",
  },
  {
    utterance: "geçen sefer bu konuda neye karar vermiştik",
    expected: "retrieve_context",
    mustNotMatch: ["web_research"],
    group: "heldout_memory",
  },
  // ── Sohbet: eyleme sızmamalı ──────────────────────────────────────────
  {
    utterance: "günün nasıl geçiyor",
    expected: null,
    mustNotMatch: ["close_app", "browser_control", "shell_run"],
    group: "heldout_chat",
  },
  {
    utterance: "versiyon kontrol sistemi ne işe yarar",
    expected: null,
    mustNotMatch: ["git_status", "git_commit"],
    group: "heldout_chat",
  },
  {
    utterance: "elektronik tablo programları arasındaki fark ne",
    expected: null,
    mustNotMatch: ["spreadsheet_write"],
    group: "heldout_chat",
  },
  {
    utterance: "anlık mesajlaşma uygulamaları güvenli mi sence",
    expected: null,
    mustNotMatch: ["send_whatsapp_message"],
    group: "heldout_chat",
  },
  {
    utterance: "yapay zeka gelecekte işleri elimizden alır mı",
    expected: null,
    mustNotMatch: ["web_research", "text_analyze"],
    group: "heldout_chat",
  },
  // ── 2026-08-16 eklenenler ───────────────────────────────────────────────
  // Bu turlar CANLI kod üzerinde ölçülürken toplandı. Tutulan küme yalnız
  // "hiç görülmemiş ifade" ile anlamlıdır; buraya bakıp AYAR YAPMAK ölçümü
  // öldürür. Yeni vaka eklemek serbest, eşiği/ağırlığı buna göre oynatmak
  // yasak.
  {
    utterance: "chrome'u açar mısın",
    expected: "open_app",
    mustNotMatch: ["close_app"],
    group: "heldout_open",
    note: "Canlıda top-1 close_app üretiyordu — eylem kutbu düzeltmesinin konusu.",
  },
  {
    utterance: "finder'ı aç bakalım",
    expected: "open_app",
    mustNotMatch: ["close_app"],
    group: "heldout_open",
  },
  {
    utterance: "safariyi kapatıver",
    expected: "close_app",
    mustNotMatch: ["open_app"],
    group: "heldout_close",
  },
  {
    utterance: "şu görseli üretiver bana",
    expected: "image_generate",
    group: "heldout_image",
    note: "\\büret\\b Türkçe 'ü' yüzünden hiç eşleşmiyordu.",
  },
  {
    utterance: "bir afiş üret",
    expected: "image_generate",
    group: "heldout_image",
  },
  {
    utterance: "raporunu word belgesi olarak hazırlar mısın",
    expected: "document_write",
    group: "heldout_document",
    note: "Ekli isim: \\brapor\\b 'raporunu' ile eşleşmiyordu.",
  },
  {
    utterance: "bana güzel bir belgesel öner",
    expected: null,
    mustNotMatch: ["document_write", "document_read"],
    group: "heldout_chat",
    note: "belgesel ≠ belge; ek toleransının üst sınırını koruyan vaka.",
  },
];
