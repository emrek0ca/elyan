// ÜRETİLEN DOSYA — ELLE DÜZENLEME.
// Kaynak: elyan-desktop runtime/capability_registry.TOOL_DECLARATIONS.
// Yeniden üretim: venv/bin/python scripts/export_capability_manifest.py <bu dosya>
// Sunucu-materyalize planlayıcı desktop'un TAM kataloğunu bu manifest'ten
// okur; onay gerektirenler desktop tarafında yine onaya takılır (güvenlik
// sınırı desktop'tadır — manifest yalnız planlama kelime dağarcığıdır).

export type DesktopCapabilityManifestEntry = {
  name: string;
  displayName: string;
  description: string;
  usage: string;
  requiredArgs: string[];
  requiresApproval: boolean;
  whenToUse: string[];
  whenNotToUse: string[];
  inputContract: Record<string, unknown>;
  outputContract: Record<string, unknown>;
  artifactContract: Record<string, unknown>;
  verificationPlan: string[];
  liveNarration: string[];
  failureModes: string[];
  fewShots: Array<Record<string, unknown>>;
  utterances: string[];
  notFor: string[];
  privacyClass: string;
  sideEffect: boolean;
  mutatesPath: boolean;
  sideEffectClass: "none" | "read" | "write" | "destructive";
  executionAuthority: "desktop" | "hybrid";
  questionSafeObservation: boolean;
  fallbackExecutionEligible: boolean;
  skillAffinity: string[];
};

