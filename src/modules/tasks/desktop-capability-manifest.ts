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
    "requiresApproval": true
  },
  {
    "name": "add_reminder",
    "description": "Apple Reminders'a yeni hatırlatıcı ekler.",
    "usage": "Hatırlatıcı/yapılacak eklerken. Tarih varsa mutlak ISO'ya çevir.",
    "requiredArgs": [
      "title"
    ],
    "requiresApproval": true
  },
  {
    "name": "analyze_screen",
    "description": "Aktif ekranda ne olduğunu analiz eder (ne görünüyor sorusu).",
    "usage": "'Ekranımda ne var / bu ne' gibi sorularda. Ekranda tıklama/yazma için desktop_operator.run.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false
  },
  {
    "name": "browser_agent.run",
    "description": "Tarayıcıda hedefi KENDİ gözleyip karar vererek adım adım gerçekleştiren ajan: sayfayı gözler, tıklar, yazar, veri toplar, dosya indirir; hedef bitince özet ve toplanan verileri döndürür.",
    "usage": "Sayfa yapısı önceden bilinmeyen çok adımlı tarayıcı görevlerinde TEK adım olarak kullan. Adımları kendin yazabiliyorsan browser_session.* daha hızlıdır; buradaki ajan keşif gerektiren işler içindir.",
    "requiredArgs": [
      "goal"
    ],
    "requiresApproval": true
  },
  {
    "name": "browser_control",
    "description": "Tarayıcıda bir URL açar, web araması yapar, YouTube'da video açar veya yeni sekme açar.",
    "usage": "Web adresi açma/arama/YouTube/yeni sekme için. 'Yeni sekme aç' isteği action='new_tab'tır — 'yeni sekme' metnini ASLA aramaya çevirme. Uygulamanın kendisini açmak için open_app kullan.",
    "requiredArgs": [
      "action"
    ],
    "requiresApproval": true
  },
  {
    "name": "browser_session.click",
    "description": "Oturumdaki sayfada bir öğeye tıklar (CSS selector, görünür metin ya da rol+metin ile).",
    "usage": "browser_session.snapshot ile öğeleri gördükten sonra hedefe tıklamak.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "browser_session.close",
    "description": "Kalıcı tarayıcı oturumunu kapatır.",
    "usage": "Çok adımlı tarayıcı işi bittiğinde temizlik.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "browser_session.download",
    "description": "Sayfadan dosya indirir (indirme başlatan öğeye tıklayarak ya da doğrudan URL ile) ve dosya yolunu döndürür.",
    "usage": "Transcript/rapor/dosya indirme adımlarında; dönen outputPath sonraki file_move adımına verilir.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "browser_session.extract",
    "description": "Sayfadan yapılandırılmış veri çıkarır: selector eşleşmelerinin metni ve istenirse bir attribute'u (ör. href). Selector verilmezse sayfanın okunur metnini döndürür.",
    "usage": "Liste toplama işlerinde: video linkleri, başlıklar, tablo hücreleri. Sonuç result.items listesindedir; sonraki adımlar {{steps.<id>.result.items}} ile kullanır.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "browser_session.goto",
    "description": "Kalıcı tarayıcı oturumunda bir adrese gider; sonraki adımlar AYNI sayfada devam eder.",
    "usage": "Çok adımlı tarayıcı işlerinde (gez → tıkla → çıkar → indir) ilk adım. Tek seferlik 'URL aç ve bırak' için browser_control kullan.",
    "requiredArgs": [
      "url"
    ],
    "requiresApproval": false
  },
  {
    "name": "browser_session.snapshot",
    "description": "Sayfanın etkileşimli öğelerini (link/buton/alan, metinleriyle) listeler — sonraki tıklama/yazma adımını doğru hedefe yöneltmek için gözlem.",
    "usage": "Sayfanın yapısı bilinmiyorken tıklamadan ÖNCE gözlem almak.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "browser_session.type",
    "description": "Oturumdaki sayfada bir alana metin yazar; submit=true ile Enter'a basar. Şifre alanlarına yazmaz.",
    "usage": "Arama kutusu doldurma, form alanına URL yapıştırma gibi işlerde.",
    "requiredArgs": [
      "value"
    ],
    "requiresApproval": false
  },
  {
    "name": "canvas_write",
    "description": "Metin, tablo, grafik ve görselleri PDF veya PNG canvas çıktısına dönüştürür.",
    "usage": "Metin+tablo+grafik+görseli tek görsel sayfada (PDF/PNG) birleştirmek için. Sadece Word için document_write.",
    "requiredArgs": [
      "outputPath"
    ],
    "requiresApproval": true
  },
  {
    "name": "chart_generate",
    "description": "CSV, JSON veya Excel verisinden yerel PNG grafik üretir.",
    "usage": "Veriyi görselleştirmek için. Önce veriyi anlamak istersen data_analyze.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false
  },
  {
    "name": "clipboard_read",
    "description": "Panodaki (clipboard) metni okur.",
    "usage": "Kullanıcı 'panodakini/kopyaladığımı' işleme dediğinde.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "clipboard_write",
    "description": "Verilen metni panoya (clipboard) kopyalar.",
    "usage": "Bir sonucu/metni kullanıcının yapıştırabilmesi için panoya koymak.",
    "requiredArgs": [
      "text"
    ],
    "requiresApproval": false
  },
  {
    "name": "close_app",
    "description": "Çalışan bir masaüstü uygulamasını kapatır.",
    "usage": "Kullanıcı bir uygulamayı kapatmak istediğinde.",
    "requiredArgs": [
      "app_name"
    ],
    "requiresApproval": true
  },
  {
    "name": "data_analyze",
    "description": "CSV, JSON veya Excel verisini yerel olarak analiz eder (özet/profil/önizleme).",
    "usage": "Bir veri dosyasını anlamak/özetlemek için. Grafik çizmek için chart_generate.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false
  },
  {
    "name": "delete_calendar_event",
    "description": "Apple Calendar takviminden etkinlik siler (geri alınamaz — onay gerekir).",
    "usage": "Etkinlik silmek için. Yanlış silmemek için start_iso ile daralt.",
    "requiredArgs": [
      "title"
    ],
    "requiresApproval": true
  },
  {
    "name": "delete_memory",
    "description": "Kalıcı hafızadan bir kaydı siler.",
    "usage": "Kullanıcı 'şunu unut/hatırlama' dediğinde.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "desktop_operator.cancel",
    "description": "Aktif ekran otomasyonu çalışmasını güvenli şekilde durdurur.",
    "usage": "Takılan/istenmeyen bir operator çalışmasını durdurmak için.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "desktop_operator.execute_action",
    "description": "Ekranda tek bir güvenli UI eylemi çalıştırır (tıkla/yaz/tuş) — operator alt-adımı.",
    "usage": "Tek UI eylemi için. Çok adımlı hedef için desktop_operator.run (kendi döngüsünü yürütür).",
    "requiredArgs": [
      "actionType"
    ],
    "requiresApproval": true
  },
  {
    "name": "desktop_operator.focus_window",
    "description": "Bir masaüstü uygulamasını öne alır.",
    "usage": "Bir uygulamayı öne getirmek için. Uygulamayı açmak için open_app.",
    "requiredArgs": [],
    "requiresApproval": true
  },
  {
    "name": "desktop_operator.locate",
    "description": "Metin veya öğe tipine göre ekrandaki hedef öğeyi bulur (operator alt-adımı).",
    "usage": "İleri ekran otomasyonu alt-adımı; genelde desktop_operator.run içinde.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "desktop_operator.observe_screen",
    "description": "Aktif pencereyi yapılandırılmış ekran gözlemine çevirir (operator alt-adımı).",
    "usage": "İleri ekran otomasyonu alt-adımı. Uçtan uca UI görevi için desktop_operator.run tercih et.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "desktop_operator.run",
    "description": "Gözlemle→bul→uygula→doğrula döngüsüyle uçtan uca ekran otomasyonu görevi çalıştırır.",
    "usage": "YALNIZ yerel (native) uygulama arayüzlerinde tıklama/yazma gerektiren işler için; macOS Ekran Kaydı + Erişilebilirlik izni ister. Web sitesi/tarayıcı işleri için HER ZAMAN browser_agent.run kullan (i…",
    "requiredArgs": [],
    "requiresApproval": true
  },
  {
    "name": "desktop_os.active_window",
    "description": "Şu an öndeki (aktif) pencere bilgisini döndürür.",
    "usage": "Kullanıcının o an hangi uygulamada olduğunu öğrenmek için.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "desktop_os.open_permission_settings",
    "description": "İlgili sistem izin ekranını güvenli şekilde açar.",
    "usage": "Bir izin eksikse kullanıcıyı doğru sistem ayar ekranına yönlendirmek için.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "desktop_os.permissions",
    "description": "Masaüstü izin modelini ve izin hazırlık (readiness) durumunu döndürür.",
    "usage": "Hangi sistem izinlerinin verildiğini görmek için. İzin ekranını açmak için desktop_os.open_permission_settings.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "desktop_os.processes",
    "description": "Çalışan uygulamaları/prosesleri güvenli şekilde listeler.",
    "usage": "Hangi uygulamaların açık olduğunu görmek için. Genel sistem bilgisi için sys_info.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "desktop_os.status",
    "description": "Masaüstü OS yetenek ve native entegrasyon durumunu döndürür.",
    "usage": "Masaüstünün hangi yeteneklerinin hazır olduğunu kontrol ederken (tanılama).",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "directory_tree",
    "description": "Proje/klasör yapısını (ağaç) çıkarır; gürültülü klasörleri atlar.",
    "usage": "Bir klasörde neler olduğunu/proje yapısını görmek için. Dosya içeriğinde arama için file_search.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "document_read",
    "description": "Zengin belge içeriğini (Word/PDF/metin) okur ve özetlenebilir metne çevirir.",
    "usage": "Word/PDF gibi belgeleri okurken. Görüntüdeki metin için ocr_read, düz metin/kod için file_read.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false
  },
  {
    "name": "document_write",
    "description": "DOCX (Word) belgesi oluşturur veya bir kaynaktan dönüştürür.",
    "usage": "Rapor/mektup/not gibi Word belgesi üretmek için. Araştırma sonrası kullanılıyorsa web_research adımına dependsOn ver; içerik _previousOutput'tan gelir.",
    "requiredArgs": [],
    "requiresApproval": true
  },
  {
    "name": "email_draft",
    "description": "E-posta taslağı hazırlar (göndermez — kullanıcı onayına sunulur).",
    "usage": "E-posta yazmak için. Taslak onaydan sonra email_send ile gönderilir. Alıcı belirsizse netleştir.",
    "requiredArgs": [
      "to"
    ],
    "requiresApproval": false
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
    "requiresApproval": true
  },
  {
    "name": "file_move",
    "description": "Dosyayı başka bir konuma taşır (hedef klasörse içine).",
    "usage": "İndirilen dosyaları kullanıcının istediği klasöre toplamak.",
    "requiredArgs": [
      "source",
      "destination"
    ],
    "requiresApproval": false
  },
  {
    "name": "file_patch",
    "description": "Var olan bir dosyada çıpalı bul/değiştir uygular (old_string → new_string).",
    "usage": "Bir dosyanın küçük bir bölümünü değiştirmek için. Tüm dosyayı yeniden yazmak için file_write.",
    "requiredArgs": [
      "path",
      "old_string"
    ],
    "requiresApproval": false
  },
  {
    "name": "file_read",
    "description": "Bir metin/kod dosyasını güvenli şekilde okur (isteğe bağlı satır aralığı).",
    "usage": "Belge/kod dosyası içeriğini görmek için. Word/PDF gibi zengin belgeler için document_read kullan.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false
  },
  {
    "name": "file_search",
    "description": "Bir klasör ağacında dosya İÇERİĞİNDE metin/regex arar (ripgrep destekli).",
    "usage": "Dosya içinde metin ararken. Dosya ADIYLA bulmak veya klasör yapısı için directory_tree.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false
  },
  {
    "name": "file_write",
    "description": "Bir metin/kod dosyası oluşturur veya (overwrite=true ile) üzerine yazar.",
    "usage": "Düz metin/kod dosyası oluştururken. Word belgesi için document_write, tablo için spreadsheet_write.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false
  },
  {
    "name": "get_calendar_events",
    "description": "Apple Calendar takvimini okur (etkinlikleri listeler).",
    "usage": "Kullanıcı takvimini/programını sorduğunda. Yeni etkinlik için add_calendar_event.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false
  },
  {
    "name": "get_reminders",
    "description": "Apple Reminders listesini okur.",
    "usage": "Hatırlatıcıları/yapılacakları görüntülerken. Yeni öğe için add_reminder.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false
  },
  {
    "name": "get_weather",
    "description": "Anlık hava durumunu özetler.",
    "usage": "Hava durumu sorulduğunda.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "get_youtube_channel_report",
    "description": "YouTube kanal istatistiklerini ve son video performansını raporlar.",
    "usage": "Bir YouTube kanalının performansını özetlerken.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "git_branch",
    "description": "Yeni bir git branch'i oluşturur (varsayılan: oluşturup geçer).",
    "usage": "Ana dalda çalışmadan önce yeni bir dal açarken.",
    "requiredArgs": [
      "name"
    ],
    "requiresApproval": false
  },
  {
    "name": "git_commit",
    "description": "Değişiklikleri commit'ler (opsiyonel git add -A). PUSH YAPMAZ.",
    "usage": "Değişiklikleri kaydederken. Push YAPMAZ (güvenlik). Yeni dal için git_branch.",
    "requiredArgs": [
      "message"
    ],
    "requiresApproval": false
  },
  {
    "name": "git_diff",
    "description": "Bir git deposundaki çalışma ağacı veya staged farkını (diff) döndürür.",
    "usage": "Kod değişikliklerinin detayını görmek için.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "git_status",
    "description": "Bir git deposunun durumunu (branch + staged/unstaged/untracked) döndürür.",
    "usage": "Bir repoda hangi değişiklikler var diye bakarken.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "image_edit",
    "description": "Kullanıcının seçtiği yerel görseli Gemini ile isteğe uygun şekilde düzenler ve yeni dosya oluşturur.",
    "usage": "Seçili/yüklenmiş görselde öğe ekleme, kaldırma, arka plan veya stil değiştirme için. Yalnız inceleme için image_read.",
    "requiredArgs": [
      "prompt",
      "sourcePath"
    ],
    "requiresApproval": false
  },
  {
    "name": "image_fetch",
    "description": "Herkese açık bir kaynaktan (Openverse/Wikimedia) bir konu için görsel indirir ve kullanıcının klasörüne (varsayılan masaüstü) kaydeder.",
    "usage": "Web'den hazır/telifsiz görsel indirmek için. Sıfırdan görsel üretmek için image_generate.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false
  },
  {
    "name": "image_generate",
    "description": "Metin isteminden Gemini ile yüksek kaliteli görsel üretir ve dosyaya kaydeder.",
    "usage": "Sıfırdan görsel/illüstrasyon üretmek için. Web'den hazır görsel indirmek için image_fetch.",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false
  },
  {
    "name": "image_read",
    "description": "Yerel bir görselin ne içerdiğini inceler (açıklama/etiket/renk).",
    "usage": "Bir görselin İÇERİĞİNİ anlamak için. İçindeki yazıyı okumak için ocr_read.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false
  },
  {
    "name": "latex_parse",
    "description": "LaTeX matematik ifadesini yerel sembolik forma çevirir/normalize eder.",
    "usage": "LaTeX'i işlerken. Sayısal çözüm için math_solve.",
    "requiredArgs": [
      "expression"
    ],
    "requiresApproval": false
  },
  {
    "name": "make_directory",
    "description": "Klasör oluşturur (üst klasörler dahil; varsa hata vermez).",
    "usage": "İndirilen/üretilen dosyaları toplamadan önce hedef klasörü hazırlamak veya kullanıcının istediği klasörü açmak.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false
  },
  {
    "name": "math_solve",
    "description": "Matematik ifadesini yerel olarak çözer veya sadeleştirir.",
    "usage": "Hesaplama/denklem/türev-integral için. LaTeX girdiyi ayrıştırmak için latex_parse.",
    "requiredArgs": [
      "expression"
    ],
    "requiresApproval": false
  },
  {
    "name": "mcp_call_tool",
    "description": "Bağlı bir MCP sunucusundaki aracı çağırır (harici entegrasyonlar).",
    "usage": "Yerleşik yeteneklerin karşılamadığı, kullanıcının bağladığı bir MCP aracı gerektiğinde.",
    "requiredArgs": [
      "serverId",
      "toolName"
    ],
    "requiresApproval": true
  },
  {
    "name": "ocr_read",
    "description": "Görsel veya taranmış PDF sayfasındaki metni OCR ile çıkarır.",
    "usage": "Fotoğraf/ekran görüntüsü/taranmış belgedeki YAZIYI okumak için. Seçilebilir metinli belge için document_read.",
    "requiredArgs": [
      "path"
    ],
    "requiresApproval": false
  },
  {
    "name": "open_app",
    "description": "Yerel bir masaüstü uygulamasını açar (Safari, Chrome, Notlar, Spotify…).",
    "usage": "Kullanıcı bir uygulamayı açmak istediğinde. URL/arama için browser_control, medya için play_media kullan.",
    "requiredArgs": [
      "app_name"
    ],
    "requiresApproval": true
  },
  {
    "name": "play_media",
    "description": "YouTube, Spotify veya Apple Music ile şarkı/çalma listesi oynatır.",
    "usage": "Müzik/video çalmak için. Sadece uygulamayı açmak için open_app kullan.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": true
  },
  {
    "name": "presentation_write",
    "description": "PPTX (PowerPoint) sunum üretir.",
    "usage": "Slayt destesi için. Araştırma sonrası kullanılıyorsa web_research'e dependsOn ver.",
    "requiredArgs": [],
    "requiresApproval": true
  },
  {
    "name": "quantum_compare_classical",
    "description": "Kuantum demo sonucunu klasik baseline ile karşılaştırır.",
    "usage": "Kuantum sonucunu klasik yöntemle kıyaslarken.",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false
  },
  {
    "name": "quantum_generate_report",
    "description": "Kuantum deney akışı için teknik rapor ve metrik artifact üretir.",
    "usage": "Kuantum deney akışının sonunda özet rapor üretmek için.",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false
  },
  {
    "name": "quantum_model_problem",
    "description": "Optimizasyon problemini QUBO/Ising demo modeline dönüştürür.",
    "usage": "Kuantum/optimizasyon demo akışının ilk adımı; ardından quantum_run_experiment.",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false
  },
  {
    "name": "quantum_run_experiment",
    "description": "QAOA/VQE simülatör demo deneyini yürütür.",
    "usage": "Kuantum demo deneyi çalıştırmak için (Qiskit/Aer gerekir).",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false
  },
  {
    "name": "retrieve_context",
    "description": "Yerel çalışma alanı ve konuşmalardan bağlam eşleşmeleri döndürür (çevrimdışı).",
    "usage": "Yerel/geçmiş bilgi gerektiğinde veya web erişilemediğinde. Güncel dış bilgi için web_research.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false
  },
  {
    "name": "run_skill",
    "description": "Yerel skill manifestinden kontrollü, çok adımlı bir beceri çalıştırır.",
    "usage": "Kullanıcının tanımladığı hazır bir beceri/otomasyon gerektiğinde.",
    "requiredArgs": [
      "skillId"
    ],
    "requiresApproval": true
  },
  {
    "name": "save_memory",
    "description": "Kullanıcı hakkında kalıcı bir tercih/olgu kaydeder (sonraki oturumlarda hatırlanır).",
    "usage": "Kullanıcı 'bunu hatırla/aklında tut' dediğinde kalıcı tercih/olgu kaydetmek için.",
    "requiredArgs": [
      "key",
      "value"
    ],
    "requiresApproval": false
  },
  {
    "name": "save_whatsapp_contact",
    "description": "WhatsApp kişisini kalıcı kaydeder (sonraki mesajlarda adla çözülür).",
    "usage": "Bir kişiyi ilerideki WhatsApp mesajları için kaydetmek üzere.",
    "requiredArgs": [
      "display_name",
      "phone_number"
    ],
    "requiresApproval": true
  },
  {
    "name": "send_whatsapp_message",
    "description": "WhatsApp Desktop/Web üzerinden mesaj hazırlar veya gönderir (gönderim dışa dönük — onay gerekir).",
    "usage": "WhatsApp mesajı için. Alıcı belirsiz/numara bilinmiyorsa netleştir, uydurma. Kişi kaydı için save_whatsapp_contact.",
    "requiredArgs": [
      "message"
    ],
    "requiresApproval": true
  },
  {
    "name": "shell_run",
    "description": "Yerel terminal komutu çalıştırır (güçlü — açık onay gerekir).",
    "usage": "Yalnız başka yetenek yokken. Dosya işlemleri için file_* , git için git_* yeteneklerini tercih et.",
    "requiredArgs": [
      "command"
    ],
    "requiresApproval": true
  },
  {
    "name": "speech_capture",
    "description": "Yerel mikrofondan kısa ses kaydı başlatır veya durdurur.",
    "usage": "Sesli not/dikte almak için kaydı başlatıp durdurma. Kaydı metne çevirmek için speech_to_text.",
    "requiredArgs": [
      "action"
    ],
    "requiresApproval": false
  },
  {
    "name": "speech_to_text",
    "description": "Yerel ses kaydını metne çevirir (dikte).",
    "usage": "Ses kaydını yazıya dökmek için. Yazıyı sese çevirmek için text_to_speech.",
    "requiredArgs": [],
    "requiresApproval": false
  },
  {
    "name": "spreadsheet_write",
    "description": "XLSX (Excel) çalışma sayfası üretir.",
    "usage": "Sayısal/tablosal veri (bütçe, liste, hesap) için. Metin belgesi için document_write.",
    "requiredArgs": [],
    "requiresApproval": true
  },
  {
    "name": "sys_info",
    "description": "Sistem bilgisi alır: pil, CPU, RAM, disk, saat, tarih, ağ.",
    "usage": "Bilgisayarın anlık durumunu/saati sorulduğunda. Çalışan uygulamalar için desktop_os.processes.",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false
  },
  {
    "name": "text_analyze",
    "description": "Okuma, araştırma veya hesap çıktılarından yerel profesyonel analiz özeti üretir.",
    "usage": "Dosya okuma/araştırma/hesaplama sonrası, belge/sunum/tablo yazmadan önce muhakeme özeti çıkarmak için.",
    "requiredArgs": [
      "prompt"
    ],
    "requiresApproval": false
  },
  {
    "name": "text_to_speech",
    "description": "Metni yerel olarak sesli okur.",
    "usage": "Bir metni/cevabı sesli okutmak için.",
    "requiredArgs": [
      "text"
    ],
    "requiresApproval": false
  },
  {
    "name": "web_research",
    "description": "Public web üzerinde kaynak toplayıp kısa bir araştırma özeti üretir.",
    "usage": "Güncel/dış bilgi gerektiğinde. Sonucu bir belgeye yazmak için ardından document_write ekle (dependsOn ile).",
    "requiredArgs": [
      "query"
    ],
    "requiresApproval": false
  }
];
