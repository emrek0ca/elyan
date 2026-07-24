// ÜRETİLEN DOSYA — ELLE DÜZENLEME.
// Kaynak: elyan-desktop runtime/capability_registry.TOOL_DECLARATIONS.
// Yeniden üretim: venv/bin/python scripts/export_capability_manifest.py <bu dosya>
// Sunucu-materyalize planlayıcı desktop'un TAM kataloğunu bu manifest'ten
// okur; onay gerektirenler desktop tarafında yine onaya takılır (güvenlik
// sınırı desktop'tadır — manifest yalnız planlama kelime dağarcığıdır).

export type DesktopCapabilityManifestEntry = {
  name: string;
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
  privacyClass: string;
  skillAffinity: string[];
};

export const DESKTOP_CAPABILITY_MANIFEST: DesktopCapabilityManifestEntry[] = [
  {
    "name": "add_calendar_event",
    "description": "Apple Calendar takvimine yeni etkinlik ekler.",
    "usage": "Takvime etkinlik eklerken. Tarihi HER ZAMAN mutlak ISO'ya çevir; belirsizse netleştir.",
    "requiredArgs": [
      "title",
      "start_iso"
    ],
    "requiresApproval": true,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "add_reminder",
    "description": "Apple Reminders'a yeni hatırlatıcı ekler.",
    "usage": "Hatırlatıcı/yapılacak eklerken. Tarih varsa mutlak ISO'ya çevir.",
    "requiredArgs": [
      "title"
    ],
    "requiresApproval": true,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "analyze_screen",
    "description": "Aktif pencereyi kullanıcı sorusuna göre görsel olarak analiz eder; basit 'ekranda ne var' cevabı üretir.",
    "usage": "Kullanıcı ekranda ne olduğunu, aktif pencerede ne yazdığını veya görünen hata/uyarıyı sorduğunda. Tıklama/yazma için desktop_operator.run.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false,
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
      "target": "active_window only in v1"
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
    "privacyClass": "local_private_screen",
    "skillAffinity": []
  },
  {
    "name": "browser_agent.run",
    "description": "Tarayıcıda hedefi KENDİ gözleyip karar vererek adım adım gerçekleştiren ajan: sayfayı gözler, tıklar, yazar, veri toplar, dosya indirir; hedef bitince özet ve toplanan verileri döndürür.",
    "usage": "Sayfa yapısı önceden bilinmeyen çok adımlı tarayıcı görevlerinde TEK adım olarak kullan. Adımları kendin yazabiliyorsan browser_session.* daha hızlıdır; buradaki ajan keşif gerektiren işler içindir.",
    "requiredArgs": [
      "goal"
    ],
    "requiresApproval": true,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "browser_control",
    "description": "Tarayıcıda bir URL açar, web araması yapar, YouTube'da video açar veya yeni sekme açar.",
    "usage": "Web adresi açma/arama/YouTube/yeni sekme için. 'Yeni sekme aç' isteği action='new_tab'tır — 'yeni sekme' metnini ASLA aramaya çevirme. Uygulamanın kendisini açmak için open_app kullan.",
    "requiredArgs": [
      "action"
    ],
    "requiresApproval": true,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "browser_session.click",
    "description": "Oturumdaki sayfada bir öğeye tıklar (CSS selector, görünür metin ya da rol+metin ile).",
    "usage": "browser_session.snapshot ile öğeleri gördükten sonra hedefe tıklamak.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "browser_session.close",
    "description": "Kalıcı tarayıcı oturumunu kapatır.",
    "usage": "Çok adımlı tarayıcı işi bittiğinde temizlik.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "browser_session.download",
    "description": "Sayfadan dosya indirir (indirme başlatan öğeye tıklayarak ya da doğrudan URL ile) ve dosya yolunu döndürür.",
    "usage": "Transcript/rapor/dosya indirme adımlarında; dönen outputPath sonraki file_move adımına verilir.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "browser_session.extract",
    "description": "Sayfadan yapılandırılmış veri çıkarır: selector eşleşmelerinin metni ve istenirse bir attribute'u (ör. href). Selector verilmezse sayfanın okunur metnini döndürür.",
    "usage": "Liste toplama işlerinde: video linkleri, başlıklar, tablo hücreleri. Sonuç result.items listesindedir; sonraki adımlar {{steps.<id>.result.items}} ile kullanır.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "browser_session.goto",
    "description": "Kalıcı tarayıcı oturumunda bir adrese gider; sonraki adımlar AYNI sayfada devam eder.",
    "usage": "Çok adımlı tarayıcı işlerinde (gez → tıkla → çıkar → indir) ilk adım. Tek seferlik 'URL aç ve bırak' için browser_control kullan.",
    "requiredArgs": [
      "url"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "browser_session.snapshot",
    "description": "Sayfanın etkileşimli öğelerini (link/buton/alan, metinleriyle) listeler — sonraki tıklama/yazma adımını doğru hedefe yöneltmek için gözlem.",
    "usage": "Sayfanın yapısı bilinmiyorken tıklamadan ÖNCE gözlem almak.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "browser_session.type",
    "description": "Oturumdaki sayfada bir alana metin yazar; submit=true ile Enter'a basar. Şifre alanlarına yazmaz.",
    "usage": "Arama kutusu doldurma, form alanına URL yapıştırma gibi işlerde.",
    "requiredArgs": [
      "value"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "canvas_write",
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
    "privacyClass": "local_private_write",
    "skillAffinity": [
      "document.pdf_report",
      "canvas.visual_report"
    ]
  },
  {
    "name": "chart_generate",
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
    "fewShots": [],
    "privacyClass": "local_private_write",
    "skillAffinity": []
  },
  {
    "name": "clipboard_read",
    "description": "Panodaki (clipboard) metni okur.",
    "usage": "Kullanıcı 'panodakini/kopyaladığımı' işleme dediğinde.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "clipboard_write",
    "description": "Verilen metni panoya (clipboard) kopyalar.",
    "usage": "Bir sonucu/metni kullanıcının yapıştırabilmesi için panoya koymak.",
    "requiredArgs": [
      "text"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "close_app",
    "description": "Çalışan bir masaüstü uygulamasını kapatır.",
    "usage": "Kullanıcı bir uygulamayı kapatmak istediğinde.",
    "requiredArgs": [
      "app_name"
    ],
    "requiresApproval": true,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "data_analyze",
    "description": "CSV, JSON veya Excel verisini yerel olarak analiz eder (özet/profil/önizleme).",
    "usage": "Bir veri dosyasını anlamak/özetlemek için. Grafik çizmek için chart_generate.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "delete_calendar_event",
    "description": "Apple Calendar takviminden etkinlik siler (geri alınamaz — onay gerekir).",
    "usage": "Etkinlik silmek için. Yanlış silmemek için start_iso ile daralt.",
    "requiredArgs": [
      "title"
    ],
    "requiresApproval": true,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "delete_memory",
    "description": "Kalıcı hafızadan bir kaydı siler.",
    "usage": "Kullanıcı 'şunu unut/hatırlama' dediğinde.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "desktop_operator.cancel",
    "description": "Aktif ekran otomasyonu çalışmasını güvenli şekilde durdurur.",
    "usage": "Takılan/istenmeyen bir operator çalışmasını durdurmak için.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "desktop_operator.execute_action",
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
    "privacyClass": "local_private_action",
    "skillAffinity": []
  },
  {
    "name": "desktop_operator.focus_window",
    "description": "Bir masaüstü uygulamasını öne alır.",
    "usage": "Bir uygulamayı öne getirmek için. Uygulamayı açmak için open_app.",
    "requiredArgs": [],
    "requiresApproval": true,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "desktop_operator.locate",
    "description": "Metin veya öğe tipine göre ekrandaki hedef öğeyi bulur (operator alt-adımı).",
    "usage": "İleri ekran otomasyonu alt-adımı; genelde desktop_operator.run içinde.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "desktop_operator.observe_screen",
    "description": "Operator için yapılandırılmış ekran gözlemi üretir; sonraki UI eylemini güvenli seçmek için kullanılır.",
    "usage": "Ekran-eylem planında her kritik tıklama/yazma öncesi ve sonrası durum görmek için.",
    "requiredArgs": [],
    "requiresApproval": false,
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
    "privacyClass": "local_private_screen",
    "skillAffinity": []
  },
  {
    "name": "desktop_operator.run",
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
    "fewShots": [],
    "privacyClass": "local_private_action",
    "skillAffinity": []
  },
  {
    "name": "desktop_os.active_window",
    "description": "Şu an öndeki (aktif) pencere bilgisini döndürür.",
    "usage": "Kullanıcının o an hangi uygulamada olduğunu öğrenmek için.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "desktop_os.open_permission_settings",
    "description": "İlgili sistem izin ekranını güvenli şekilde açar.",
    "usage": "Bir izin eksikse kullanıcıyı doğru sistem ayar ekranına yönlendirmek için.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "desktop_os.permissions",
    "description": "Masaüstü izin modelini ve izin hazırlık (readiness) durumunu döndürür.",
    "usage": "Hangi sistem izinlerinin verildiğini görmek için. İzin ekranını açmak için desktop_os.open_permission_settings.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "desktop_os.processes",
    "description": "Çalışan uygulamaları/prosesleri güvenli şekilde listeler.",
    "usage": "Hangi uygulamaların açık olduğunu görmek için. Genel sistem bilgisi için sys_info.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "desktop_os.status",
    "description": "Masaüstü OS yetenek ve native entegrasyon durumunu döndürür.",
    "usage": "Masaüstünün hangi yeteneklerinin hazır olduğunu kontrol ederken (tanılama).",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "directory_tree",
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
    "privacyClass": "local_private_read",
    "skillAffinity": []
  },
  {
    "name": "document_read",
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
    "privacyClass": "local_private_read",
    "skillAffinity": []
  },
  {
    "name": "document_write",
    "description": "DOCX/Word belgesi üretir; metin, bölüm, tablo, grafik ve görsel bloklarını düzenli belgeye yazar.",
    "usage": "Word/DOCX, dilekçe, rapor, yazı, taslak, not veya profesyonel belge istendiğinde. PDF için canvas_write, Excel için spreadsheet_write, sunum için presentation_write.",
    "requiredArgs": [],
    "requiresApproval": true,
    "whenToUse": [
      "savunma dilekçesi hazırla",
      "rapor yaz ve docx kaydet",
      "okunan metni Word belgesi yap"
    ],
    "whenNotToUse": [
      "PDF isteniyorsa canvas_write kullan.",
      "Sunum/slayt isteniyorsa presentation_write kullan.",
      "Tablo/xlsx isteniyorsa spreadsheet_write kullan."
    ],
    "inputContract": {
      "contentFields": [
        "prompt",
        "sections",
        "blocks",
        "sourceContext",
        "sourcePath"
      ],
      "mustUsePriorOutputs": "research/read/analysis outputs go into sourceContext or prompt"
    },
    "outputContract": {
      "kind": "document_write",
      "primary": "artifact",
      "formats": [
        "docx"
      ]
    },
    "artifactContract": {
      "artifactTypes": [
        "document"
      ],
      "extension": ".docx",
      "mobileBlocksRemainCanonical": true
    },
    "verificationPlan": [
      "Check DOCX artifact exists.",
      "Writer args must contain concrete content or a prior-step reference."
    ],
    "liveNarration": [
      "Belge içeriği düzenleniyor",
      "DOCX dosyası oluşturuluyor",
      "Belge çıktısı doğrulanıyor"
    ],
    "failureModes": [
      "EMPTY_DOCUMENT",
      "INVALID_OUTPUT_PATH",
      "DEPENDENCY_UNAVAILABLE"
    ],
    "fewShots": [],
    "privacyClass": "local_private_write",
    "skillAffinity": [
      "document.docx_from_context",
      "document.summary_and_save"
    ]
  },
  {
    "name": "email_draft",
    "description": "E-posta taslağı hazırlar (göndermez — kullanıcı onayına sunulur).",
    "usage": "E-posta yazmak için. Taslak onaydan sonra email_send ile gönderilir. Alıcı belirsizse netleştir.",
    "requiredArgs": [
      "to"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "email_send",
    "description": "Onaylı e-postayı GÖNDERİR (geri alınamaz — açık onay gerekir).",
    "usage": "Genelde email_draft ile taslak hazırlanıp onaydan sonra gönderilir. Doğrudan gönderim geri alınamaz.",
    "requiredArgs": [
      "to",
      "subject",
      "body"
    ],
    "requiresApproval": true,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "file_move",
    "description": "Dosyayı başka bir konuma taşır (hedef klasörse içine).",
    "usage": "İndirilen dosyaları kullanıcının istediği klasöre toplamak.",
    "requiredArgs": [
      "source",
      "destination"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "file_patch",
    "description": "Var olan bir dosyada çıpalı bul/değiştir uygular (old_string → new_string).",
    "usage": "Bir dosyanın küçük bir bölümünü değiştirmek için. Tüm dosyayı yeniden yazmak için file_write.",
    "requiredArgs": [
      "path",
      "old_string"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "file_read",
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
    "fewShots": [],
    "privacyClass": "local_private_read",
    "skillAffinity": []
  },
  {
    "name": "file_search",
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
      "Web bilgisi için web_research kullan."
    ],
    "inputContract": {
      "required": [
        "query"
      ],
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
    "fewShots": [],
    "privacyClass": "local_private_read",
    "skillAffinity": []
  },
  {
    "name": "file_write",
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
    "privacyClass": "local_private_write",
    "skillAffinity": []
  },
  {
    "name": "get_calendar_events",
    "description": "Apple Calendar takvimini okur (etkinlikleri listeler).",
    "usage": "Kullanıcı takvimini/programını sorduğunda. Yeni etkinlik için add_calendar_event.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "get_reminders",
    "description": "Apple Reminders listesini okur.",
    "usage": "Hatırlatıcıları/yapılacakları görüntülerken. Yeni öğe için add_reminder.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "get_weather",
    "description": "Anlık hava durumunu özetler.",
    "usage": "Hava durumu sorulduğunda.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "get_youtube_channel_report",
    "description": "YouTube kanal istatistiklerini ve son video performansını raporlar.",
    "usage": "Bir YouTube kanalının performansını özetlerken.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "git_branch",
    "description": "Yeni bir git branch'i oluşturur (varsayılan: oluşturup geçer).",
    "usage": "Ana dalda çalışmadan önce yeni bir dal açarken.",
    "requiredArgs": [
      "name"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "git_commit",
    "description": "Değişiklikleri commit'ler (opsiyonel git add -A). PUSH YAPMAZ.",
    "usage": "Değişiklikleri kaydederken. Push YAPMAZ (güvenlik). Yeni dal için git_branch.",
    "requiredArgs": [
      "message"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "git_diff",
    "description": "Bir git deposundaki çalışma ağacı veya staged farkını (diff) döndürür.",
    "usage": "Kod değişikliklerinin detayını görmek için.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "git_status",
    "description": "Bir git deposunun durumunu (branch + staged/unstaged/untracked) döndürür.",
    "usage": "Bir repoda hangi değişiklikler var diye bakarken.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "image_edit",
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
        "prompt"
      ],
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
    "fewShots": [],
    "privacyClass": "external_model_optional",
    "skillAffinity": []
  },
  {
    "name": "image_fetch",
    "description": "Herkese açık bir kaynaktan (Openverse/Wikimedia) bir konu için görsel indirir ve kullanıcının klasörüne (varsayılan masaüstü) kaydeder.",
    "usage": "Web'den hazır/telifsiz görsel indirmek için. Sıfırdan görsel üretmek için image_generate.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "image_generate",
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
    "fewShots": [],
    "privacyClass": "external_model_optional",
    "skillAffinity": []
  },
  {
    "name": "image_read",
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
    "privacyClass": "local_private_read",
    "skillAffinity": []
  },
  {
    "name": "latex_parse",
    "description": "LaTeX matematik ifadesini yerel sembolik forma çevirir/normalize eder.",
    "usage": "LaTeX'i işlerken. Sayısal çözüm için math_solve.",
    "requiredArgs": [
      "expression"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "make_directory",
    "description": "Klasör oluşturur (üst klasörler dahil; varsa hata vermez).",
    "usage": "İndirilen/üretilen dosyaları toplamadan önce hedef klasörü hazırlamak veya kullanıcının istediği klasörü açmak.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "math_solve",
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
    "fewShots": [],
    "privacyClass": "local_safe_compute",
    "skillAffinity": [
      "math.solve"
    ]
  },
  {
    "name": "mcp_call_tool",
    "description": "Bağlı bir MCP sunucusundaki aracı çağırır (harici entegrasyonlar).",
    "usage": "Yerleşik yeteneklerin karşılamadığı, kullanıcının bağladığı bir MCP aracı gerektiğinde.",
    "requiredArgs": [
      "serverId",
      "toolName"
    ],
    "requiresApproval": true,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "ocr_read",
    "description": "Görsel veya taranmış PDF sayfasındaki metni OCR ile çıkarır.",
    "usage": "Fotoğraf/ekran görüntüsü/taranmış belgedeki YAZIYI okumak için. Seçilebilir metinli belge için document_read.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "open_app",
    "description": "Yerel bir masaüstü uygulamasını açar (Safari, Chrome, Notlar, Spotify…).",
    "usage": "Kullanıcı bir uygulamayı açmak istediğinde. URL/arama için browser_control, medya için play_media kullan.",
    "requiredArgs": [
      "app_name"
    ],
    "requiresApproval": true,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "play_media",
    "description": "YouTube, Spotify veya Apple Music ile şarkı/çalma listesi oynatır.",
    "usage": "Müzik/video çalmak için. Sadece uygulamayı açmak için open_app kullan.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": true,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "presentation_write",
    "description": "PPTX/PowerPoint sunum üretir; araştırma/analiz çıktısını slaytlara böler.",
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
    "fewShots": [],
    "privacyClass": "local_private_write",
    "skillAffinity": [
      "presentation.deck_from_context"
    ]
  },
  {
    "name": "quantum_compare_classical",
    "description": "Kuantum demo sonucunu klasik baseline ile karşılaştırır.",
    "usage": "Kuantum sonucunu klasik yöntemle kıyaslarken.",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "quantum_generate_report",
    "description": "Kuantum deney akışı için teknik rapor ve metrik artifact üretir.",
    "usage": "Kuantum deney akışının sonunda özet rapor üretmek için.",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "quantum_model_problem",
    "description": "Optimizasyon problemini QUBO/Ising demo modeline dönüştürür.",
    "usage": "Kuantum/optimizasyon demo akışının ilk adımı; ardından quantum_run_experiment.",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "quantum_run_experiment",
    "description": "QAOA/VQE simülatör demo deneyini yürütür.",
    "usage": "Kuantum demo deneyi çalıştırmak için (Qiskit/Aer gerekir).",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "retrieve_context",
    "description": "Yerel çalışma alanı ve konuşmalardan bağlam eşleşmeleri döndürür (çevrimdışı).",
    "usage": "Yerel/geçmiş bilgi gerektiğinde veya web erişilemediğinde. Güncel dış bilgi için web_research.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "run_skill",
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
    "privacyClass": "local_private_mixed",
    "skillAffinity": []
  },
  {
    "name": "save_memory",
    "description": "Kullanıcı hakkında kalıcı bir tercih/olgu kaydeder (sonraki oturumlarda hatırlanır).",
    "usage": "Kullanıcı 'bunu hatırla/aklında tut' dediğinde kalıcı tercih/olgu kaydetmek için.",
    "requiredArgs": [
      "key",
      "value"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "save_whatsapp_contact",
    "description": "WhatsApp kişisini kalıcı kaydeder (sonraki mesajlarda adla çözülür).",
    "usage": "Bir kişiyi ilerideki WhatsApp mesajları için kaydetmek üzere.",
    "requiredArgs": [
      "display_name",
      "phone_number"
    ],
    "requiresApproval": true,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "send_whatsapp_message",
    "description": "WhatsApp Desktop/Web üzerinden mesaj hazırlar veya gönderir (gönderim dışa dönük — onay gerekir).",
    "usage": "WhatsApp mesajı için. Alıcı belirsiz/numara bilinmiyorsa netleştir, uydurma. Kişi kaydı için save_whatsapp_contact.",
    "requiredArgs": [
      "message"
    ],
    "requiresApproval": true,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "shell_run",
    "description": "Yerel terminal komutu çalıştırır (güçlü — açık onay gerekir).",
    "usage": "Yalnız başka yetenek yokken. Dosya işlemleri için file_* , git için git_* yeteneklerini tercih et.",
    "requiredArgs": [
      "command"
    ],
    "requiresApproval": true,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "shell_session_close",
    "description": "Terminal oturumunu kapatır.",
    "usage": "İş bitince oturumu serbest bırak.",
    "requiredArgs": [
      "session_id"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "shell_session_open",
    "description": "Kalıcı terminal oturumu açar; çalışma dizini ve ortam sonraki komutlarda korunur.",
    "usage": "Çok adımlı yazılım işleri için (derle/test/düzelt döngüsü). Tek komut yetiyorsa shell_run kullan.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "shell_session_run",
    "description": "Açık terminal oturumunda komut çalıştırır; cwd/ortam korunur, çıktı ve exit kodu döner.",
    "usage": "Testi çalıştır, çıktıyı oku, düzelt, tekrar çalıştır döngüsü için.",
    "requiredArgs": [
      "session_id",
      "command"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "speech_capture",
    "description": "Yerel mikrofondan kısa ses kaydı başlatır veya durdurur.",
    "usage": "Sesli not/dikte almak için kaydı başlatıp durdurma. Kaydı metne çevirmek için speech_to_text.",
    "requiredArgs": [
      "action"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "speech_to_text",
    "description": "Yerel ses kaydını metne çevirir (dikte).",
    "usage": "Ses kaydını yazıya dökmek için. Yazıyı sese çevirmek için text_to_speech.",
    "requiredArgs": [],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "spreadsheet_write",
    "description": "XLSX/Excel çalışma kitabı üretir; satır, sütun, sheet ve hesap sonuçlarını yapılandırılmış tabloya yazar.",
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
    "fewShots": [],
    "privacyClass": "local_private_write",
    "skillAffinity": [
      "spreadsheet.table_from_context"
    ]
  },
  {
    "name": "sys_info",
    "description": "Sistem bilgisi alır: pil, CPU, RAM, disk, saat, tarih, ağ.",
    "usage": "Bilgisayarın anlık durumunu/saati sorulduğunda. Çalışan uygulamalar için desktop_os.processes.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "text_analyze",
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
    "privacyClass": "local_or_server_context",
    "skillAffinity": []
  },
  {
    "name": "text_to_speech",
    "description": "Metni yerel olarak sesli okur.",
    "usage": "Bir metni/cevabı sesli okutmak için.",
    "requiredArgs": [
      "text"
    ],
    "requiresApproval": false,
    "whenToUse": [],
    "whenNotToUse": [],
    "inputContract": {},
    "outputContract": {},
    "artifactContract": {},
    "verificationPlan": [],
    "liveNarration": [],
    "failureModes": [],
    "fewShots": [],
    "privacyClass": "",
    "skillAffinity": []
  },
  {
    "name": "web_research",
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
    "fewShots": [],
    "privacyClass": "public_web",
    "skillAffinity": []
  }
];