export const DESKTOP_CAPABILITY_MANIFEST: DesktopCapabilityManifestEntry[] = [
  {
    "name": "add_calendar_event",
    "displayName": "Takvim etkinliği ekleme",
    "description": "Apple Calendar takvimine yeni etkinlik ekler.",
    "usage": "Takvime etkinlik eklerken. Tarihi HER ZAMAN mutlak ISO'ya çevir; belirsizse netleştir.",
    "requiredArgs": [
      "title",
      "start_iso"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "Takvime etkinlik eklerken. Tarihi HER ZAMAN mutlak ISO'ya çevir; belirsizse netleştir."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (title, start_iso) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "title",
        "start_iso"
      ],
      "properties": {
        "title": {
          "type": "STRING",
          "description": "Etkinlik başlığı."
        },
        "start_iso": {
          "type": "STRING",
          "description": "Başlangıç, ISO 8601 yerel saat: 'YYYY-MM-DDTHH:MM:SS'. Göreli ifadeyi ('yarın 14:00') mutlak tarihe çevir."
        },
        "end_iso": {
          "type": "STRING",
          "description": "Bitiş, ISO 8601. Boşsa başlangıçtan 1 saat sonrası."
        },
        "location": {
          "type": "STRING",
          "description": "Konum (varsa)."
        },
        "notes": {
          "type": "STRING",
          "description": "Ek not."
        },
        "calendar_name": {
          "type": "STRING",
          "description": "Hedef takvim adı (varsa)."
        },
        "all_day": {
          "type": "BOOLEAN",
          "description": "Tüm gün etkinliği."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "add_calendar_event",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported.",
      "Permission or approval must be verified before the side effect runs."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [
      {
        "args": {
          "title": "Diş randevusu",
          "start_iso": "2026-07-15T09:30:00"
        }
      }
    ],
    "utterances": [
      "yarın 14:00'e toplantı ekle",
      "cuma günü için takvime randevu koy",
      "takvimime etkinlik gir"
    ],
    "notFor": [
      "takvimimde ne var",
      "takvim uygulaması nasıl çalışır",
      "bana hatırlat"
    ],
    "privacyClass": "permission_gated",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "add_reminder",
    "displayName": "Hatırlatıcı ekleme",
    "description": "Apple Reminders'a yeni hatırlatıcı ekler.",
    "usage": "Hatırlatıcı/yapılacak eklerken. Tarih varsa mutlak ISO'ya çevir.",
    "requiredArgs": [
      "title"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "Hatırlatıcı/yapılacak eklerken. Tarih varsa mutlak ISO'ya çevir."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (title) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "title"
      ],
      "properties": {
        "title": {
          "type": "STRING",
          "description": "Hatırlatıcı metni."
        },
        "due_iso": {
          "type": "STRING",
          "description": "Son tarih, ISO 8601: 'YYYY-MM-DDTHH:MM:SS'. Göreli ifadeyi mutlaka çevir."
        },
        "notes": {
          "type": "STRING",
          "description": "Ek not."
        },
        "list_name": {
          "type": "STRING",
          "description": "Hedef liste adı (varsa)."
        },
        "priority": {
          "type": "STRING",
          "description": "Öncelik: 'low', 'medium', 'high'."
        },
        "all_day": {
          "type": "BOOLEAN",
          "description": "Saatsiz, gün bazlı."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "add_reminder",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported.",
      "Permission or approval must be verified before the side effect runs."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [
      {
        "args": {
          "title": "Faturayı öde",
          "due_iso": "2026-07-13T18:00:00",
          "priority": "high"
        }
      }
    ],
    "utterances": [
      "akşam süt almayı hatırlat",
      "bana yarın sabah şunu anımsat",
      "hatırlatıcı kur"
    ],
    "notFor": [
      "takvime toplantı ekle",
      "hatırlatıcılarımı göster"
    ],
    "privacyClass": "permission_gated",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "analyze_screen",
    "displayName": "Ekran analizi",
    "description": "Aktif pencereyi kullanıcı sorusuna göre görsel olarak analiz eder; basit 'ekranda ne var' cevabı üretir.",
    "usage": "Kullanıcı ekranda ne olduğunu, aktif pencerede ne yazdığını veya görünen hata/uyarıyı sorduğunda. Tıklama/yazma için desktop_operator.run.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "ekranda ne var",
      "aktif pencerede ne görünüyor",
      "bu hata ne diyor"
    ],
    "whenNotToUse": [
      "Bir hedefe tıklamak/yazmak/kaydırmak için desktop_operator.run veya execute_action kullan.",
      "Ekli görsel dosyası için image_read kullan."
    ],
    "inputContract": {
      "required": [
        "query"
      ],
      "properties": {
        "query": {
          "type": "STRING"
        },
        "target": {
          "type": "STRING",
          "enum": [
            "active_window"
          ]
        },
        "cloudAllowed": {
          "type": "BOOLEAN",
          "description": "Yalnız açık onayla bulut vision kullanımına izin verir."
        }
      },
      "additionalProperties": false,
      "target": "active_window only in v1",
      "cloudDefault": "local_only"
    },
    "outputContract": {
      "kind": "screen_analysis",
      "primary": "text",
      "fields": [
        "ownerName",
        "windowTitle",
        "analysis"
      ]
    },
    "artifactContract": {},
    "verificationPlan": [
      "Return active app/window context and visual analysis; do not hide visible third-party names from screen facts."
    ],
    "liveNarration": [
      "Ekran görüntüsü alınıyor",
      "Aktif pencere analiz ediliyor"
    ],
    "failureModes": [
      "OS_PERMISSION_REQUIRED",
      "VISION_UNAVAILABLE",
      "BLANK_CAPTURE"
    ],
    "fewShots": [],
    "utterances": [
      "ekranda ne var",
      "ekrandaki hatayı oku ve ne olduğunu söyle",
      "şu an ne görüyorsun ekranda",
      "ekranı oku",
      "aktif pencereyi analiz et",
      "visible error on screen"
    ],
    "notFor": [
      "ekranı kapat",
      "klasördeki dosyaları listele"
    ],
    "privacyClass": "local_private_screen",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "browser_agent.run",
    "displayName": "Tarayıcı ajanı",
    "description": "Tarayıcıda hedefi KENDİ gözleyip karar vererek adım adım gerçekleştiren ajan: sayfayı gözler, tıklar, yazar, veri toplar, dosya indirir; hedef bitince özet ve toplanan verileri döndürür.",
    "usage": "Sayfa yapısı önceden bilinmeyen çok adımlı tarayıcı görevlerinde TEK adım olarak kullan. Adımları kendin yazabiliyorsan browser_session.* daha hızlıdır; buradaki ajan keşif gerektiren işler içindir.",
    "requiredArgs": [
      "goal"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "Sayfa yapısı önceden bilinmeyen çok adımlı tarayıcı görevlerinde TEK adım olarak kullan. Adımları kendin yazabiliyorsan browser_session.* daha hızlıdır; buradaki ajan keşif gerektiren işler içindir."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (goal) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "goal"
      ],
      "properties": {
        "goal": {
          "type": "STRING",
          "description": "Doğal dille hedef (ör. 'YouTube kanalımdaki son 5 uzun videonun linkini topla')."
        },
        "max_turns": {
          "type": "NUMBER",
          "description": "En fazla gözlem-eylem turu (varsayılan 12, üst sınır 24)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "browser_agent.run",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported.",
      "Permission or approval must be verified before the side effect runs."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "şu sitede formu doldurup gönder",
      "şu sayfada adım adım işlemi tamamla",
      "tarayıcıda gerekli adımları kendin yap",
      "tarayıcıda adım adım yap",
      "form doldur",
      "sayfayı gez ve tamamla",
      "browser automation"
    ],
    "notFor": [],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "browser_control",
    "displayName": "Tarayıcı kontrolü",
    "description": "Tarayıcıda bir URL açar, web araması yapar, YouTube'da video açar veya yeni sekme açar.",
    "usage": "KAPATMA YAPMAZ (close/quit/close_tab action YOK — kapatmak için close_app). Yalnız açma/arama: web adresi, arama, YouTube, yeni sekme. 'Yeni sekme aç' = action='new_tab'; aramaya çevirme. Uygulama aç…",
    "requiredArgs": [
      "action"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "KAPATMA YAPMAZ (close/quit/close_tab action YOK — kapatmak için close_app). Yalnız açma/arama: web adresi, arama, YouTube, yeni sekme. 'Yeni sekme aç' = action='new_tab'; aramaya çevirme. Uygulama aç…"
    ],
    "whenNotToUse": [
      "Do not use when required inputs (action) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "action"
      ],
      "properties": {
        "action": {
          "type": "STRING",
          "description": "İşlem türü: 'open_url' (belirli adres), 'search' (web araması), 'play_youtube' (YouTube video), 'new_tab' (yeni boş sekme — ARAMA DEĞİLDİR).",
          "enum": [
            "open_url",
            "search",
            "play_youtube",
            "new_tab"
          ]
        },
        "url": {
          "type": "STRING",
          "description": "action='open_url' için açılacak tam adres (https://…)."
        },
        "query": {
          "type": "STRING",
          "description": "action='search'/'play_youtube' için arama metni."
        },
        "browser": {
          "type": "STRING",
          "description": "action='new_tab' için tarayıcı adı (chrome/safari/brave/edge; boşsa Chrome)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "browser_control",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported.",
      "Permission or approval must be verified before the side effect runs."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [
      {
        "args": {
          "action": "open_url",
          "url": "https://github.com"
        }
      },
      {
        "args": {
          "action": "search",
          "query": "hava durumu istanbul"
        }
      },
      {
        "args": {
          "action": "play_youtube",
          "query": "lo-fi çalışma müziği"
        }
      }
    ],
    "utterances": [
      "github.com'u aç",
      "şu linki açar mısın",
      "google'da uçak bileti ara",
      "yeni sekme aç",
      "tarayıcıda bu adrese git",
      "chrome'da şu sayfayı aç",
      "safaride şunu açar mısın",
      "open this website",
      "tarayıcıda aç",
      "tarayıcıdan bak"
    ],
    "notFor": [
      "chrome'u kapat",
      "tarayıcıyı kapat",
      "tarayıcı hakkında bilgi ver",
      "internet nasıl çalışır",
      "sadece web araştırması raporu yaz"
    ],
    "privacyClass": "permission_gated",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "browser_session.click",
    "displayName": "Tarayıcı oturumu — tıkla",
    "description": "Oturumdaki sayfada bir öğeye tıklar (CSS selector, görünür metin ya da rol+metin ile).",
    "usage": "browser_session.snapshot ile öğeleri gördükten sonra hedefe tıklamak.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "browser_session.snapshot ile öğeleri gördükten sonra hedefe tıklamak."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "selector": {
          "type": "STRING",
          "description": "CSS selector (en kesin yol)."
        },
        "text": {
          "type": "STRING",
          "description": "Öğenin görünür metni."
        },
        "role": {
          "type": "STRING",
          "description": "ARIA rolü (button, link, tab...)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "browser_session.click",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "sayfadaki giriş butonuna tıkla",
      "şu bağlantıya tıkla",
      "kabul et butonuna bas"
    ],
    "notFor": [],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "browser_session.close",
    "displayName": "Tarayıcı oturumu — kapat",
    "description": "Kalıcı tarayıcı oturumunu kapatır.",
    "usage": "Çok adımlı tarayıcı işi bittiğinde temizlik.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Çok adımlı tarayıcı işi bittiğinde temizlik."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {},
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "browser_session.close",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "tarayıcı oturumunu sonlandır",
      "otomasyon oturumunu kapat"
    ],
    "notFor": [
      "Terminal uygulamasını kapat",
      "uygulamayı kapat",
      "chrome'u kapat"
    ],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "none",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "browser_session.download",
    "displayName": "Tarayıcı oturumu — dosya indir",
    "description": "Sayfadan dosya indirir (indirme başlatan öğeye tıklayarak ya da doğrudan URL ile) ve dosya yolunu döndürür.",
    "usage": "Transcript/rapor/dosya indirme adımlarında; dönen outputPath sonraki file_move adımına verilir.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Transcript/rapor/dosya indirme adımlarında; dönen outputPath sonraki file_move adımına verilir."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "selector": {
          "type": "STRING",
          "description": "İndirmeyi başlatan öğenin CSS selector'ı."
        },
        "text": {
          "type": "STRING",
          "description": "İndirme öğesinin görünür metni."
        },
        "url": {
          "type": "STRING",
          "description": "Doğrudan indirme adresi."
        },
        "output_dir": {
          "type": "STRING",
          "description": "Hedef klasör (varsayılan Elyan indirmeleri)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "browser_session_download",
      "primary": "file_artifact"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "bu sayfadan pdf'i indir",
      "dosyayı siteden indir"
    ],
    "notFor": [],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "browser_session.extract",
    "displayName": "Tarayıcı oturumu — veri çıkar",
    "description": "Sayfadan yapılandırılmış veri çıkarır: selector eşleşmelerinin metni ve istenirse bir attribute'u (ör. href). Selector verilmezse sayfanın okunur metnini döndürür.",
    "usage": "Liste toplama işlerinde: video linkleri, başlıklar, tablo hücreleri. Sonuç result.items listesindedir; sonraki adımlar {{steps.<id>.result.items}} ile kullanır.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Liste toplama işlerinde: video linkleri, başlıklar, tablo hücreleri. Sonuç result.items listesindedir; sonraki adımlar {{steps.<id>.result.items}} ile kullanır."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "selector": {
          "type": "STRING",
          "description": "CSS selector (ör. 'a#video-title')."
        },
        "attribute": {
          "type": "STRING",
          "description": "Çıkarılacak attribute (ör. 'href')."
        },
        "limit": {
          "type": "NUMBER",
          "description": "En fazla öğe sayısı (varsayılan 20)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "browser_session.extract",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "sayfadaki tüm başlıkları çıkar",
      "tablodaki verileri topla",
      "listedeki linkleri al"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "none",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "browser_session.goto",
    "displayName": "Tarayıcı oturumu — sayfaya git",
    "description": "Kalıcı tarayıcı oturumunda bir adrese gider; sonraki adımlar AYNI sayfada devam eder.",
    "usage": "Çok adımlı tarayıcı işlerinde (gez → tıkla → çıkar → indir) ilk adım. Tek seferlik 'URL aç ve bırak' için browser_control kullan.",
    "requiredArgs": [
      "url"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Çok adımlı tarayıcı işlerinde (gez → tıkla → çıkar → indir) ilk adım. Tek seferlik 'URL aç ve bırak' için browser_control kullan."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (url) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "url"
      ],
      "properties": {
        "url": {
          "type": "STRING",
          "description": "Gidilecek http/https adresi."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "browser_session.goto",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "oturumda şu adrese git",
      "aynı sayfada kalarak bu adrese geç"
    ],
    "notFor": [],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "browser_session.snapshot",
    "displayName": "Tarayıcı oturumu — sayfa gözlemi",
    "description": "Sayfanın etkileşimli öğelerini (link/buton/alan, metinleriyle) listeler — sonraki tıklama/yazma adımını doğru hedefe yöneltmek için gözlem.",
    "usage": "Sayfanın yapısı bilinmiyorken tıklamadan ÖNCE gözlem almak.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Sayfanın yapısı bilinmiyorken tıklamadan ÖNCE gözlem almak."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "limit": {
          "type": "NUMBER",
          "description": "En fazla öğe (varsayılan 80)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "browser_session.snapshot",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "sayfada hangi butonlar var",
      "tıklanabilir öğeleri listele"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "none",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "browser_session.type",
    "displayName": "Tarayıcı oturumu — yaz",
    "description": "Oturumdaki sayfada bir alana metin yazar; submit=true ile Enter'a basar. Şifre alanlarına yazmaz.",
    "usage": "Arama kutusu doldurma, form alanına URL yapıştırma gibi işlerde.",
    "requiredArgs": [
      "value"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Arama kutusu doldurma, form alanına URL yapıştırma gibi işlerde."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (value) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "value"
      ],
      "properties": {
        "value": {
          "type": "STRING",
          "description": "Yazılacak metin."
        },
        "selector": {
          "type": "STRING",
          "description": "Hedef alanın CSS selector'ı."
        },
        "text": {
          "type": "STRING",
          "description": "Alanın görünür etiketi/placeholder metni."
        },
        "submit": {
          "type": "BOOLEAN",
          "description": "Yazdıktan sonra Enter'a bas."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "browser_session.type",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "arama kutusuna elyan yaz",
      "forma bu metni gir ve enter'a bas"
    ],
    "notFor": [],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "canvas_write",
    "displayName": "Görsel pano oluşturma",
    "description": "PDF/PNG canvas çıktısı üretir; metin, bölüm, tablo, grafik ve görsel bloklarını sayfalı veya tek görsel artifact'a dönüştürür.",
    "usage": "Kullanıcı PDF, tasarımlı belge, poster, rapor PDF'i veya tablo+metin+grafik birleşik çıktı istediğinde. Word için document_write, Excel için spreadsheet_write, sunum için presentation_write.",
    "requiredArgs": [
      "outputPath"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "PDF olarak ver",
      "4 sayfalık PDF hazırla",
      "metni/görseli PDF'e dönüştür",
      "tablo+grafik içeren tek çıktı üret"
    ],
    "whenNotToUse": [
      "Sadece DOCX/Word isteniyorsa document_write kullan.",
      "Yalnız tablo/xlsx isteniyorsa spreadsheet_write kullan."
    ],
    "inputContract": {
      "required": [
        "outputPath"
      ],
      "properties": {
        "prompt": {
          "type": "STRING",
          "description": "Üretilecek PDF/PNG içeriği ve tasarım talimatı."
        },
        "outputPath": {
          "type": "STRING",
          "description": "Kaydedilecek .pdf veya .png yolu."
        },
        "title": {
          "type": "STRING",
          "description": "Belgenin/görsel panonun başlığı."
        },
        "blocks": {
          "type": "ARRAY",
          "description": "Text/table/chart/image blokları; önceki adım çıktıları burada kullanılabilir."
        },
        "sections": {
          "type": "ARRAY",
          "description": "Rapor bölümleri."
        },
        "outputFormat": {
          "type": "STRING",
          "description": "pdf veya png."
        },
        "width": {
          "type": "NUMBER",
          "description": "Genişlik (px)."
        },
        "height": {
          "type": "NUMBER",
          "description": "Yükseklik (px)."
        },
        "sourceContext": {
          "type": "STRING",
          "description": "Önceki adım metni veya {{steps.<id>.output}} referansı."
        },
        "sourcePath": {
          "type": "STRING",
          "description": "Dönüştürülecek kaynak dosya."
        },
        "overwrite": {
          "type": "BOOLEAN",
          "description": "Üzerine yaz."
        }
      },
      "additionalProperties": false,
      "requiredDecision": "outputFormat must be pdf or png",
      "contentFields": [
        "prompt",
        "blocks",
        "sections",
        "sourceContext",
        "sourcePath"
      ],
      "references": "{{steps.<id>.output}} allowed"
    },
    "outputContract": {
      "kind": "canvas_write",
      "primary": "artifact",
      "formats": [
        "pdf",
        "png"
      ],
      "summaryField": "text"
    },
    "artifactContract": {
      "artifactTypes": [
        "pdf",
        "image"
      ],
      "mustIncludeOutputPath": true,
      "mobileBlocksRemainCanonical": true
    },
    "verificationPlan": [
      "Check artifact exists and extension matches requested format.",
      "If PDF was requested, verify the plan uses outputFormat=pdf or .pdf outputPath."
    ],
    "liveNarration": [
      "PDF içeriği hazırlanıyor",
      "Sayfa düzeni kuruluyor",
      "Çıktı dosyası doğrulanıyor"
    ],
    "failureModes": [
      "MISSING_CONTENT",
      "INVALID_OUTPUT_PATH",
      "DEPENDENCY_UNAVAILABLE"
    ],
    "fewShots": [
      {
        "goal": "Bunu 4 sayfalık PDF yap",
        "args": {
          "title": "Rapor",
          "outputFormat": "pdf",
          "sourceContext": "{{steps.s1.output}}"
        }
      }
    ],
    "utterances": [
      "tek sayfalık görsel afiş çıktısı üret",
      "sayfa düzenli bir png tasarım hazırla"
    ],
    "notFor": [],
    "privacyClass": "local_private_write",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "write",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": [
      "document.pdf_report",
      "canvas.visual_report"
    ]
  },
  {
    "name": "chart_generate",
    "displayName": "Grafik oluşturma",
    "description": "Veri dosyası veya yapılandırılmış veri üzerinden PNG grafik üretir.",
    "usage": "Kullanıcı grafik/plot/histogram istediğinde; önce veri okuma/analiz, sonra chart_generate, gerekirse canvas/document içine göm.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "grafik çiz",
      "veriden chart üret",
      "Excel verisini görselleştir"
    ],
    "whenNotToUse": [
      "Sadece tablo için spreadsheet_write kullan.",
      "Grafikli PDF için chart_generate sonrası canvas_write kullan."
    ],
    "inputContract": {
      "required": [
        "path"
      ],
      "properties": {
        "path": {
          "type": "STRING"
        },
        "chartType": {
          "type": "STRING"
        },
        "xColumn": {
          "type": "STRING"
        },
        "yColumn": {
          "type": "STRING"
        },
        "title": {
          "type": "STRING"
        },
        "outputPath": {
          "type": "STRING"
        },
        "sourceContext": {
          "type": "STRING"
        }
      },
      "additionalProperties": false,
      "dataSourceRequired": "path or sourceContext",
      "chartTypeRecommended": true
    },
    "outputContract": {
      "kind": "chart_generate",
      "primary": "image_artifact",
      "formats": [
        "png"
      ]
    },
    "artifactContract": {
      "artifactTypes": [
        "image"
      ],
      "extension": ".png"
    },
    "verificationPlan": [
      "Check PNG artifact exists and chart type/data mapping is explicit."
    ],
    "liveNarration": [
      "Grafik verisi hazırlanıyor",
      "Grafik çiziliyor"
    ],
    "failureModes": [
      "MISSING_DATA",
      "INVALID_COLUMNS",
      "DEPENDENCY_UNAVAILABLE"
    ],
    "fewShots": [
      {
        "args": {
          "path": "/Users/x/veri.csv",
          "chartType": "bar",
          "xColumn": "ay",
          "yColumn": "gelir"
        }
      }
    ],
    "utterances": [
      "bu verinin grafiğini çiz",
      "polinomun grafiğini çiz",
      "sonuçları grafiğe dök",
      "bar chart oluştur"
    ],
    "notFor": [
      "bana bir manzara resmi çiz",
      "grafik nedir açıkla",
      "veriyi analiz et yorumla"
    ],
    "privacyClass": "local_private_write",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "write",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "clipboard_read",
    "displayName": "Panoyu okuma",
    "description": "Panodaki (clipboard) metni okur.",
    "usage": "Kullanıcı 'panodakini/kopyaladığımı' işleme dediğinde.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Kullanıcı 'panodakini/kopyaladığımı' işleme dediğinde."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "query": {
          "type": "STRING",
          "description": "İsteğe bağlı bağlam/filtre."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "clipboard_read",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "panodaki metni oku",
      "kopyaladığım şey neydi",
      "panoda ne var"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "clipboard_write",
    "displayName": "Panoya yazma",
    "description": "Verilen metni panoya (clipboard) kopyalar.",
    "usage": "Bir sonucu/metni kullanıcının yapıştırabilmesi için panoya koymak.",
    "requiredArgs": [
      "text"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Bir sonucu/metni kullanıcının yapıştırabilmesi için panoya koymak."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (text) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "text"
      ],
      "properties": {
        "text": {
          "type": "STRING",
          "description": "Panoya kopyalanacak metin."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "clipboard_write",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "bunu panoya kopyala",
      "şu metni kopyala da yapıştırayım"
    ],
    "notFor": [],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "close_app",
    "displayName": "Uygulama kapatma",
    "description": "Açık uygulamayı kapatır.",
    "usage": "Kullanıcı bir uygulamayı kapatmak istediğinde.",
    "requiredArgs": [
      "app_name"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "chrome'u kapat",
      "terminali kapat",
      "şu uygulamadan çık"
    ],
    "whenNotToUse": [
      "Kaydedilmemiş iş olabilecek durumlarda önce kullanıcıya sor.",
      "Terminal OTURUMUNU bırakmak için shell_session_close kullan."
    ],
    "inputContract": {
      "required": [
        "app_name"
      ],
      "properties": {
        "app_name": {
          "type": "STRING"
        }
      },
      "additionalProperties": false,
      "appNameMustBeConcrete": true
    },
    "outputContract": {
      "kind": "close_app",
      "primary": "closed_app"
    },
    "artifactContract": {},
    "verificationPlan": [
      "The app must no longer be running afterwards."
    ],
    "liveNarration": [
      "Uygulama kapatılıyor"
    ],
    "failureModes": [
      "APP_NOT_RUNNING",
      "PERMISSION_REQUIRED",
      "CLOSE_REFUSED"
    ],
    "fewShots": [
      {
        "args": {
          "app_name": "Spotify"
        }
      }
    ],
    "utterances": [
      "Chrome'u kapat",
      "chrome kapansın artık",
      "tarayıcıyı kapat",
      "Spotify'ı kapat",
      "açık olan Word'ü kapat",
      "şu uygulamadan çık",
      "Terminali kapat",
      "Finder'ı kapat",
      "quit the app",
      "uygulama kapat"
    ],
    "notFor": [
      "bilgisayarı kapat",
      "ekranı kapat",
      "sistemi kapat",
      "uygulama nasıl kapatılır",
      "ayarlardaki bildirimleri kapat"
    ],
    "privacyClass": "permission_gated",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "data_analyze",
    "displayName": "Veri analizi",
    "description": "CSV, JSON veya Excel verisini yerel olarak analiz eder (özet/profil/önizleme).",
    "usage": "Bir veri dosyasını anlamak/özetlemek için. Grafik çizmek için chart_generate.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Bir veri dosyasını anlamak/özetlemek için. Grafik çizmek için chart_generate."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (path) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "path"
      ],
      "properties": {
        "path": {
          "type": "STRING",
          "description": "Veri dosyası yolu (.csv/.json/.xlsx/.xls)."
        },
        "mode": {
          "type": "STRING",
          "description": "'summary', 'profile' veya 'preview'.",
          "enum": [
            "summary",
            "profile",
            "preview"
          ]
        },
        "columns": {
          "type": "ARRAY",
          "description": "Odaklanılacak sütun adları (varsa)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "data_analyze",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "şu csv'yi analiz et",
      "excel verisinin özetini çıkar",
      "veri setini profille"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "delete_calendar_event",
    "displayName": "Takvim etkinliği silme",
    "description": "Apple Calendar takviminden etkinlik siler (geri alınamaz — onay gerekir).",
    "usage": "Etkinlik silmek için. Yanlış silmemek için start_iso ile daralt.",
    "requiredArgs": [
      "title"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "Etkinlik silmek için. Yanlış silmemek için start_iso ile daralt."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (title) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "title"
      ],
      "properties": {
        "title": {
          "type": "STRING",
          "description": "Silinecek etkinliğin başlığı."
        },
        "start_iso": {
          "type": "STRING",
          "description": "Etkinliğin başlangıcı (ISO) — doğru eşleşme için."
        },
        "calendar_name": {
          "type": "STRING",
          "description": "Takvim adı (varsa)."
        },
        "delete_all_matches": {
          "type": "BOOLEAN",
          "description": "Aynı başlıklı tüm etkinlikleri sil."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "delete_calendar_event",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported.",
      "Permission or approval must be verified before the side effect runs."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "cuma günkü toplantıyı takvimden sil",
      "o etkinliği iptal et takvimden kaldır"
    ],
    "notFor": [],
    "privacyClass": "permission_gated",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "destructive",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "delete_memory",
    "displayName": "Hafızadan silme",
    "description": "Kalıcı hafızadan bir kaydı siler.",
    "usage": "Kullanıcı 'şunu unut/hatırlama' dediğinde.",
    "requiredArgs": [],
    "requiresApproval": true,
    "whenToUse": [
      "Kullanıcı 'şunu unut/hatırlama' dediğinde."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "category": {
          "type": "STRING",
          "description": "Kategori (varsa)."
        },
        "key": {
          "type": "STRING",
          "description": "Silinecek kaydın anahtarı."
        },
        "match_text": {
          "type": "STRING",
          "description": "Anahtar yoksa içerikle eşleştir."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "delete_memory",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported.",
      "Permission or approval must be verified before the side effect runs."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "hakkımdaki şu kaydı sil",
      "o bilgiyi hafızandan çıkar"
    ],
    "notFor": [
      "o klasörü sil",
      "bu dosyayı sil",
      "masaüstündeki klasörü sil",
      "şunu çöpe at",
      "unutmayayım, şunu hatırlat"
    ],
    "privacyClass": "local_private_write",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "destructive",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "desktop_operator.cancel",
    "displayName": "Otomasyonu iptal",
    "description": "Aktif ekran otomasyonu çalışmasını güvenli şekilde durdurur.",
    "usage": "Takılan/istenmeyen bir operator çalışmasını durdurmak için.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Takılan/istenmeyen bir operator çalışmasını durdurmak için."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "runId": {
          "type": "STRING",
          "description": "Durdurulacak çalışma kimliği (varsa)."
        },
        "reason": {
          "type": "STRING",
          "description": "İptal nedeni."
        },
        "source": {
          "type": "STRING",
          "description": "İptali başlatan kaynak."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "desktop_operator.cancel",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "otomasyonu durdur",
      "yaptığın işlemi iptal et"
    ],
    "notFor": [],
    "privacyClass": "local_session_control",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "desktop_operator.execute_action",
    "displayName": "Ekran eylemi",
    "description": "Gözlemlenmiş ekranda tek bir güvenli click/type/key/scroll eylemi uygular.",
    "usage": "Önce observe_screen ile hedef görüldüyse tek UI eylemi için. Belirsiz/çok adımlı UI hedefinde desktop_operator.run kullan.",
    "requiredArgs": [
      "actionType"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "görünen butona tıkla",
      "alana şu metni yaz",
      "enter'a bas",
      "sayfayı kaydır"
    ],
    "whenNotToUse": [
      "Hedef belirsiz veya çok adımlıysa desktop_operator.run kullan.",
      "Web DOM erişimi varsa browser_session/browser_agent daha güvenilir olabilir."
    ],
    "inputContract": {
      "required": [
        "actionType"
      ],
      "properties": {
        "actionType": {
          "type": "STRING",
          "enum": [
            "click",
            "double_click",
            "right_click",
            "drag",
            "type_text",
            "hotkey",
            "scroll",
            "wait",
            "focus_window"
          ]
        },
        "targetText": {
          "type": "STRING"
        },
        "elementType": {
          "type": "STRING"
        },
        "bbox": {
          "type": "OBJECT"
        },
        "text": {
          "type": "STRING"
        },
        "keys": {
          "type": "ARRAY"
        },
        "delta": {
          "type": "NUMBER",
          "description": "Kaydırma miktarı."
        },
        "duration": {
          "type": "NUMBER",
          "description": "Süre (sn)."
        },
        "appName": {
          "type": "STRING",
          "description": "Hedef uygulama."
        },
        "reason": {
          "type": "STRING"
        }
      },
      "additionalProperties": false,
      "targetOrReasonRequired": true,
      "mustDependOnObservation": true
    },
    "outputContract": {
      "kind": "desktop_operator_action",
      "primary": "action_result"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Follow with observe_screen for important state changes."
    ],
    "liveNarration": [
      "Ekranda güvenli eylem uygulanıyor"
    ],
    "failureModes": [
      "TARGET_NOT_FOUND",
      "OS_PERMISSION_REQUIRED",
      "ACTION_BLOCKED"
    ],
    "fewShots": [],
    "utterances": [
      "kaydet butonuna tıkla",
      "şu alana yaz",
      "aşağı kaydır"
    ],
    "notFor": [],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "desktop_operator.focus_window",
    "displayName": "Pencere odaklama",
    "description": "Bir masaüstü uygulamasını öne alır.",
    "usage": "Bir uygulamayı öne getirmek için. Uygulamayı açmak için open_app.",
    "requiredArgs": [],
    "requiresApproval": true,
    "whenToUse": [
      "Bir uygulamayı öne getirmek için. Uygulamayı açmak için open_app."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "appName": {
          "type": "STRING",
          "description": "Öne alınacak uygulama adı."
        },
        "bundleId": {
          "type": "STRING",
          "description": "Uygulama bundle kimliği (varsa)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "desktop_operator.focus_window",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported.",
      "Permission or approval must be verified before the side effect runs."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "şu pencereyi öne al",
      "o uygulamaya geç"
    ],
    "notFor": [],
    "privacyClass": "permission_gated",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "desktop_operator.locate",
    "displayName": "Ekranda konum bulma",
    "description": "EKRAN konumlandırıcısı: görünen bir öğenin ekran koordinatını (x/y) döndürür. Dosya ya da klasör YOLU döndürmez, dosya sistemi aramaz.",
    "usage": "Yalnız ekran otomasyonunun alt adımı (genelde desktop_operator.run içinde). Yol çözücü DEĞİLDİR: çıktısı sonraki adıma 'path' olarak verilemez. Klasör açmak için tek başına make_directory yeterlidir.",
    "requiredArgs": [],
    "requiresApproval": true,
    "whenToUse": [
      "Yalnız ekran otomasyonunun alt adımı (genelde desktop_operator.run içinde). Yol çözücü DEĞİLDİR: çıktısı sonraki adıma 'path' olarak verilemez. Klasör açmak için tek başına make_directory yeterlidir."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "text": {
          "type": "STRING",
          "description": "Aranan görünür metin."
        },
        "elementType": {
          "type": "STRING",
          "description": "Öğe tipi, örn. 'button', 'field'."
        },
        "imagePath": {
          "type": "STRING",
          "description": "Ekranda aranacak template görsel yolu."
        },
        "threshold": {
          "type": "NUMBER",
          "description": "Template eşleşme eşiği; varsayılan 0.86."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "desktop_operator.locate",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported.",
      "Permission or approval must be verified before the side effect runs."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "ekranda şu butonu bul",
      "o yazı ekranın neresinde"
    ],
    "notFor": [],
    "privacyClass": "local_private_screen",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "desktop_operator.observe_screen",
    "displayName": "Ekran gözlemi",
    "description": "Operator için yapılandırılmış ekran gözlemi üretir; sonraki UI eylemini güvenli seçmek için kullanılır.",
    "usage": "Ekran-eylem planında her kritik tıklama/yazma öncesi ve sonrası durum görmek için.",
    "requiredArgs": [],
    "requiresApproval": true,
    "whenToUse": [
      "UI görevinin mevcut durumunu gözle",
      "buton/alan görünür mü kontrol et",
      "eylem sonrası doğrula"
    ],
    "whenNotToUse": [
      "Kullanıcı sadece genel açıklama istiyorsa analyze_screen kullan.",
      "Tek dosya/görsel için image_read kullan."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "query": {
          "type": "STRING"
        },
        "target": {
          "type": "STRING",
          "enum": [
            "active_window"
          ]
        },
        "preserveScreenshot": {
          "type": "BOOLEAN"
        }
      },
      "additionalProperties": false,
      "queryRecommended": true,
      "preserveScreenshotOnlyWhenNeeded": true
    },
    "outputContract": {
      "kind": "screen_observation",
      "primary": "observation"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Observation should include active app/window, visible text/elements when available."
    ],
    "liveNarration": [
      "Ekran durumu gözlemleniyor"
    ],
    "failureModes": [
      "OS_PERMISSION_REQUIRED",
      "NO_ACTIVE_WINDOW"
    ],
    "fewShots": [],
    "utterances": [
      "ekran görüntüsü al",
      "ekranı gözlemle",
      "screenshot al"
    ],
    "notFor": [],
    "privacyClass": "local_private_screen",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "desktop_operator.run",
    "displayName": "Ekran otomasyonu",
    "description": "Çok adımlı observe→decide→act→verify ekran otomasyonu hedefini yürütür.",
    "usage": "Yerel uygulama veya belirsiz UI üzerinde ardışık tıklama/yazma/kaydırma gerektiğinde; stop condition içeren somut goal ver.",
    "requiredArgs": [
      "goal"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "ekrandaki formu doldur",
      "uygulamada şu ayarı bul ve aç",
      "butonları izleyerek işlemi tamamla"
    ],
    "whenNotToUse": [
      "Sadece ekranı anlatmak için analyze_screen kullan.",
      "Bilinen browser DOM işlerinde browser_session/browser_agent daha uygundur."
    ],
    "inputContract": {
      "required": [
        "goal"
      ],
      "properties": {
        "goal": {
          "type": "STRING"
        },
        "action": {
          "type": "STRING",
          "description": "Tek eylem kısayolu (varsa)."
        },
        "targetText": {
          "type": "STRING",
          "description": "Hedef öğe metni (varsa)."
        },
        "elementType": {
          "type": "STRING",
          "description": "Öğe tipi (varsa)."
        },
        "text": {
          "type": "STRING",
          "description": "Yazılacak metin (varsa)."
        },
        "appName": {
          "type": "STRING"
        },
        "steps": {
          "type": "ARRAY"
        },
        "maxActions": {
          "type": "NUMBER"
        }
      },
      "additionalProperties": false,
      "goalMustIncludeStopCondition": true,
      "maxActionsRecommended": true
    },
    "outputContract": {
      "kind": "desktop_operator_run",
      "primary": "run_summary"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Operator loop must stop on success, uncertainty, or maxActions.",
      "Important final state must be observed before success."
    ],
    "liveNarration": [
      "Ekran görevi başlatılıyor",
      "Her adımdan sonra durum kontrol ediliyor",
      "Son durum doğrulanıyor"
    ],
    "failureModes": [
      "MAX_ACTIONS_REACHED",
      "TARGET_NOT_FOUND",
      "OS_PERMISSION_REQUIRED",
      "UNSAFE_ACTION"
    ],
    "fewShots": [
      {
        "args": {
          "goal": "System Settings'te karanlık modu aç",
          "appName": "System Settings"
        }
      }
    ],
    "utterances": [
      "şu uygulamada ayarlara gir ve bildirimleri kapat",
      "bilgisayarda bu işi adım adım yap",
      "uygulamada gerekli tıklamaları yaparak tamamla",
      "masaüstünde işi yap",
      "tıkla yaz kaydır",
      "bilgisayarda uygula",
      "computer control"
    ],
    "notFor": [
      "masaüstü uygulamaları hakkında tavsiye ver",
      "bilgisayarda yapmadan planla",
      "uygulamayı kapat"
    ],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "desktop_os.active_window",
    "displayName": "Aktif pencere",
    "description": "Şu an öndeki (aktif) pencere bilgisini döndürür.",
    "usage": "Kullanıcının o an hangi uygulamada olduğunu öğrenmek için.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Kullanıcının o an hangi uygulamada olduğunu öğrenmek için."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {},
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "desktop_os.active_window",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "şu anda hangi uygulama önde",
      "aktif pencere hangisi",
      "hangi ekrandayım"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "none",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "desktop_os.open_permission_settings",
    "displayName": "İzin ayarlarını açma",
    "description": "İlgili sistem izin ekranını güvenli şekilde açar.",
    "usage": "Bir izin eksikse kullanıcıyı doğru sistem ayar ekranına yönlendirmek için.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Bir izin eksikse kullanıcıyı doğru sistem ayar ekranına yönlendirmek için."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "permission": {
          "type": "STRING",
          "description": "Açılacak izin türü, örn. 'accessibility', 'screen'."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "desktop_os.open_permission_settings",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "ayarlardan ekran kaydı iznini aç",
      "sistem izin ekranını aç",
      "erişilebilirlik ayarlarına götür beni"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "none",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "desktop_os.permissions",
    "displayName": "İzin durumu",
    "description": "Masaüstü izin modelini ve izin hazırlık (readiness) durumunu döndürür.",
    "usage": "Hangi sistem izinlerinin verildiğini görmek için. İzin ekranını açmak için desktop_os.open_permission_settings.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Hangi sistem izinlerinin verildiğini görmek için. İzin ekranını açmak için desktop_os.open_permission_settings."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {},
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "desktop_os.permissions",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "hangi izinler eksik",
      "erişim izinleri tamam mı",
      "izin durumunu kontrol et"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "desktop_os.processes",
    "displayName": "Çalışan uygulamalar",
    "description": "Çalışan uygulamaları/prosesleri güvenli şekilde listeler.",
    "usage": "Hangi uygulamaların açık olduğunu görmek için. Genel sistem bilgisi için sys_info.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Hangi uygulamaların açık olduğunu görmek için. Genel sistem bilgisi için sys_info."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "query": {
          "type": "STRING",
          "description": "Filtre/arama (varsa)."
        },
        "limit": {
          "type": "NUMBER",
          "description": "En fazla sonuç."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "desktop_os.processes",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "açık uygulamaları listele",
      "arka planda neler çalışıyor",
      "hangi programlar açık şu an"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "none",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "desktop_os.status",
    "displayName": "Masaüstü durumu",
    "description": "Masaüstü OS yetenek ve native entegrasyon durumunu döndürür.",
    "usage": "Masaüstünün hangi yeteneklerinin hazır olduğunu kontrol ederken (tanılama).",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Masaüstünün hangi yeteneklerinin hazır olduğunu kontrol ederken (tanılama)."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {},
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "desktop_os.status",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "masaüstü entegrasyonu çalışıyor mu",
      "yerel yetenekler hazır mı"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "desktop_os.volume",
    "displayName": "Ses kontrolü",
    "description": "Sistem ses seviyesini okur, ayarlar veya sessize alır.",
    "usage": "Kullanıcı sesi kapat/aç, kıs/yükselt ya da ses seviyesini sorduğunda. Medya oynatmak için play_media.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Kullanıcı sesi kapat/aç, kıs/yükselt ya da ses seviyesini sorduğunda. Medya oynatmak için play_media."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "action": {
          "type": "STRING",
          "description": "get | set | mute | unmute | toggle"
        },
        "level": {
          "type": "NUMBER",
          "description": "0-100 arası ses seviyesi (yalnız action=set)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "desktop_os.volume",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "bilgisayarın sesini kapat",
      "sesi aç",
      "sesi kıs",
      "ses seviyesini yüzde otuz yap",
      "sessize al"
    ],
    "notFor": [],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "directory_tree",
    "displayName": "Klasör ağacı",
    "description": "Klasör/proje yapısını güvenli, sınırlı ağaç olarak listeler.",
    "usage": "Klasörde ne var, proje yapısı nasıl, hangi dosyalar mevcut sorularında.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "klasörü listele",
      "proje ağacını çıkar",
      "dosya yapısını göster"
    ],
    "whenNotToUse": [
      "İçerik aramak için file_search kullan.",
      "Belge metni okumak için document_read/file_read kullan."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "path": {
          "type": "STRING"
        },
        "max_depth": {
          "type": "NUMBER"
        },
        "max_entries": {
          "type": "NUMBER"
        }
      },
      "additionalProperties": false,
      "defaults": {
        "path": "workspace",
        "max_depth": 3
      }
    },
    "outputContract": {
      "kind": "directory_tree",
      "primary": "tree"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Tree must include scoped root and bounded entries."
    ],
    "liveNarration": [
      "Klasör yapısı çıkarılıyor"
    ],
    "failureModes": [
      "PATH_BLOCKED",
      "TOO_MANY_ENTRIES"
    ],
    "fewShots": [],
    "utterances": [
      "proje klasörünün yapısını göster",
      "indirilenler klasöründe ne var",
      "bu dizindeki dosyaları listele",
      "masaüstünde hangi dosyalar var",
      "klasör ağacı",
      "klasörleri listele",
      "dosya yapısını göster"
    ],
    "notFor": [
      "yeni klasör oluştur",
      "dosya içeriğinde metin ara"
    ],
    "privacyClass": "local_private_read",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "document_read",
    "displayName": "Belge okuma",
    "description": "PDF, DOCX, PPTX ve desteklenen belgelerden metin/özet çıkarır.",
    "usage": "Kullanıcının verdiği belgeyi okumadan analiz/yazım yapma. PDF içeriği okunacaksa önce document_read, PDF üretilecekse canvas_write.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "bu dosyayı oku",
      "PDF'i özetle",
      "belgedeki bilgiden rapor hazırla"
    ],
    "whenNotToUse": [
      "Düz .txt/.py dosyaları için file_read kullan.",
      "Ekrandaki metni okumak için analyze_screen kullan."
    ],
    "inputContract": {
      "required": [
        "path"
      ],
      "properties": {
        "path": {
          "type": "STRING"
        },
        "text": {
          "type": "STRING",
          "description": "Doğrudan metin verilecekse (path yerine)."
        },
        "mode": {
          "type": "STRING"
        },
        "max_chars": {
          "type": "NUMBER"
        }
      },
      "additionalProperties": false,
      "selectedPathsAllowed": true
    },
    "outputContract": {
      "kind": "document_read",
      "primary": "text",
      "fields": [
        "text",
        "pages",
        "summary"
      ]
    },
    "artifactContract": {},
    "verificationPlan": [
      "Ensure extracted text or structured page summary is non-empty."
    ],
    "liveNarration": [
      "Belge okunuyor",
      "Metin çıkarılıyor"
    ],
    "failureModes": [
      "FILE_NOT_FOUND",
      "UNSUPPORTED_FORMAT",
      "EMPTY_DOCUMENT"
    ],
    "fewShots": [],
    "utterances": [
      "şu pdf'i özetle",
      "raporun içindekileri oku bana anlat",
      "bu docx'te ne yazıyor",
      "belge oku",
      "pdf oku",
      "docx oku",
      "dosyayı özetle"
    ],
    "notFor": [
      "pdf raporu oluştur",
      "belge nasıl okunur anlat",
      "sayfadan dosya indir"
    ],
    "privacyClass": "local_private_read",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "document_write",
    "displayName": "Belge oluşturma",
    "description": "Verilen HAZIR metni DOCX/Word veya sade PDF dosyasına yazar. İçerik ÜRETMEZ — ne verilirse dosyada o görünür.",
    "usage": "HAZIR metni Word/DOCX veya sade PDF dosyasına dökmek için. Metin yoksa ÖNCE onu üreten bir adım gerekir; bu araç yazmaz, sadece kaydeder. Tasarımlı canvas PDF için canvas_write, Excel için spreadshee…",
    "requiredArgs": [],
    "requiresApproval": true,
    "whenToUse": [
      "hazırlanan metni docx olarak kaydet",
      "okunan metni Word belgesi yap",
      "üretilen dilekçeyi dosyaya yaz"
    ],
    "whenNotToUse": [
      "Görsel tasarımlı PDF isteniyorsa canvas_write kullan.",
      "Sunum/slayt isteniyorsa presentation_write kullan.",
      "Tablo/xlsx isteniyorsa spreadsheet_write kullan."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "prompt": {
          "type": "STRING",
          "description": "Belgeye YAZILACAK hazır metin. Konu/talimat DEĞİL. Metin henüz yoksa önce üreten adımı koy ve {{steps.<id>.output}} ver."
        },
        "outputPath": {
          "type": "STRING",
          "description": "Kaydedilecek .docx veya .pdf yolu."
        },
        "outputFormat": {
          "type": "STRING",
          "description": "docx veya pdf."
        },
        "title": {
          "type": "STRING",
          "description": "Belge başlığı."
        },
        "sections": {
          "type": "ARRAY",
          "description": "Başlık ve gövdeden oluşan bölümler."
        },
        "blocks": {
          "type": "ARRAY",
          "description": "Text/table/chart/image blokları."
        },
        "sourcePath": {
          "type": "STRING",
          "description": "Dönüştürülecek/özetlenecek kaynak belge."
        },
        "sourceContext": {
          "type": "STRING",
          "description": "Önceki adım çıktısı veya kullanıcı metni."
        },
        "overwrite": {
          "type": "BOOLEAN",
          "description": "Var olan dosyanın üzerine yaz."
        }
      },
      "additionalProperties": false,
      "contentFields": [
        "prompt",
        "sections",
        "blocks",
        "sourceContext",
        "sourcePath"
      ],
      "contentIsWrittenVerbatim": "prompt/sections/blocks are written to the file AS-IS; this tool never expands a topic into prose",
      "formatDecision": "outputFormat/outputPath extension chooses docx or pdf",
      "mustUsePriorOutputs": "research/read/analysis outputs go into sourceContext or prompt"
    },
    "outputContract": {
      "kind": "document_write",
      "primary": "artifact",
      "formats": [
        "docx",
        "pdf"
      ]
    },
    "artifactContract": {
      "artifactTypes": [
        "document",
        "pdf"
      ],
      "extension": ".docx",
      "extensions": [
        ".docx",
        ".pdf"
      ],
      "mobileBlocksRemainCanonical": true
    },
    "verificationPlan": [
      "Check written artifact exists and extension matches requested format.",
      "Writer args must contain concrete content or a prior-step reference.",
      "Content must be the deliverable itself, never a description of it."
    ],
    "liveNarration": [
      "Belge içeriği düzenleniyor",
      "Belge dosyası oluşturuluyor",
      "Belge çıktısı doğrulanıyor"
    ],
    "failureModes": [
      "EMPTY_DOCUMENT",
      "INVALID_OUTPUT_PATH",
      "DEPENDENCY_UNAVAILABLE"
    ],
    "fewShots": [
      {
        "args": {
          "title": "Pazar Raporu",
          "prompt": "{{steps.icerik.output}}"
        }
      }
    ],
    "utterances": [
      "masaüstüne pdf rapor hazırla",
      "bunu word belgesi yap",
      "bir rapor dosyası oluştur ve kaydet",
      "belge yaz",
      "docx oluştur",
      "pdf hazırla",
      "rapor kaydet"
    ],
    "notFor": [
      "pdf nedir açıkla",
      "word belgesi nasıl hazırlanır",
      "belgeyi oku ve özetle",
      "excel tablosu oluştur"
    ],
    "privacyClass": "local_private_write",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "write",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": [
      "document.docx_from_context",
      "document.summary_and_save"
    ]
  },
  {
    "name": "email_draft",
    "displayName": "E-posta taslağı",
    "description": "E-posta taslağı hazırlar (göndermez — kullanıcı onayına sunulur).",
    "usage": "E-posta yazmak için. Taslak onaydan sonra email_send ile gönderilir. Alıcı belirsizse netleştir.",
    "requiredArgs": [
      "to"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "E-posta yazmak için. Taslak onaydan sonra email_send ile gönderilir. Alıcı belirsizse netleştir."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (to) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "to"
      ],
      "properties": {
        "to": {
          "type": "ARRAY",
          "description": "Alıcı e-posta adresleri listesi. Bilinmiyorsa netleştirme iste, uydurma."
        },
        "subject": {
          "type": "STRING",
          "description": "E-posta konusu."
        },
        "topic": {
          "type": "STRING",
          "description": "İçeriğin kısa konusu (gövde bundan üretilir)."
        },
        "prompt": {
          "type": "STRING",
          "description": "Gövde için ayrıntılı yönlendirme/talimat."
        },
        "tone": {
          "type": "STRING",
          "description": "Üslup: 'resmi', 'samimi', 'kısa' vb."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "email_draft",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [
      {
        "args": {
          "to": [
            "ali@ornek.com"
          ],
          "subject": "Toplantı",
          "topic": "cuma 14:00 toplantı daveti",
          "tone": "resmi"
        }
      }
    ],
    "utterances": [
      "müşteriye e-posta taslağı hazırla",
      "şöyle bir mail yaz ama gönderme"
    ],
    "notFor": [
      "maili şimdi gönder"
    ],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "email_send",
    "displayName": "E-posta gönderme",
    "description": "Onaylı e-postayı GÖNDERİR (geri alınamaz — açık onay gerekir).",
    "usage": "Genelde email_draft ile taslak hazırlanıp onaydan sonra gönderilir. Doğrudan gönderim geri alınamaz.",
    "requiredArgs": [
      "to",
      "subject",
      "body"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "Genelde email_draft ile taslak hazırlanıp onaydan sonra gönderilir. Doğrudan gönderim geri alınamaz."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (to, subject, body) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "to",
        "subject",
        "body"
      ],
      "properties": {
        "to": {
          "type": "ARRAY",
          "description": "Alıcı adresleri. Gerçek adres yoksa gönderme, netleştir."
        },
        "subject": {
          "type": "STRING",
          "description": "Konu."
        },
        "body": {
          "type": "STRING",
          "description": "Gövde (tam metin)."
        },
        "connectionId": {
          "type": "STRING",
          "description": "Gönderen hesap bağlantı kimliği (varsa)."
        },
        "cc": {
          "type": "ARRAY",
          "description": "CC adresleri."
        },
        "bcc": {
          "type": "ARRAY",
          "description": "BCC adresleri."
        },
        "replyTo": {
          "type": "STRING",
          "description": "Yanıt adresi."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "email_send",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported.",
      "Permission or approval must be verified before the side effect runs."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "maili gönder",
      "e-postayı yolla artık"
    ],
    "notFor": [
      "e-posta taslağı hazırla ama gönderme",
      "mail nasıl atılır"
    ],
    "privacyClass": "permission_gated",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "file_find",
    "displayName": "Dosya bulma",
    "description": "Dosyaları ADIYLA/TÜRÜYLE bulur ve EN YENİDEN eskiye sıralar; içeriği hiç açmaz.",
    "usage": "\"Son/en yeni X dosyası\", \"masaüstündeki raporlar\", \"dünkü sunum\" gibi DOSYA bulma isteklerinde. Dosya İÇİNDE metin aramak için file_search.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "masaüstündeki son raporu bul",
      "en yeni sunumu getir",
      "indirilenlerdeki pdf'leri listele",
      "dünkü excel dosyasını bul"
    ],
    "whenNotToUse": [
      "Dosya İÇERİĞİNDE metin/fonksiyon aramak için file_search kullan.",
      "Yalnız klasör yapısını görmek için directory_tree kullan."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "path": {
          "type": "STRING",
          "description": "Aranacak klasör (ör. ~/Desktop)."
        },
        "name_contains": {
          "type": "STRING",
          "description": "Dosya adında geçmesi gereken metin (ör. 'rapor')."
        },
        "kind": {
          "type": "STRING",
          "description": "document | spreadsheet | presentation | image | archive | any",
          "enum": [
            "document",
            "spreadsheet",
            "presentation",
            "image",
            "archive",
            "any"
          ]
        },
        "max_depth": {
          "type": "NUMBER"
        },
        "max_results": {
          "type": "NUMBER"
        }
      },
      "additionalProperties": false,
      "optionalScope": [
        "path",
        "name_contains",
        "kind"
      ],
      "sortOrder": "modifiedAt DESC — 'son/en yeni' isteği doğrudan karşılanır",
      "singleResultField": "result.newest — tek dosya gerekiyorsa sonraki adım bunu kullanır"
    },
    "outputContract": {
      "kind": "file_find",
      "primary": "files",
      "newest": "result.newest"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Return files sorted newest first, or an explicit empty result.",
      "Never open file contents; this capability only reads names, sizes and timestamps."
    ],
    "liveNarration": [
      "Dosyalar taranıyor",
      "En yeni dosya seçiliyor"
    ],
    "failureModes": [
      "FILE_NOT_FOUND",
      "PATH_BLOCKED"
    ],
    "fewShots": [
      {
        "args": {
          "path": "~/Desktop",
          "name_contains": "rapor",
          "kind": "document"
        }
      }
    ],
    "utterances": [
      "masaüstündeki son raporu bul",
      "en yeni sunumu getir",
      "son indirdiğim dosyayı bul",
      "dünkü excel dosyasını bul",
      "indirilenlerdeki pdf'leri listele",
      "masaüstündeki word belgelerini göster",
      "en son değiştirdiğim dosya hangisi",
      "find the newest file"
    ],
    "notFor": [
      "rapor hazırla",
      "word belgesi oluştur",
      "sunum yap",
      "bu metni pdf olarak kaydet",
      "dosyanın içinde ara",
      "dosya içeriğini oku"
    ],
    "privacyClass": "local_private_read",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "file_move",
    "displayName": "Dosya taşıma",
    "description": "Dosyayı başka bir konuma taşır (hedef klasörse içine).",
    "usage": "İndirilen dosyaları kullanıcının istediği klasöre toplamak.",
    "requiredArgs": [
      "source",
      "destination"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "bu dosyayı şu klasöre taşı",
      "indirilenlerdeki dosyayı masaüstüne al",
      "üretilen dosyayı hedef klasöre yerleştir"
    ],
    "whenNotToUse": [
      "Silmek için move_to_trash kullan; taşımak silmek değildir.",
      "Kopya isteniyorsa taşıma yanlış: kaynak yerinde kalmalıysa bu yetenek uygun değil."
    ],
    "inputContract": {
      "required": [
        "source",
        "destination"
      ],
      "properties": {
        "source": {
          "type": "STRING",
          "description": "Taşınacak dosyanın yolu."
        },
        "destination": {
          "type": "STRING",
          "description": "Hedef yol ya da klasör."
        },
        "overwrite": {
          "type": "BOOLEAN",
          "description": "Hedef varsa üzerine yaz (varsayılan hayır)."
        }
      },
      "additionalProperties": false,
      "sourceMustExist": true
    },
    "outputContract": {
      "kind": "file_move",
      "primary": "moved_path"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Destination must exist after the step.",
      "Source must no longer exist at the old path."
    ],
    "liveNarration": [
      "Dosya taşınıyor"
    ],
    "failureModes": [
      "SOURCE_MISSING",
      "DESTINATION_EXISTS",
      "PERMISSION_REQUIRED",
      "RESOURCE_SCOPE"
    ],
    "fewShots": [
      {
        "user": "indirilenlerdeki raporu masaüstüne taşı",
        "args": {
          "source": "~/Downloads/rapor.pdf",
          "destination": "~/Desktop"
        }
      }
    ],
    "utterances": [
      "bu dosyayı masaüstüne taşı",
      "dosyanın adını rapor_final yap",
      "şunu arşiv klasörüne al",
      "dosya taşı",
      "dosyayı yeniden adlandır",
      "rename file"
    ],
    "notFor": [],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "file_patch",
    "displayName": "Dosya düzenleme",
    "description": "Var olan dosyanın içeriğini hedefli biçimde değiştirir; dosyanın tamamını yeniden yazmaz.",
    "usage": "Kod/metin dosyasında bir bölümü düzeltmek için: old_string çıpasını new_string ile değiştirir. Dosyayı sıfırdan üretmek gerekiyorsa file_write kullan.",
    "requiredArgs": [
      "path",
      "old_string"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "şu satırı düzelt",
      "testte kırılan yeri yamala",
      "dosyadaki değeri güncelle"
    ],
    "whenNotToUse": [
      "Dosya yoksa file_write kullan; yama var olan içeriği varsayar.",
      "Tüm içerik değişecekse yama yerine file_write daha okunur."
    ],
    "inputContract": {
      "required": [
        "path",
        "old_string"
      ],
      "properties": {
        "path": {
          "type": "STRING",
          "description": "Yamalanacak dosyanın yolu."
        },
        "old_string": {
          "type": "STRING",
          "description": "Değiştirilecek MEVCUT metin (çıpa). Dosyada birebir geçmeli."
        },
        "new_string": {
          "type": "STRING",
          "description": "Yerine yazılacak metin. Boş bırakmak silme demektir."
        },
        "replace_all": {
          "type": "BOOLEAN",
          "description": "Tüm eşleşmeleri değiştir (varsayılan yalnız ilki)."
        }
      },
      "additionalProperties": false,
      "pathMustExist": true,
      "oldStringMustMatchFileExactly": true
    },
    "outputContract": {
      "kind": "file_patch",
      "primary": "patched_path"
    },
    "artifactContract": {},
    "verificationPlan": [
      "File must exist and its hash must differ from the pre-execution state."
    ],
    "liveNarration": [
      "Dosya güncelleniyor"
    ],
    "failureModes": [
      "FILE_MISSING",
      "PATCH_DID_NOT_APPLY",
      "PERMISSION_REQUIRED"
    ],
    "fewShots": [],
    "utterances": [
      "şu satırı dosyada değiştir",
      "config.json'daki değeri güncelle",
      "dosyadaki bu ifadeyi şununla değiştir"
    ],
    "notFor": [],
    "privacyClass": "local_private_write",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "file_read",
    "displayName": "Dosya okuma",
    "description": "Düz metin/kod dosyasını güvenli şekilde okur; satır aralığı ve boyut sınırı destekler.",
    "usage": "Kod, txt, md, json gibi düz dosyalar için. PDF/DOCX için document_read.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "dosyayı oku",
      "şu kodu incele",
      "JSON içeriğini gör"
    ],
    "whenNotToUse": [
      "Zengin belge/PDF için document_read kullan.",
      "Klasör listesi için directory_tree kullan."
    ],
    "inputContract": {
      "required": [
        "path"
      ],
      "properties": {
        "path": {
          "type": "STRING"
        },
        "max_bytes": {
          "type": "NUMBER"
        },
        "start_line": {
          "type": "NUMBER"
        },
        "end_line": {
          "type": "NUMBER"
        }
      },
      "additionalProperties": false,
      "largeFiles": "use max_bytes or line range"
    },
    "outputContract": {
      "kind": "file_read",
      "primary": "text"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Read result must include path and text excerpt."
    ],
    "liveNarration": [
      "Dosya okunuyor"
    ],
    "failureModes": [
      "FILE_NOT_FOUND",
      "READ_BLOCKED",
      "TOO_LARGE"
    ],
    "fewShots": [
      {
        "args": {
          "path": "/Users/x/Desktop/notlar.txt"
        }
      }
    ],
    "utterances": [
      "package.json'u oku",
      "şu dosyanın içeriğini göster",
      "koddaki bu dosyayı aç bakalım",
      "dosya oku",
      "yerel dosyayı aç",
      "file read"
    ],
    "notFor": [
      "dosyayı bul nerede",
      "pdf belgeyi özetle",
      "dosyaya yaz"
    ],
    "privacyClass": "local_private_read",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "file_search",
    "displayName": "Dosya arama",
    "description": "Dosya içeriklerinde metin/regex arar; kod ve metin araştırması için hızlı indeksli arama kullanır.",
    "usage": "Kullanıcı bir repo/klasör içinde geçen metni, fonksiyonu, hatayı veya belge parçasını aradığında.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "bu projede nerede geçiyor",
      "dosyalarda ara",
      "fonksiyonu bul"
    ],
    "whenNotToUse": [
      "Sadece klasör yapısı için directory_tree kullan.",
      "Web bilgisi için web_research kullan.",
      "Dosyayı ADIYLA/TARİHE göre bulmak için file_find kullan — bu araç içeriğe bakar, 'son rapor' sorusunu cevaplayamaz."
    ],
    "inputContract": {
      "required": [
        "query"
      ],
      "properties": {
        "query": {
          "type": "STRING"
        },
        "path": {
          "type": "STRING"
        },
        "glob": {
          "type": "STRING"
        },
        "regex": {
          "type": "BOOLEAN"
        },
        "case_sensitive": {
          "type": "BOOLEAN",
          "description": "Büyük/küçük harf duyarlı."
        },
        "max_results": {
          "type": "NUMBER"
        }
      },
      "additionalProperties": false,
      "optionalScope": [
        "path",
        "glob"
      ]
    },
    "outputContract": {
      "kind": "file_search",
      "primary": "matches"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Return matched file paths or explicit empty result."
    ],
    "liveNarration": [
      "Dosyalarda aranıyor"
    ],
    "failureModes": [
      "SEARCH_TIMEOUT",
      "PATH_BLOCKED"
    ],
    "fewShots": [
      {
        "args": {
          "query": "TODO",
          "glob": "*.py"
        }
      }
    ],
    "utterances": [
      "projede TODO geçen yerleri bul",
      "bu metnin geçtiği dosyaları ara",
      "dosyalarımın içinde arama yap",
      "kodda şu fonksiyon nerede geçiyor",
      "dosya içinde metin ara",
      "search inside files"
    ],
    "notFor": [
      "internette ara",
      "dosyanın içeriğini oku"
    ],
    "privacyClass": "local_private_read",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "file_write",
    "displayName": "Dosya yazma",
    "description": "Düz metin/kod dosyası oluşturur veya açık overwrite ile değiştirir.",
    "usage": "TXT/MD/JSON/kod dosyası yazmak için. DOCX/PDF/XLSX/PPTX için ilgili writer capability'yi kullan.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "metni dosyaya kaydet",
      "markdown oluştur",
      "json dosyası yaz"
    ],
    "whenNotToUse": [
      "Word/PDF/Excel/sunum için specialized writer kullan.",
      "Küçük mevcut dosya düzenlemesi için file_patch daha uygundur."
    ],
    "inputContract": {
      "required": [
        "path"
      ],
      "properties": {
        "path": {
          "type": "STRING"
        },
        "content": {
          "type": "STRING"
        },
        "overwrite": {
          "type": "BOOLEAN"
        }
      },
      "additionalProperties": false,
      "contentRequiredUnlessEmptyFile": true,
      "overwriteMustBeExplicit": true
    },
    "outputContract": {
      "kind": "file_write",
      "primary": "artifact"
    },
    "artifactContract": {
      "artifactTypes": [
        "file"
      ],
      "mustIncludeOutputPath": true
    },
    "verificationPlan": [
      "Check written file exists.",
      "Overwrite must be explicit when target exists."
    ],
    "liveNarration": [
      "Dosya içeriği hazırlanıyor",
      "Dosya yazılıyor"
    ],
    "failureModes": [
      "INVALID_OUTPUT_PATH",
      "OVERWRITE_REQUIRED",
      "WRITE_BLOCKED"
    ],
    "fewShots": [],
    "utterances": [
      "notes.txt diye bir dosya oluştur içine merhaba yaz",
      "şunu bir metin dosyasına kaydet",
      "yeni bir kod dosyası yaz",
      "dosyaya yaz",
      "write local file"
    ],
    "notFor": [
      "pdf rapor hazırla",
      "excel dosyası oluştur",
      "kaydetmeden sadece anlat",
      "klasör oluştur"
    ],
    "privacyClass": "local_private_write",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "get_calendar_events",
    "displayName": "Takvim etkinliklerini görme",
    "description": "Apple Calendar takvimini okur (etkinlikleri listeler).",
    "usage": "Kullanıcı takvimini/programını sorduğunda. Yeni etkinlik için add_calendar_event.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Kullanıcı takvimini/programını sorduğunda. Yeni etkinlik için add_calendar_event."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (query) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "query"
      ],
      "properties": {
        "query": {
          "type": "STRING",
          "description": "Aranan aralık/konu, örn. 'bu hafta', 'yarın', 'toplantı'."
        },
        "limit": {
          "type": "NUMBER",
          "description": "Döndürülecek en fazla etkinlik sayısı."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "get_calendar_events",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [
      {
        "args": {
          "query": "bu hafta",
          "limit": 10
        }
      }
    ],
    "utterances": [
      "bu haftaki etkinliklerim neler",
      "yarın programım nasıl",
      "takvimimde ne var"
    ],
    "notFor": [
      "takvime etkinlik ekle",
      "etkinliği sil"
    ],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "get_reminders",
    "displayName": "Hatırlatıcıları görme",
    "description": "Apple Reminders listesini okur.",
    "usage": "Hatırlatıcıları/yapılacakları görüntülerken. Yeni öğe için add_reminder.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Hatırlatıcıları/yapılacakları görüntülerken. Yeni öğe için add_reminder."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (query) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "query"
      ],
      "properties": {
        "query": {
          "type": "STRING",
          "description": "Aranan konu/liste, örn. 'bugün', 'alışveriş'."
        },
        "limit": {
          "type": "NUMBER",
          "description": "En fazla öğe sayısı."
        },
        "list_name": {
          "type": "STRING",
          "description": "Belirli liste adı (varsa)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "get_reminders",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "hatırlatıcılarımı göster",
      "yapılacaklar listemde ne var"
    ],
    "notFor": [
      "hatırlatıcı kur",
      "bana anımsat"
    ],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "get_weather",
    "displayName": "Hava durumu",
    "description": "Anlık hava durumunu özetler.",
    "usage": "Hava durumu sorulduğunda.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Hava durumu sorulduğunda."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "location": {
          "type": "STRING",
          "description": "Şehir/konum adı, örn. 'İstanbul'. Boşsa mevcut konum."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "get_weather",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [
      {
        "args": {
          "location": "Ankara"
        }
      }
    ],
    "utterances": [
      "bugün hava nasıl",
      "yarın yağmur var mı",
      "İstanbul'da hava kaç derece"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "get_youtube_channel_report",
    "displayName": "YouTube kanal raporu",
    "description": "YouTube kanal istatistiklerini ve son video performansını raporlar.",
    "usage": "Bir YouTube kanalının performansını özetlerken.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Bir YouTube kanalının performansını özetlerken."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "query": {
          "type": "STRING",
          "description": "Kanal adı/araması."
        },
        "handle": {
          "type": "STRING",
          "description": "Kanal @handle'ı (varsa)."
        },
        "video_limit": {
          "type": "NUMBER",
          "description": "Raporlanacak son video sayısı."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "get_youtube_channel_report",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "kanalımın son video performansını raporla",
      "youtube istatistiklerimi göster"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "git_branch",
    "displayName": "Git dal",
    "description": "Yeni bir git branch'i oluşturur (varsayılan: oluşturup geçer).",
    "usage": "Ana dalda çalışmadan önce yeni bir dal açarken.",
    "requiredArgs": [
      "name"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Ana dalda çalışmadan önce yeni bir dal açarken."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (name) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "name"
      ],
      "properties": {
        "path": {
          "type": "STRING",
          "description": "Depo yolu."
        },
        "name": {
          "type": "STRING",
          "description": "Yeni dal adı."
        },
        "checkout": {
          "type": "BOOLEAN",
          "description": "Oluşturduktan sonra dala geç (varsayılan true)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "git_branch",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "yeni bir branch aç",
      "dal oluştur ve ona geç"
    ],
    "notFor": [],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "git_commit",
    "displayName": "Git commit",
    "description": "Değişiklikleri commit'ler (opsiyonel git add -A). PUSH YAPMAZ.",
    "usage": "Değişiklikleri kaydederken. Push YAPMAZ (güvenlik). Yeni dal için git_branch.",
    "requiredArgs": [
      "message"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Değişiklikleri kaydederken. Push YAPMAZ (güvenlik). Yeni dal için git_branch."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (message) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "message"
      ],
      "properties": {
        "path": {
          "type": "STRING",
          "description": "Depo yolu."
        },
        "message": {
          "type": "STRING",
          "description": "Commit mesajı — kısa ve açıklayıcı."
        },
        "add_all": {
          "type": "BOOLEAN",
          "description": "Commit'ten önce tüm değişiklikleri sahnele (git add -A)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "git_commit",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "değişiklikleri commit'le",
      "şu mesajla kaydet depoya"
    ],
    "notFor": [
      "git durumuna bak",
      "commit nedir açıkla"
    ],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "git_diff",
    "displayName": "Git değişiklikleri",
    "description": "Bir git deposundaki çalışma ağacı veya staged farkını (diff) döndürür.",
    "usage": "Kod değişikliklerinin detayını görmek için.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Kod değişikliklerinin detayını görmek için."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "path": {
          "type": "STRING",
          "description": "Depo yolu."
        },
        "staged": {
          "type": "BOOLEAN",
          "description": "true → staged (index) farkı; false → çalışma ağacı."
        },
        "target_file": {
          "type": "STRING",
          "description": "Yalnız bu dosyanın farkı (varsa)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "git_diff",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "ne değişmiş göster",
      "farkları görmek istiyorum"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "git_status",
    "displayName": "Git durumu",
    "description": "Bir git deposunun durumunu (branch + staged/unstaged/untracked) döndürür.",
    "usage": "Bir repoda hangi değişiklikler var diye bakarken.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Bir repoda hangi değişiklikler var diye bakarken."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "path": {
          "type": "STRING",
          "description": "Depo yolu (boşsa çalışma dizini)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "git_status",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "git durumuna bak",
      "depoda ne durumdayız",
      "git'te hangi dosyalar değişmiş",
      "commit edilmemiş değişiklikler neler"
    ],
    "notFor": [
      "git nedir",
      "değişiklikleri commit'le"
    ],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "image_edit",
    "displayName": "Görsel düzenleme",
    "description": "Mevcut görseli kullanıcı düzeltmesine göre değiştirir; son görsel artefact/prompt bağlamını korur.",
    "usage": "'bunu beyaz yap', 'daha sinematik yap', 'arka planı değiştir' gibi follow-up görsel düzenlemelerinde.",
    "requiredArgs": [
      "prompt",
      "sourcePath"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "mevcut görseli düzenle",
      "son resmi değiştir",
      "daha sinematik yap",
      "rengini değiştir"
    ],
    "whenNotToUse": [
      "Sıfırdan alakasız yeni görsel için image_generate kullan.",
      "Görseli sadece okumak için image_read kullan."
    ],
    "inputContract": {
      "required": [
        "prompt",
        "sourcePath"
      ],
      "properties": {
        "prompt": {
          "type": "STRING"
        },
        "sourcePath": {
          "type": "STRING",
          "description": "Düzenlenecek ana görsel yolu."
        },
        "sourcePaths": {
          "type": "ARRAY",
          "description": "İsteğe bağlı ek referans görsel yolları."
        },
        "outputPath": {
          "type": "STRING"
        },
        "title": {
          "type": "STRING",
          "description": "Çıktı başlığı/dosya adı."
        },
        "aspectRatio": {
          "type": "STRING",
          "description": "Çıktı en-boy oranı."
        },
        "imageSize": {
          "type": "STRING",
          "description": "Çözünürlük: '1K', '2K' veya '4K'."
        },
        "overwrite": {
          "type": "BOOLEAN",
          "description": "Üzerine yaz."
        },
        "imagePath": {
          "type": "STRING"
        },
        "sourceImagePath": {
          "type": "STRING"
        }
      },
      "additionalProperties": false,
      "sourceImageRequired": "imagePath or latestArtifactRef.imagePath",
      "mustPreserveSubject": true
    },
    "outputContract": {
      "kind": "image_edit",
      "primary": "image_artifact"
    },
    "artifactContract": {
      "artifactTypes": [
        "image"
      ],
      "sourceArtifactRequired": true
    },
    "verificationPlan": [
      "Edited artifact exists and preserves requested subject unless user asked otherwise."
    ],
    "liveNarration": [
      "Önceki görsel referansı alınıyor",
      "Düzenleme uygulanıyor",
      "Görsel kontrol ediliyor"
    ],
    "failureModes": [
      "MISSING_SOURCE_IMAGE",
      "GENERATION_UNAVAILABLE",
      "SAFETY_BLOCKED"
    ],
    "fewShots": [
      {
        "args": {
          "prompt": "Arka planı gün batımı yap, kişiyi değiştirme",
          "sourcePath": "portrait.png",
          "imageSize": "2K"
        }
      }
    ],
    "utterances": [
      "bu görseldeki arka planı değiştir",
      "resme şunu ekle",
      "az önceki görseli düzelt",
      "görseli düzenle",
      "resme ekle",
      "modify image"
    ],
    "notFor": [],
    "privacyClass": "external_model_optional",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "write",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "image_fetch",
    "displayName": "Görsel indirme",
    "description": "Herkese açık bir kaynaktan (Openverse/Wikimedia) bir konu için görsel indirir ve kullanıcının klasörüne (varsayılan masaüstü) kaydeder.",
    "usage": "Web'den hazır/telifsiz görsel indirmek için. Sıfırdan görsel üretmek için image_generate.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Web'den hazır/telifsiz görsel indirmek için. Sıfırdan görsel üretmek için image_generate."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (query) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "query"
      ],
      "properties": {
        "query": {
          "type": "STRING",
          "description": "İndirilecek görselin konusu/araması."
        },
        "destination": {
          "type": "STRING",
          "description": "Kaydedilecek klasör (varsayılan masaüstü)."
        },
        "count": {
          "type": "INTEGER",
          "description": "İndirilecek görsel sayısı."
        },
        "overwrite": {
          "type": "BOOLEAN",
          "description": "Var olanın üzerine yaz."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "image_fetch",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "eyfel kulesinin gerçek fotoğrafını indir",
      "bu konuda gerçek bir fotoğraf bul ve kaydet"
    ],
    "notFor": [
      "hayali bir görsel üret",
      "çizim yap"
    ],
    "privacyClass": "local_private_write",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "image_generate",
    "displayName": "Görsel üretme",
    "description": "Yeni görsel üretir; prompt önceki görsel/artefact takiplerini ve kullanıcının düzeltmesini taşımalıdır.",
    "usage": "Sıfırdan görsel/resim çizmek/üretmek için. Mevcut görseli değiştirmek için image_edit.",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "kedi resmi çiz",
      "görsel oluştur",
      "kapak görseli üret"
    ],
    "whenNotToUse": [
      "Önceki görseli değiştir/daha sinematik/beyaz yap isteniyorsa image_edit veya latestArtifactRef tabanlı generation kullan.",
      "Web'den hazır görsel indirmek için image_fetch kullan."
    ],
    "inputContract": {
      "required": [
        "prompt"
      ],
      "properties": {
        "prompt": {
          "type": "STRING"
        },
        "outputPath": {
          "type": "STRING"
        },
        "title": {
          "type": "STRING",
          "description": "Görsel başlığı/dosya adı."
        },
        "aspectRatio": {
          "type": "STRING",
          "description": "En-boy oranı, örn. '1:1', '16:9' veya '9:16'.",
          "enum": [
            "1:1",
            "1:4",
            "1:8",
            "2:3",
            "3:2",
            "3:4",
            "4:1",
            "4:3",
            "4:5",
            "5:4",
            "8:1",
            "9:16",
            "16:9",
            "21:9"
          ]
        },
        "imageSize": {
          "type": "STRING",
          "description": "Çözünürlük: '1K', '2K' veya açık istekle '4K'.",
          "enum": [
            "1K",
            "2K",
            "4K"
          ]
        },
        "overwrite": {
          "type": "BOOLEAN",
          "description": "Üzerine yaz."
        },
        "size": {
          "type": "STRING"
        },
        "style": {
          "type": "STRING"
        }
      },
      "additionalProperties": false,
      "promptMustBeFullVisualSpec": true,
      "followUpMustReusePreviousPrompt": true
    },
    "outputContract": {
      "kind": "image_generate",
      "primary": "image_artifact"
    },
    "artifactContract": {
      "artifactTypes": [
        "image"
      ],
      "mustIncludeOutputPath": true
    },
    "verificationPlan": [
      "Generated artifact exists and matches requested subject/style constraints."
    ],
    "liveNarration": [
      "Görsel prompt'u hazırlanıyor",
      "Görsel üretiliyor",
      "Sonuç kontrol ediliyor"
    ],
    "failureModes": [
      "GENERATION_UNAVAILABLE",
      "SAFETY_BLOCKED",
      "TIMEOUT"
    ],
    "fewShots": [
      {
        "args": {
          "prompt": "minimalist dağ manzarası, düz renkler",
          "aspectRatio": "1:1",
          "imageSize": "2K"
        }
      }
    ],
    "utterances": [
      "bana bir kedi resmi çiz",
      "şöyle bir görsel üret",
      "hayali bir manzara tasarla",
      "resim çiz",
      "draw a picture"
    ],
    "notFor": [
      "verinin grafiğini çiz",
      "gerçek bir fotoğrafını bul",
      "bu görselde ne yazıyor"
    ],
    "privacyClass": "external_model_optional",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "write",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "image_read",
    "displayName": "Görsel inceleme",
    "description": "Görseli okur, içerik/etiket/metin/özet çıkarır.",
    "usage": "Paylaşılan fotoğraf/görsel/screenshot dosyasını anlamak için. Canlı aktif ekran için analyze_screen.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "bu görselde ne var",
      "resmi analiz et",
      "fotoğraftaki metni oku"
    ],
    "whenNotToUse": [
      "Aktif masaüstü ekranı için analyze_screen kullan.",
      "Yeni görsel üretmek için image_generate kullan."
    ],
    "inputContract": {
      "required": [
        "path"
      ],
      "properties": {
        "path": {
          "type": "STRING"
        },
        "mode": {
          "type": "STRING",
          "description": "'summary' (açıklama), 'metadata' veya 'palette' (renkler).",
          "enum": [
            "summary",
            "metadata",
            "palette"
          ]
        },
        "query": {
          "type": "STRING"
        }
      },
      "additionalProperties": false,
      "queryOptional": true
    },
    "outputContract": {
      "kind": "image_read",
      "primary": "vision_summary"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Vision summary should mention visible content and uncertainty."
    ],
    "liveNarration": [
      "Görsel okunuyor"
    ],
    "failureModes": [
      "FILE_NOT_FOUND",
      "VISION_UNAVAILABLE",
      "LOW_CONFIDENCE"
    ],
    "fewShots": [],
    "utterances": [
      "bu fotoğrafta ne var",
      "görseli analiz et",
      "resimde neler görüyorsun"
    ],
    "notFor": [],
    "privacyClass": "local_private_read",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "latex_parse",
    "displayName": "LaTeX işleme",
    "description": "LaTeX matematik ifadesini yerel sembolik forma çevirir/normalize eder.",
    "usage": "LaTeX'i işlerken. Sayısal çözüm için math_solve.",
    "requiredArgs": [
      "expression"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "LaTeX'i işlerken. Sayısal çözüm için math_solve."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (expression) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "expression"
      ],
      "properties": {
        "expression": {
          "type": "STRING",
          "description": "LaTeX ifadesi, örn. '\\frac{a}{b}'."
        },
        "mode": {
          "type": "STRING",
          "description": "'parse' veya 'normalize'.",
          "enum": [
            "parse",
            "normalize"
          ]
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "latex_parse",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "bu latex ifadesini normalize et",
      "formülü sembolik forma çevir"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "make_directory",
    "displayName": "Klasör oluşturma",
    "description": "Klasör oluşturur (üst klasörler dahil; varsa hata vermez).",
    "usage": "İndirilen/üretilen dosyaları toplamadan önce hedef klasörü hazırlamak veya kullanıcının istediği klasörü açmak.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "masaüstünde klasör oluştur",
      "dosyaları toplamadan önce hedef klasörü hazırla"
    ],
    "whenNotToUse": [
      "Dosya YAZMAK istiyorsan file_write zaten üst klasörü açar; ayrı adım gereksiz.",
      "Var olan bir klasörü taşımak için file_move kullan."
    ],
    "inputContract": {
      "required": [
        "path"
      ],
      "properties": {
        "path": {
          "type": "STRING",
          "description": "Oluşturulacak klasör yolu (ör. ~/Desktop/youtube-transkript)."
        }
      },
      "additionalProperties": false,
      "pathMustBeConcrete": true
    },
    "outputContract": {
      "kind": "make_directory",
      "primary": "directory_state"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Directory must exist on disk after the step."
    ],
    "liveNarration": [
      "Klasör hazırlanıyor"
    ],
    "failureModes": [
      "PERMISSION_REQUIRED",
      "PATH_INVALID",
      "RESOURCE_SCOPE"
    ],
    "fewShots": [
      {
        "user": "masaüstüne rapor adında klasör aç",
        "args": {
          "path": "~/Desktop/rapor"
        }
      }
    ],
    "utterances": [
      "Masaüstünde Cabir adında klasör oluştur",
      "yeni bir klasör aç adı Arşiv olsun",
      "şuraya bir dizin yarat"
    ],
    "notFor": [
      "klasördeki dosyaları listele",
      "klasör yapısını göster"
    ],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "math_solve",
    "displayName": "Matematik çözümü",
    "description": "Somut matematiksel ifadeyi çözer, sadeleştirir veya hesaplar; açıklama değil ifade alır.",
    "usage": "Hesaplama, denklem, oran, vergi/KDV, optimizasyon alt hesabı için. expression her zaman rakamlı/sembolik ifade olmalı.",
    "requiredArgs": [
      "expression"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "hesapla",
      "denklem çöz",
      "KDV tutarını bul",
      "toplam/maliyet/oran hesapla"
    ],
    "whenNotToUse": [
      "Metin analizi için text_analyze kullan.",
      "Tablo çıktısı için math_solve sonrası spreadsheet_write kullan."
    ],
    "inputContract": {
      "required": [
        "expression"
      ],
      "properties": {
        "expression": {
          "type": "STRING"
        },
        "mode": {
          "type": "STRING",
          "enum": [
            "solve",
            "simplify",
            "factor",
            "expand",
            "evaluate"
          ]
        }
      },
      "additionalProperties": false,
      "expressionMustBeConcrete": true,
      "examples": [
        "12000+8500",
        "(12000+8500)*0.20"
      ]
    },
    "outputContract": {
      "kind": "math_solve",
      "primary": "numeric_or_symbolic_result"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Expression must not be prose-only.",
      "Result must be non-empty and feed writer/table via {{steps.<id>.output}}."
    ],
    "liveNarration": [
      "Hesaplama yapılıyor"
    ],
    "failureModes": [
      "INVALID_EXPRESSION",
      "NO_NUMERIC_EXPRESSION"
    ],
    "fewShots": [
      {
        "args": {
          "expression": "12 * (3 + 4)"
        }
      }
    ],
    "utterances": [
      "x^2 + 3x - 4 = 0 çöz",
      "türevini al",
      "şu ifadeyi sadeleştir",
      "hesapla: 12000+8500"
    ],
    "notFor": [
      "matematik nasıl çalışılır",
      "grafiğini çiz"
    ],
    "privacyClass": "local_safe_compute",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": [
      "math.solve"
    ]
  },
  {
    "name": "mcp_call_tool",
    "displayName": "MCP aracı",
    "description": "Bağlı bir MCP sunucusundaki aracı çağırır (harici entegrasyonlar).",
    "usage": "Yerleşik yeteneklerin karşılamadığı, kullanıcının bağladığı bir MCP aracı gerektiğinde.",
    "requiredArgs": [
      "serverId",
      "toolName"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "Yerleşik yeteneklerin karşılamadığı, kullanıcının bağladığı bir MCP aracı gerektiğinde."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (serverId, toolName) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "serverId",
        "toolName"
      ],
      "properties": {
        "serverId": {
          "type": "STRING",
          "description": "MCP sunucu kimliği."
        },
        "toolName": {
          "type": "STRING",
          "description": "Çağrılacak araç adı."
        },
        "arguments": {
          "type": "OBJECT",
          "description": "Araca geçilecek argümanlar (araç şemasına uygun)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "mcp_call_tool",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported.",
      "Permission or approval must be verified before the side effect runs."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "bağlı mcp aracını çağır",
      "harici entegrasyondaki aracı kullan"
    ],
    "notFor": [],
    "privacyClass": "permission_gated",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "move_to_trash",
    "displayName": "Çöp Kutusu'na taşıma",
    "description": "Dosyayı/klasörü Çöp Kutusu'na taşır (geri alınabilir; kalıcı silme değil).",
    "usage": "Kullanıcı bir dosyayı/klasörü silmek istediğinde. Kalıcı silme yok; hedef Çöp Kutusu'na taşınır.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "bu klasörü sil",
      "şu dosyayı sil",
      "az önce oluşturduğun klasörü kaldır",
      "masaüstündeki dosyayı çöpe at"
    ],
    "whenNotToUse": [
      "Hafızadan/hatırlatıcıdan bir kaydı unutmak isteniyorsa delete_memory kullan; bu yetenek DOSYA sistemine dokunur.",
      "Takvim etkinliği silinecekse delete_calendar_event kullan.",
      "Dosya başka yere gidecekse silme değil taşıma: file_move."
    ],
    "inputContract": {
      "required": [
        "path"
      ],
      "properties": {
        "path": {
          "type": "STRING",
          "description": "Silinecek dosya ya da klasör yolu (ör. ~/Desktop/poke)."
        }
      },
      "additionalProperties": false,
      "pathMustExist": true,
      "pathMustNotBeSystemRoot": true
    },
    "outputContract": {
      "kind": "move_to_trash",
      "primary": "trashed_path",
      "recoverable": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Source path must be gone afterwards.",
      "The item must be present in Trash: 'deleted' must also mean 'recoverable'."
    ],
    "liveNarration": [
      "Çöp Kutusu'na taşınıyor"
    ],
    "failureModes": [
      "PATH_MISSING",
      "PROTECTED_ROOT",
      "PERMISSION_REQUIRED"
    ],
    "fewShots": [
      {
        "user": "masaüstündeki poke klasörünü sil",
        "args": {
          "path": "~/Desktop/poke"
        }
      }
    ],
    "utterances": [
      "o klasörü sil",
      "bu dosyayı sil",
      "masaüstündeki poke klasörünü sil",
      "şunu çöpe at",
      "dosyayı çöp kutusuna taşı",
      "klasörü kaldır",
      "bu dosyadan kurtul",
      "delete this file",
      "move to trash",
      "remove that folder"
    ],
    "notFor": [
      "hakkımdaki kaydı sil",
      "o bilgiyi hafızandan çıkar",
      "sohbet geçmişini temizle",
      "uygulamayı kapat"
    ],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "destructive",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "ocr_read",
    "displayName": "Görüntüden metin (OCR)",
    "description": "Görsel veya taranmış PDF sayfasındaki metni OCR ile çıkarır.",
    "usage": "Fotoğraf/ekran görüntüsü/taranmış belgedeki YAZIYI okumak için. Seçilebilir metinli belge için document_read.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Fotoğraf/ekran görüntüsü/taranmış belgedeki YAZIYI okumak için. Seçilebilir metinli belge için document_read."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (path) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "path"
      ],
      "properties": {
        "path": {
          "type": "STRING",
          "description": "Görsel/PDF yolu."
        },
        "mode": {
          "type": "STRING",
          "description": "OCR modu (varsa)."
        },
        "languageHint": {
          "type": "STRING",
          "description": "Metin dili ipucu, örn. 'tr'."
        },
        "backend": {
          "type": "STRING",
          "description": "auto, rapidocr, tesseract, easyocr, paddleocr veya surya."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "ocr_read",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "taranmış faturadaki yazıyı çıkar",
      "bu görüntüdeki metni oku",
      "fotoğraftaki yazıyı metne çevir"
    ],
    "notFor": [],
    "privacyClass": "local_private_read",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "open_app",
    "displayName": "Uygulama açma",
    "description": "Yerel uygulamayı açar ve öne getirir.",
    "usage": "Kullanıcı bir uygulamayı açmak/öne getirmek istediğinde. Uygulama içinde iş yapılacaksa önce bunu çağır, sonra desktop_operator ile devam et.",
    "requiredArgs": [
      "app_name"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "spotify aç",
      "terminali aç",
      "şu uygulamayı öne getir"
    ],
    "whenNotToUse": [
      "Bir web adresi açılacaksa browser_control daha doğrudur.",
      "Kalıcı kabuk oturumu isteniyorsa shell_session_open kullan; Terminal penceresi açmak aynı şey değildir."
    ],
    "inputContract": {
      "required": [
        "app_name"
      ],
      "properties": {
        "app_name": {
          "type": "STRING"
        }
      },
      "additionalProperties": false,
      "appNameMustBeConcrete": true
    },
    "outputContract": {
      "kind": "open_app",
      "primary": "foreground_app"
    },
    "artifactContract": {},
    "verificationPlan": [
      "The app must actually be frontmost afterwards; a launch attempt alone is not success."
    ],
    "liveNarration": [
      "Uygulama açılıyor"
    ],
    "failureModes": [
      "APP_NOT_FOUND",
      "PERMISSION_REQUIRED",
      "LAUNCH_FAILED"
    ],
    "fewShots": [
      {
        "args": {
          "app_name": "Google Chrome"
        }
      },
      {
        "args": {
          "app_name": "Notes"
        }
      }
    ],
    "utterances": [
      "Finder'ı açar mısın",
      "Spotify uygulamasını başlat",
      "Notlar'ı aç",
      "hesap makinesini açsana",
      "open the Notes app",
      "uygulama aç",
      "finder aç",
      "open app"
    ],
    "notFor": [
      "yeni bir klasör aç",
      "yeni bir branch aç",
      "terminal oturumu aç",
      "bu adresi aç"
    ],
    "privacyClass": "permission_gated",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "play_media",
    "displayName": "Medya oynatma",
    "description": "YouTube, Spotify veya Apple Music ile şarkı/çalma listesi oynatır.",
    "usage": "Müzik/video çalmak için. Sadece uygulamayı açmak için open_app kullan.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "Müzik/video çalmak için. Sadece uygulamayı açmak için open_app kullan."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (query) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "query"
      ],
      "properties": {
        "query": {
          "type": "STRING",
          "description": "Çalınacak şarkı, sanatçı veya çalma listesi adı."
        },
        "provider": {
          "type": "STRING",
          "description": "Kaynak: 'youtube', 'spotify' veya 'music'. Belirtilmezse akıllı seçilir."
        },
        "autoplay": {
          "type": "BOOLEAN",
          "description": "Bulunan ilk sonucu otomatik çal (varsayılan true)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "play_media",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported.",
      "Permission or approval must be verified before the side effect runs."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [
      {
        "args": {
          "query": "Tarkan Kuzu Kuzu",
          "provider": "spotify"
        }
      }
    ],
    "utterances": [
      "şu şarkıyı çal",
      "spotify'da çalma listemi başlat",
      "youtube'da lofi aç",
      "müzik aç"
    ],
    "notFor": [
      "spotify'ı kapat",
      "müzik uygulaması nasıl kullanılır"
    ],
    "privacyClass": "permission_gated",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "presentation_write",
    "displayName": "Sunum oluşturma",
    "description": "Verilen HAZIR metni/anahatları PPTX sunum dosyasına yazar. İçerik ÜRETMEZ.",
    "usage": "Sunum, slayt, pptx, ders/proje sunumu veya konuşma deck'i istendiğinde.",
    "requiredArgs": [],
    "requiresApproval": true,
    "whenToUse": [
      "sunum hazırla",
      "5 slaytlık deck yap",
      "araştırmayı pptx'e dönüştür"
    ],
    "whenNotToUse": [
      "PDF raporu için canvas_write kullan.",
      "Word raporu için document_write kullan."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "prompt": {
          "type": "STRING",
          "description": "Slaytlara YAZILACAK hazır metin/anahat. Konu/talimat DEĞİL."
        },
        "outputPath": {
          "type": "STRING"
        },
        "title": {
          "type": "STRING"
        },
        "slides": {
          "type": "ARRAY"
        },
        "blocks": {
          "type": "ARRAY"
        },
        "sourceContext": {
          "type": "STRING"
        },
        "overwrite": {
          "type": "BOOLEAN",
          "description": "Üzerine yaz."
        }
      },
      "additionalProperties": false,
      "contentFields": [
        "prompt",
        "slides",
        "sourceContext"
      ],
      "slideCount": "derive from user request or use concise default"
    },
    "outputContract": {
      "kind": "presentation_write",
      "primary": "artifact",
      "formats": [
        "pptx"
      ]
    },
    "artifactContract": {
      "artifactTypes": [
        "presentation"
      ],
      "extension": ".pptx"
    },
    "verificationPlan": [
      "Check PPTX artifact exists.",
      "Slides must contain titles and body bullets."
    ],
    "liveNarration": [
      "Slayt akışı çıkarılıyor",
      "Sunum dosyası yazılıyor",
      "PPTX çıktısı doğrulanıyor"
    ],
    "failureModes": [
      "EMPTY_PRESENTATION",
      "INVALID_OUTPUT_PATH",
      "DEPENDENCY_UNAVAILABLE"
    ],
    "fewShots": [
      {
        "args": {
          "title": "Ürün Tanıtımı",
          "prompt": "{{steps.icerik.output}}"
        }
      }
    ],
    "utterances": [
      "sunum hazırla 10 slayt olsun",
      "bunu powerpoint'e dök",
      "slaytlara böl",
      "sunum hazırla",
      "slayt oluştur",
      "pptx yap"
    ],
    "notFor": [],
    "privacyClass": "local_private_write",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "write",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": [
      "presentation.deck_from_context"
    ]
  },
  {
    "name": "quantum_compare_classical",
    "displayName": "Kuantum karşılaştırma",
    "description": "Kuantum demo sonucunu klasik baseline ile karşılaştırır.",
    "usage": "Kuantum sonucunu klasik yöntemle kıyaslarken.",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Kuantum sonucunu klasik yöntemle kıyaslarken."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (prompt) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "prompt"
      ],
      "properties": {
        "prompt": {
          "type": "STRING",
          "description": "Karşılaştırılacak problem/sonuç bağlamı."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "quantum_compare_classical",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "kuantum sonucunu klasikle karşılaştır",
      "klasik baseline'a göre nasıl"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "quantum_generate_report",
    "displayName": "Kuantum raporu",
    "description": "Kuantum deney akışı için teknik rapor ve metrik artifact üretir.",
    "usage": "Kuantum deney akışının sonunda özet rapor üretmek için.",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Kuantum deney akışının sonunda özet rapor üretmek için."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (prompt) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "prompt"
      ],
      "properties": {
        "prompt": {
          "type": "STRING",
          "description": "Rapor konusu/kapsamı."
        },
        "title": {
          "type": "STRING",
          "description": "Rapor başlığı."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "quantum_generate_report",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "kuantum deneyi için teknik rapor üret",
      "deney metriklerini raporla"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "quantum_model_problem",
    "displayName": "Kuantum modelleme",
    "description": "Optimizasyon problemini QUBO/Ising demo modeline dönüştürür.",
    "usage": "Kuantum/optimizasyon demo akışının ilk adımı; ardından quantum_run_experiment.",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Kuantum/optimizasyon demo akışının ilk adımı; ardından quantum_run_experiment."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (prompt) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "prompt"
      ],
      "properties": {
        "prompt": {
          "type": "STRING",
          "description": "Modellemek istenen optimizasyon problemi."
        },
        "problemClass": {
          "type": "STRING",
          "description": "Problem sınıfı (varsa)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "quantum_model_problem",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "bu optimizasyon problemini qubo modeline dök",
      "ising formülasyonuna çevir"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "quantum_run_experiment",
    "displayName": "Kuantum deneyi",
    "description": "QAOA/VQE simülatör demo deneyini yürütür.",
    "usage": "Kuantum demo deneyi çalıştırmak için (Qiskit/Aer gerekir).",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Kuantum demo deneyi çalıştırmak için (Qiskit/Aer gerekir)."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (prompt) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "prompt"
      ],
      "properties": {
        "prompt": {
          "type": "STRING",
          "description": "Deney tanımı/hedefi."
        },
        "algorithm": {
          "type": "STRING",
          "description": "Algoritma: 'qaoa' veya 'vqe'."
        },
        "shots": {
          "type": "NUMBER",
          "description": "Ölçüm sayısı."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "quantum_run_experiment",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "qaoa deneyini çalıştır",
      "vqe simülasyonunu koştur"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "retrieve_context",
    "displayName": "Yerel bağlam getirme",
    "description": "Yerel çalışma alanı ve konuşmalardan bağlam eşleşmeleri döndürür (çevrimdışı).",
    "usage": "Yerel/geçmiş bilgi gerektiğinde veya web erişilemediğinde. Güncel dış bilgi için web_research.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Yerel/geçmiş bilgi gerektiğinde veya web erişilemediğinde. Güncel dış bilgi için web_research."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (query) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "query"
      ],
      "properties": {
        "query": {
          "type": "STRING",
          "description": "Aranan konu/soru."
        },
        "sources": {
          "type": "STRING",
          "description": "Kaynaklar, virgüllü: 'workspace,conversations'."
        },
        "limit": {
          "type": "NUMBER",
          "description": "En fazla eşleşme."
        },
        "conversationId": {
          "type": "STRING",
          "description": "Belirli konuşma bağlamı (varsa)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "retrieve_context",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "daha önce bu konuda ne konuşmuştuk",
      "geçen seferki notlarıma bak"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "run_skill",
    "displayName": "Beceri çalıştırma",
    "description": "Hazır local skill workflow'unu exact skillId ve payload ile çalıştırır.",
    "usage": "Skill kataloğunda kullanıcının isteğine bire bir uyan hazırlanmış workflow varsa kullan. Skill id'sini capability adı gibi uydurma; yalnız katalogdaki exact id geçerlidir.",
    "requiredArgs": [
      "skillId"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "hazır workflow bire bir uyuyor",
      "çok adımlı tekrarlı beceri katalogda var",
      "skill manifesti exact payload alanlarını veriyor"
    ],
    "whenNotToUse": [
      "Katalogdaki skill tam uymuyorsa primitive tool zinciri kur.",
      "Skill id katalogda yoksa run_skill kullanma."
    ],
    "inputContract": {
      "required": [
        "skillId"
      ],
      "properties": {
        "skillId": {
          "type": "STRING"
        },
        "payload": {
          "type": "OBJECT"
        }
      },
      "additionalProperties": false,
      "skillIdMustExistInCatalog": true,
      "payloadMustSatisfyRequiredParameters": true
    },
    "outputContract": {
      "kind": "run_skill",
      "primary": "lastStepResult"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Chosen skillId must exist in DESKTOP_SKILL_MANIFEST.",
      "Payload must include every requiredParameter."
    ],
    "liveNarration": [
      "Hazır beceri akışı başlatılıyor",
      "Beceri adımları yürütülüyor"
    ],
    "failureModes": [
      "UNKNOWN_SKILL",
      "MISSING_PAYLOAD_FIELD",
      "STEP_FAILED"
    ],
    "fewShots": [],
    "utterances": [
      "hazır iş akışını çalıştır",
      "katalogdaki o beceriyi uygula"
    ],
    "notFor": [
      "sen neler yapabiliyorsun",
      "yeteneklerini anlat"
    ],
    "privacyClass": "local_private_mixed",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "save_memory",
    "displayName": "Hafızaya kaydetme",
    "description": "Kullanıcı hakkında kalıcı bir tercih/olgu kaydeder (sonraki oturumlarda hatırlanır).",
    "usage": "Kullanıcı 'bunu hatırla/aklında tut' dediğinde kalıcı tercih/olgu kaydetmek için.",
    "requiredArgs": [
      "key",
      "value"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Kullanıcı 'bunu hatırla/aklında tut' dediğinde kalıcı tercih/olgu kaydetmek için."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (key, value) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "key",
        "value"
      ],
      "properties": {
        "category": {
          "type": "STRING",
          "description": "Kategori, örn. 'tercih', 'kişi', 'proje'."
        },
        "key": {
          "type": "STRING",
          "description": "Kısa anahtar/etiket."
        },
        "value": {
          "type": "STRING",
          "description": "Hatırlanacak bilgi."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "save_memory",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [
      {
        "args": {
          "category": "tercih",
          "key": "kahve",
          "value": "sütlü, şekersiz"
        }
      }
    ],
    "utterances": [
      "kahve sevmediğimi unutma",
      "bunu aklında tut",
      "beni böyle bilmeni istiyorum"
    ],
    "notFor": [
      "hafızandaki kaydı sil",
      "daha önce ne konuşmuştuk",
      "numarayı kişi olarak kaydet"
    ],
    "privacyClass": "local_private_write",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "save_whatsapp_contact",
    "displayName": "WhatsApp kişi kaydı",
    "description": "WhatsApp kişisini kalıcı kaydeder (sonraki mesajlarda adla çözülür).",
    "usage": "Bir kişiyi ilerideki WhatsApp mesajları için kaydetmek üzere.",
    "requiredArgs": [
      "display_name",
      "phone_number"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "Bir kişiyi ilerideki WhatsApp mesajları için kaydetmek üzere."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (display_name, phone_number) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "display_name",
        "phone_number"
      ],
      "properties": {
        "display_name": {
          "type": "STRING",
          "description": "Kişinin görünen adı."
        },
        "phone_number": {
          "type": "STRING",
          "description": "Uluslararası numara (+90…)."
        },
        "aliases": {
          "type": "STRING",
          "description": "Alternatif adlar, virgüllü (varsa)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "save_whatsapp_contact",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported.",
      "Permission or approval must be verified before the side effect runs."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "bu numarayı Ayşe olarak kaydet",
      "kişiyi rehbere ekle"
    ],
    "notFor": [
      "kişiye mesaj gönder",
      "hakkımda bir bilgi kaydet"
    ],
    "privacyClass": "permission_gated",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "screen_capture",
    "displayName": "Ekran görüntüsü",
    "description": "Ekranın, pencerenin veya seçilen bölgenin görüntüsünü alıp DOSYA olarak kaydeder.",
    "usage": "Kullanıcı ekran görüntüsü alıp saklamak istediğinde. Ekranda NE OLDUĞUNU soruyorsa analyze_screen kullan.",
    "requiredArgs": [
      "outputPath"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "ekran görüntüsü al",
      "screenshot al masaüstüne kaydet",
      "ekranın resmini çek"
    ],
    "whenNotToUse": [
      "Ekranda ne olduğunu ANLAMAK için analyze_screen kullan.",
      "Var olan görseli okumak için image_read kullan."
    ],
    "inputContract": {
      "required": [
        "outputPath"
      ],
      "properties": {
        "outputPath": {
          "type": "STRING"
        },
        "target": {
          "type": "STRING",
          "description": "screen | window | selection"
        },
        "format": {
          "type": "STRING",
          "description": "png | jpg"
        }
      },
      "additionalProperties": false,
      "target": "screen|window|selection",
      "format": "png|jpg"
    },
    "outputContract": {
      "kind": "artifact",
      "format": "image"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported.",
      "Permission or approval must be verified before the side effect runs."
    ],
    "liveNarration": [
      "Ekran görüntüsü alınıyor",
      "Görüntü kaydediliyor"
    ],
    "failureModes": [
      "SCREEN_RECORDING_PERMISSION_DENIED",
      "INVALID_OUTPUT_PATH",
      "CAPTURE_FAILED"
    ],
    "fewShots": [],
    "utterances": [],
    "notFor": [],
    "privacyClass": "local_private_write",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "send_whatsapp_message",
    "displayName": "WhatsApp mesajı",
    "description": "WhatsApp Desktop/Web üzerinden mesaj hazırlar veya gönderir (gönderim dışa dönük — onay gerekir).",
    "usage": "WhatsApp mesajı için. Alıcı belirsiz/numara bilinmiyorsa netleştir, uydurma. Kişi kaydı için save_whatsapp_contact.",
    "requiredArgs": [
      "message"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "WhatsApp mesajı için. Alıcı belirsiz/numara bilinmiyorsa netleştir, uydurma. Kişi kaydı için save_whatsapp_contact."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (message) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "message"
      ],
      "properties": {
        "recipient_name": {
          "type": "STRING",
          "description": "Alıcının kayıtlı adı. Numarası yoksa kişi rehberinden çözülür."
        },
        "phone_number": {
          "type": "STRING",
          "description": "Uluslararası numara (+90…). recipient_name yeterliyse boş bırak."
        },
        "message": {
          "type": "STRING",
          "description": "Gönderilecek mesaj metni."
        },
        "app_target": {
          "type": "STRING",
          "description": "Hedef: 'desktop' veya 'web'."
        },
        "send_now": {
          "type": "BOOLEAN",
          "description": "true → hemen gönder; false → yalnız hazırla."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "send_whatsapp_message",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported.",
      "Permission or approval must be verified before the side effect runs."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "Ahmet'e whatsapp'tan geç kalacağımı yaz",
      "şu kişiye mesaj at",
      "whatsapp'tan haber ver"
    ],
    "notFor": [
      "whatsapp nasıl kullanılır",
      "kişiyi rehbere kaydet",
      "e-posta gönder"
    ],
    "privacyClass": "permission_gated",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": true,
    "skillAffinity": []
  },
  {
    "name": "shell_run",
    "displayName": "Terminal komutu",
    "description": "Tek seferlik terminal komutu çalıştırır; her çağrı YENİ süreçtir, dizin ve ortam sonraki çağrıya taşınmaz.",
    "usage": "TEK ve bağımsız bir komut için: sürüm sor, tek script çalıştır, tek build tetikle. Ardışık komutlar gerekiyorsa shell_session_open ile oturum aç.",
    "requiredArgs": [
      "command"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "node --version gibi tek seferlik sorgu",
      "tek bir script'i çalıştır",
      "başka bir yetenekle yapılamayan tek komut"
    ],
    "whenNotToUse": [
      "Ardışık komutlar gerekiyorsa (cd → kur → test) shell_session_* kullan: shell_run her çağrıda dizini ve ortamı UNUTUR.",
      "Dosya okuma/yazma/taşıma için file_* yetenekleri daha güvenli ve doğrulanabilir.",
      "Git işlemleri için git_* yetenekleri kullan.",
      "Komutta &&, |, > gibi operatör varsa use_shell=true vermeden çağırma; aksi hâlde reddedilir."
    ],
    "inputContract": {
      "required": [
        "command"
      ],
      "properties": {
        "command": {
          "type": "STRING",
          "description": "Çalıştırılacak tek komut."
        },
        "mode": {
          "type": "STRING",
          "description": "read_only verilirse onay istemeden salt-okunur çalışır."
        },
        "timeout": {
          "type": "NUMBER",
          "description": "Saniye cinsinden üst sınır."
        },
        "use_shell": {
          "type": "BOOLEAN",
          "description": "Komut &&, ||, |, >, < veya ; içeriyorsa ZORUNLU true. Tek komutta gereksiz."
        },
        "working_dir": {
          "type": "STRING",
          "description": "Komutun çalışacağı dizin."
        },
        "riskOverride": {
          "type": "STRING",
          "description": "Kilit eylem sınıfı (upload/share/irreversible_delete...) beyanı."
        }
      },
      "additionalProperties": false,
      "commandMustBeConcrete": true,
      "workingDirRecommendedForProjectWork": true,
      "useShellRequiredWhenCommandContainsOperators": [
        "&&",
        "||",
        "|",
        ">",
        "<",
        ";"
      ]
    },
    "outputContract": {
      "kind": "shell_run",
      "primary": "command_result",
      "fields": [
        "stdout",
        "stderr",
        "exitCode"
      ]
    },
    "artifactContract": {},
    "verificationPlan": [
      "Exit code must be read; non-zero is a failure even when stdout is non-empty."
    ],
    "liveNarration": [
      "Komut çalıştırılıyor"
    ],
    "failureModes": [
      "PERMISSION_REQUIRED",
      "COMMAND_NOT_FOUND",
      "NON_ZERO_EXIT",
      "TIMEOUT"
    ],
    "fewShots": [
      {
        "user": "python sürümü kaç",
        "args": {
          "command": "python3 --version"
        }
      },
      {
        "user": "şu klasörde build al",
        "args": {
          "command": "npm run build",
          "working_dir": "~/Desktop/proje"
        }
      },
      {
        "user": "kur ve test et",
        "args": {
          "command": "npm ci && npm test",
          "use_shell": true
        }
      }
    ],
    "utterances": [
      "npm install çalıştır",
      "şu komutu terminalde koştur",
      "terminal komutu çalıştır",
      "script çalıştır"
    ],
    "notFor": [
      "terminal nedir",
      "komut çalıştırmadan anlat"
    ],
    "privacyClass": "permission_gated",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "destructive",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "shell_session_close",
    "displayName": "Terminal oturumu kapatma",
    "description": "Terminal oturumunu kapatır ve kaynakları serbest bırakır.",
    "usage": "Çok adımlı iş bitince oturumu kapat. Terminal UYGULAMASINI kapatmaz.",
    "requiredArgs": [
      "session_id"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "iş bitti, oturumu serbest bırak"
    ],
    "whenNotToUse": [
      "Kullanıcı 'terminali kapat' derken görünür uygulamayı kastediyorsa close_app kullan.",
      "Aynı işte hâlâ komut çalıştıracaksan oturumu kapatma."
    ],
    "inputContract": {
      "required": [
        "session_id"
      ],
      "properties": {
        "session_id": {
          "type": "STRING"
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "shell_session_close",
      "primary": "closed"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Terminal oturumu kapatılıyor"
    ],
    "failureModes": [
      "UNKNOWN_SESSION"
    ],
    "fewShots": [],
    "utterances": [
      "açtığın kabuk oturumunu sonlandır",
      "çalışan komut oturumunu bitir"
    ],
    "notFor": [
      "Terminal uygulamasını kapat",
      "terminali kapat"
    ],
    "privacyClass": "local_session_control",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "none",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "shell_session_open",
    "displayName": "Terminal oturumu açma",
    "description": "Kalıcı terminal oturumu açar; çalışma dizini, ortam değişkenleri ve kabuk durumu sonraki komutlarda KORUNUR.",
    "usage": "Çok adımlı yazılım işinin İLK adımı: derle/test/düzelt döngüsü, sanal ortam kurup içinde çalışma, arka arkaya komut. Dönen sessionId sonraki adımlara verilir.",
    "requiredArgs": [],
    "requiresApproval": true,
    "whenToUse": [
      "projede testleri çalıştırıp hatayı düzelt",
      "bağımlılıkları kur sonra derle",
      "arka arkaya birkaç komut gerekiyor"
    ],
    "whenNotToUse": [
      "Tek bir komut yetiyorsa shell_run daha ucuz — oturum açma/kapatma yükü gereksizdir.",
      "Terminal UYGULAMASINI açmak istiyorsan open_app kullan; bu yetenek görünür bir pencere açmaz."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "working_dir": {
          "type": "STRING"
        },
        "root": {
          "type": "STRING"
        }
      },
      "additionalProperties": false,
      "workingDirRecommended": true
    },
    "outputContract": {
      "kind": "shell_session_open",
      "primary": "session_id",
      "fields": [
        "sessionId",
        "workingDir"
      ]
    },
    "artifactContract": {},
    "verificationPlan": [
      "Returned sessionId must be passed to every following shell_session_run step."
    ],
    "liveNarration": [
      "Terminal oturumu açılıyor"
    ],
    "failureModes": [
      "SESSION_LIMIT_REACHED",
      "WORKING_DIR_MISSING"
    ],
    "fewShots": [
      {
        "args": {
          "working_dir": "~/projeler/elyan"
        }
      }
    ],
    "utterances": [
      "kalıcı terminal oturumu aç",
      "çalışma dizini korunsun bir kabuk başlat"
    ],
    "notFor": [],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "write",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "shell_session_run",
    "displayName": "Terminal oturumunda komut",
    "description": "Açık oturumda komut çalıştırır; dizin ve ortam korunur, çıkış kodu ve çıktı döner.",
    "usage": "Aynı oturumda ardışık komutlar: cd ile konumlan, kur, çalıştır, çıktıyı oku, düzelt, tekrar çalıştır. sessionId shell_session_open'dan gelir.",
    "requiredArgs": [
      "session_id",
      "command"
    ],
    "requiresApproval": true,
    "whenToUse": [
      "testi çalıştır ve çıktısını oku",
      "önceki adımda girdiğim dizinde devam et",
      "hatayı düzelttim, tekrar çalıştır"
    ],
    "whenNotToUse": [
      "Oturum yoksa önce shell_session_open çağır; sessionId uydurma.",
      "Tek seferlik bağımsız komut için shell_run yeterli.",
      "Dizin değiştirmek için `cd` AYRI bir adım olmalı: 'cd x && komut' oturumun dizinini kalıcı değiştirmez."
    ],
    "inputContract": {
      "required": [
        "session_id",
        "command"
      ],
      "properties": {
        "session_id": {
          "type": "STRING"
        },
        "command": {
          "type": "STRING"
        },
        "timeout": {
          "type": "NUMBER"
        }
      },
      "additionalProperties": false,
      "sessionIdMustComeFromOpenStep": true
    },
    "outputContract": {
      "kind": "shell_session_run",
      "primary": "command_result",
      "fields": [
        "stdout",
        "stderr",
        "exitCode",
        "workingDir"
      ]
    },
    "artifactContract": {},
    "verificationPlan": [
      "Exit code must be read before claiming success.",
      "Failing output must be shown, not summarised away."
    ],
    "liveNarration": [
      "Oturumda komut çalıştırılıyor"
    ],
    "failureModes": [
      "PERMISSION_REQUIRED",
      "UNKNOWN_SESSION",
      "NON_ZERO_EXIT",
      "TIMEOUT"
    ],
    "fewShots": [
      {
        "user": "testleri çalıştır",
        "args": {
          "session_id": "<open adımından gelen>",
          "command": "pytest -q"
        }
      }
    ],
    "utterances": [
      "aynı terminalde testleri koştur",
      "açık oturumda şu komutu çalıştır"
    ],
    "notFor": [],
    "privacyClass": "local_private_action",
    "sideEffect": true,
    "mutatesPath": false,
    "sideEffectClass": "destructive",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "speech_capture",
    "displayName": "Ses kaydı",
    "description": "Yerel mikrofondan kısa ses kaydı başlatır veya durdurur.",
    "usage": "Sesli not/dikte almak için kaydı başlatıp durdurma. Kaydı metne çevirmek için speech_to_text.",
    "requiredArgs": [
      "action"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Sesli not/dikte almak için kaydı başlatıp durdurma. Kaydı metne çevirmek için speech_to_text."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (action) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "action"
      ],
      "properties": {
        "action": {
          "type": "STRING",
          "description": "'start' (kaydı başlat) veya 'stop' (durdur)."
        },
        "_uiGesture": {
          "type": "BOOLEAN",
          "description": "Kullanıcı jestiyle tetiklendi (dahili)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "speech_capture",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "mikrofonu aç kayıt başlat",
      "ses kaydını durdur"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "none",
    "executionAuthority": "desktop",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "speech_to_text",
    "displayName": "Sesten metne",
    "description": "Yerel ses kaydını metne çevirir (dikte).",
    "usage": "Ses kaydını yazıya dökmek için. Yazıyı sese çevirmek için text_to_speech.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [
      "Ses kaydını yazıya dökmek için. Yazıyı sese çevirmek için text_to_speech."
    ],
    "whenNotToUse": [
      "Do not use when this capability does not directly advance the requested outcome."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "audioPath": {
          "type": "STRING",
          "description": "Çevrilecek ses dosyası yolu (varsa)."
        },
        "sessionId": {
          "type": "STRING",
          "description": "Kayıt oturumu kimliği (varsa)."
        },
        "languageHint": {
          "type": "STRING",
          "description": "Konuşma dili ipucu, örn. 'tr'."
        },
        "taskId": {
          "type": "STRING",
          "description": "İlişkili görev kimliği (varsa)."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "speech_to_text",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "ses kaydını yazıya dök",
      "bu kaydı metne çevir",
      "dikte ettiğimi yaz"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "spreadsheet_write",
    "displayName": "Tablo oluşturma",
    "description": "Verilen HAZIR satır/sütun verisini XLSX/Excel çalışma kitabına yazar. Veri ÜRETMEZ.",
    "usage": "Excel, xlsx, tablo, bütçe, hesap dökümü, karşılaştırma matrisi veya satır/sütunlu çıktı istendiğinde.",
    "requiredArgs": [],
    "requiresApproval": true,
    "whenToUse": [
      "excele dönüştür",
      "tablo yap",
      "hesapları Excel'e yaz",
      "satış/muhasebe verisi için çalışma sayfası üret"
    ],
    "whenNotToUse": [
      "Paragraflı rapor için document_write/canvas_write kullan.",
      "Grafik görseli tek başına isteniyorsa chart_generate kullan."
    ],
    "inputContract": {
      "required": [],
      "properties": {
        "prompt": {
          "type": "STRING",
          "description": "Sayfaya YAZILACAK hazır metin/veri. Konu/talimat DEĞİL."
        },
        "outputPath": {
          "type": "STRING"
        },
        "title": {
          "type": "STRING"
        },
        "columns": {
          "type": "ARRAY"
        },
        "rows": {
          "type": "ARRAY"
        },
        "sourceContext": {
          "type": "STRING"
        },
        "overwrite": {
          "type": "BOOLEAN",
          "description": "Üzerine yaz."
        },
        "sheets": {
          "type": "ARRAY"
        }
      },
      "additionalProperties": false,
      "structuredInputs": [
        "sheets",
        "columns",
        "rows"
      ],
      "calculationReferences": "math_solve outputs belong in rows/cells via {{steps.<id>.output}}"
    },
    "outputContract": {
      "kind": "spreadsheet_write",
      "primary": "artifact",
      "formats": [
        "xlsx"
      ]
    },
    "artifactContract": {
      "artifactTypes": [
        "spreadsheet"
      ],
      "extension": ".xlsx"
    },
    "verificationPlan": [
      "Check XLSX artifact exists.",
      "Rows/sheets must be concrete, not prose-only."
    ],
    "liveNarration": [
      "Tablo yapısı kuruluyor",
      "Excel satırları yazılıyor",
      "Çalışma kitabı doğrulanıyor"
    ],
    "failureModes": [
      "INVALID_ROWS",
      "INVALID_OUTPUT_PATH",
      "DEPENDENCY_UNAVAILABLE"
    ],
    "fewShots": [
      {
        "args": {
          "title": "Aylık Bütçe",
          "columns": "{{steps.analiz.result.columns}}",
          "rows": "{{steps.analiz.result.previewRows}}"
        }
      }
    ],
    "utterances": [
      "excel tablosu oluştur",
      "xlsx olarak kaydet",
      "bu verileri bir çalışma kitabına yaz",
      "excel hazırla",
      "tablo oluştur",
      "xlsx yap"
    ],
    "notFor": [
      "verinin grafiğini çiz",
      "excel nedir",
      "tabloyu oku ve analiz et"
    ],
    "privacyClass": "local_private_write",
    "sideEffect": true,
    "mutatesPath": true,
    "sideEffectClass": "write",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": [
      "spreadsheet.table_from_context"
    ]
  },
  {
    "name": "sys_info",
    "displayName": "Sistem bilgisi",
    "description": "Sistem bilgisi alır: pil, CPU, RAM, disk, saat, tarih, ağ.",
    "usage": "Bilgisayarın anlık durumunu/saati sorulduğunda. Çalışan uygulamalar için desktop_os.processes.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Bilgisayarın anlık durumunu/saati sorulduğunda. Çalışan uygulamalar için desktop_os.processes."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (query) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "query"
      ],
      "properties": {
        "query": {
          "type": "STRING",
          "description": "Hangi bilgi: 'pil', 'saat', 'disk', 'ram', 'ağ' vb."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "sys_info",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [
      {
        "args": {
          "query": "pil durumu"
        }
      }
    ],
    "utterances": [
      "pil yüzde kaç",
      "diskte ne kadar yer kalmış",
      "bilgisayarın RAM'i ne durumda",
      "saat kaç",
      "battery status"
    ],
    "notFor": [
      "bilgisayar nasıl hızlandırılır",
      "açık uygulamaları listele"
    ],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "desktop",
    "questionSafeObservation": true,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "text_analyze",
    "displayName": "Metin analizi",
    "description": "Okunan/araştırılan/hesaplanan içeriği profesyonel muhakeme özeti, karar, risk veya rapor planına dönüştürür.",
    "usage": "read/research/math çıktılarını belge/tablo/sunum yazmadan önce analiz etmek için. Sadece format export için writer yeterliyse atlanabilir.",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "analiz et",
      "yorumla",
      "riskleri çıkar",
      "rapor yapmadan önce değerlendir"
    ],
    "whenNotToUse": [
      "Sadece basit hesap için math_solve kullan.",
      "Sadece dosya okuma için document_read/file_read kullan."
    ],
    "inputContract": {
      "required": [
        "prompt"
      ],
      "properties": {
        "prompt": {
          "type": "STRING"
        },
        "sourceContext": {
          "type": "STRING"
        },
        "mode": {
          "type": "STRING"
        }
      },
      "additionalProperties": false,
      "sourceContextRecommended": true
    },
    "outputContract": {
      "kind": "text_analyze",
      "primary": "analysis"
    },
    "artifactContract": {},
    "verificationPlan": [
      "Analysis must answer the requested lens and preserve source facts."
    ],
    "liveNarration": [
      "Veri analiz ediliyor",
      "Sonuçlar yapılandırılıyor"
    ],
    "failureModes": [
      "EMPTY_SOURCE",
      "INSUFFICIENT_CONTEXT"
    ],
    "fewShots": [],
    "utterances": [
      "bulguları karar odaklı özete çevir",
      "bunu profesyonel bir değerlendirmeye dönüştür",
      "riskleri çıkar ve yorumla"
    ],
    "notFor": [],
    "privacyClass": "local_or_server_context",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "text_to_speech",
    "displayName": "Metinden sese",
    "description": "Metni yerel olarak sesli okur.",
    "usage": "Bir metni/cevabı sesli okutmak için.",
    "requiredArgs": [
      "text"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "Bir metni/cevabı sesli okutmak için."
    ],
    "whenNotToUse": [
      "Do not use when required inputs (text) are missing or ambiguous."
    ],
    "inputContract": {
      "required": [
        "text"
      ],
      "properties": {
        "text": {
          "type": "STRING",
          "description": "Sesli okunacak metin."
        },
        "languageHint": {
          "type": "STRING",
          "description": "Dil ipucu, örn. 'tr'."
        },
        "voice": {
          "type": "STRING",
          "description": "Ses/tını adı (varsa)."
        },
        "interrupt": {
          "type": "BOOLEAN",
          "description": "Süren okumayı kesip yeniden başla."
        }
      },
      "additionalProperties": false
    },
    "outputContract": {
      "kind": "structured_result",
      "capability": "text_to_speech",
      "requiresOk": true
    },
    "artifactContract": {},
    "verificationPlan": [
      "Structured result must return ok=true before success is reported."
    ],
    "liveNarration": [
      "Capability is running.",
      "Result is being verified."
    ],
    "failureModes": [
      "INVALID_INPUT",
      "DEPENDENCY_UNAVAILABLE",
      "TIMEOUT"
    ],
    "fewShots": [],
    "utterances": [
      "bu metni sesli oku",
      "yüksek sesle okur musun"
    ],
    "notFor": [],
    "privacyClass": "local_runtime",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  },
  {
    "name": "web_research",
    "displayName": "Web araştırması",
    "description": "Public web kaynaklarından araştırma özeti ve kaynak listesi üretir.",
    "usage": "Güncel/dış/public bilgi gerektiğinde. Özel dosya/metin içeriğini query'ye koyma; önce public arama, sonra private analiz/yazımda birleştir.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false,
    "whenToUse": [
      "güncel bilgi araştır",
      "kaynaklı rapor hazırla",
      "public mevzuat/teknoloji/pazar bilgisi bul"
    ],
    "whenNotToUse": [
      "Kullanıcının özel dosyasını analiz etmek için document_read/text_analyze kullan.",
      "Yerel geçmiş/çalışma alanı için retrieve_context kullan."
    ],
    "inputContract": {
      "required": [
        "query"
      ],
      "properties": {
        "query": {
          "type": "STRING"
        },
        "max_results": {
          "type": "NUMBER"
        },
        "language_hint": {
          "type": "STRING"
        }
      },
      "additionalProperties": false,
      "queryMustBePublic": true,
      "maxPrivateData": "none"
    },
    "outputContract": {
      "kind": "web_research",
      "primary": "research_summary",
      "fields": [
        "summary",
        "sources"
      ]
    },
    "artifactContract": {},
    "verificationPlan": [
      "Result must include a non-empty summary and source evidence when available."
    ],
    "liveNarration": [
      "Kaynaklar araştırılıyor",
      "Bulgular özetleniyor"
    ],
    "failureModes": [
      "NETWORK_UNAVAILABLE",
      "NO_SOURCES",
      "TIMEOUT"
    ],
    "fewShots": [
      {
        "args": {
          "query": "2025 elektrikli araç pazar payı",
          "language_hint": "tr"
        }
      }
    ],
    "utterances": [
      "bu konuyu internetten araştır ve kaynak ver",
      "kuantum bilgisayarlar hakkında kaynak topla",
      "güncel bilgileri webden derle",
      "research this topic with sources",
      "web araştır",
      "internet kaynakları",
      "public research"
    ],
    "notFor": [
      "tarayıcıda siteyi aç",
      "yerel dosyalarda ara",
      "internete bakma kendi bilginle cevapla"
    ],
    "privacyClass": "public_web",
    "sideEffect": false,
    "mutatesPath": false,
    "sideEffectClass": "read",
    "executionAuthority": "hybrid",
    "questionSafeObservation": false,
    "fallbackExecutionEligible": false,
    "skillAffinity": []
  }
];
