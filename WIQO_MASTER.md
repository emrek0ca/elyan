# ELYAN MASTER STATUS

Son güncelleme: 13 Şubat 2026 (03:12)

## Ürün Özeti
- Elyan: macOS odaklı, çok araçlı, TR öncelikli dijital asistan.
- Ana hedef: kullanıcının verdiği görevi doğru anlayıp güvenli biçimde planlayıp uygulamak.
- Çalışma modeli: Anla -> Planla -> Uygula -> Geri Bildirim -> Öğren.

## Tek Komut Çalıştırma (Güncel)
- Tek dosya launcher eklendi: `wiqo.py`
- Önerilen başlatma:
  - UI: `python3 /Users/emrekoca/Desktop/bot/wiqo.py`
  - CLI (Telegram): `python3 /Users/emrekoca/Desktop/bot/wiqo.py --cli`
- Eski giriş noktası hâlâ geçerli: `python main.py`

## Bu Oturumda Yapılan Kritik Düzeltmeler

### 0) AI Panel modüler refactor (yeni)
- `CleanAIPanel` ayrı modüle taşındı:
  - `ui/ai_settings_panel.py`
- `ui/clean_main_app.py` artık yeni paneli import ederek kullanıyor.
- Eski panel kodu tamamen temizlendi.

### 0.1) LLM bağlantı testi (yeni)
- AI paneline **“Bağlantıyı Test Et”** butonu eklendi.
- Provider bazlı doğrulama:
  - Groq: chat completions ping
  - Gemini: generateContent ping
  - OpenAI: models endpoint kontrolü
  - Ollama: `ollama list` host doğrulaması
- Sonuçlar panelde anlık durum metni olarak gösteriliyor.

### 0.2) AI panel profesyonel UX iyileştirmesi (yeni)
- Bağlantı testi artık UI thread'i bloklamıyor (`ConnectionTestWorker`).
- Test sonucu artık daha detaylı:
  - başarı/hata özeti
  - teknik detay (HTTP kodu / stderr)
  - gecikme süresi (ms)
- Kaydetme doğrulaması güçlendirildi:
  - Cloud provider seçiliyken boş API key ile kayıt engelleniyor.
  - Ollama host formatı (`http://` / `https://`) kontrol ediliyor.

### 0.3) AI panel güvenilirlik artırımı (yeni)
- Bağlantı testine otomatik retry/backoff eklendi (geçici ağ hataları için).
- Son 10 bağlantı test sonucu panelde geçmiş olarak tutuluyor.
- `clean_main_app.py` içindeki `LegacyCleanAIPanel` tamamen kaldırıldı.
- Kullanılmayan AI panel importları (`QSlider`, `QSpinBox`) temizlendi.

### 0.4) Capability Router temeli (yeni)
- Yeni modül eklendi: `core/capability_router.py`
- Kullanıcı talepleri domain bazlı sınıflandırılıyor:
  - website, code, image, research, document, summarization
- Router çıktısı `TaskEngine` içine execution requirement olarak enjekte ediliyor:
  - `capability_domain`, `primary_objective`, `preferred_tools`
  - `output_artifacts`, `quality_checklist`, `learning_tags`
- Amaç: görev ayrıştırmayı “profesyonel asistan” davranışına hizalamak ve
  website/kod/görsel/araştırma/belgeleme/özetleme isteklerini daha doğru route etmek.

### 0.5) Profesyonel workflow araçları (yeni)
- Yeni tool modülü eklendi: `tools/pro_workflows.py`
  - `create_web_project_scaffold(...)`
  - `generate_document_pack(...)`
- Tool registry güncellendi: `tools/__init__.py`
- Capability router bu araçları öncelikli önerilerde kullanacak şekilde güncellendi.
- TaskEngine:
  - heuristic action inference yeni araçlara yönlendirildi.
  - decomposition tool kataloğu yeni araçları içeriyor.
  - kısa mesajlarda capability domain yüksekse chat fallback yerine task akışı korunuyor.
- `generate_document_pack` dayanıklılığı artırıldı:
  - markdown/txt paket her durumda lokal olarak üretiliyor
  - docx üretimi best-effort (başarısız olursa `docx_warning` ile devam)

### 0.6) Kalıcı capability metrikleri + pipeline state (yeni)
- Yeni modüller:
  - `core/capability_metrics.py`
  - `core/pipeline_state.py`
- TaskEngine entegrasyonu:
  - capability domain bazlı başarı/süre metrikleri kaydediliyor.
  - task yürütmeleri pipeline state olarak tutuluyor (start/step/complete).
  - metadata'da `capability_domain` ve `pipeline_id` dönüyor.
- Dashboard entegrasyonu (`ui/clean_main_app.py`):
  - Yeni kartlar: `Odak Domain`, `Tahmini Maliyet`.

### 0.7) Görsel workflow profili (yeni)
- Yeni tool: `create_image_workflow_profile(...)`
  - Prompt pack + style profile üretir.
- Registry ve routing güncellendi:
  - `tools/__init__.py`
  - `core/capability_router.py`
  - `core/task_engine.py`

### 0.8) Task Contract + Regression Suite (yeni)
- Yeni modül: `core/task_contract.py`
  - Task contract üretimi: objective, quality checklist, verification, retry, security level.
- TaskEngine artık metadata içinde `task_contract` döndürüyor.
- Regression suite eklendi:
  - `scripts/regression_capability_pipeline.py`
  - pytest bağımsız çalışır; capability routing + workflows + pipeline state + metrics doğrular.

### 1) QPainter/UI stabilite
- `QGraphicsOpacityEffect` tabanlı sayfa geçiş animasyonu kaldırıldı.
- QPainter spam/painter not active kaynaklarını azaltacak şekilde effect bağımlılığı düşürüldü.
- Font fallback mekanizması iyileştirildi.
- Dosyalar:
  - `ui/clean_main_app.py`
  - `ui/components.py`

### 2) Wizard ve LLM seçim sadakati
- Wizard’da provider/model seçimi adımlar arasında korunur hale getirildi.
- Kurulum sonunda ayarlara model sadakati yazılıyor:
  - `llm_sticky_selection: true`
  - `llm_fallback_mode: conservative`
- Dosya:
  - `ui/apple_setup_wizard.py`

### 3) LLM yönlendirme davranışı
- Kullanıcının seçtiği modelin zorla default modele çevrilmesi kaldırıldı.
- Sticky seçim açıkken yalnız seçilen provider deneniyor.
- Dosya:
  - `core/llm_client.py`
  - `config/settings_manager.py`

### 4) Araştırma sonucu crash düzeltmesi
- Hata: `research_finished[str].emit(dict)` tip uyuşmazlığı.
- Fix: `research_finished = pyqtSignal(object)`
- Dosya:
  - `ui/clean_main_app.py`

### 5) Task callback await hatası (`NoneType can't be awaited`)
- Hata: `notify_callback` sync geldiğinde `await` ediliyordu.
- Fix: async/sync uyumlu `_emit_notify` eklendi, tüm notify noktaları buraya yönlendirildi.
- Dosya:
  - `core/task_engine.py`

### 6) Zeka (AI) paneli gerçek yönetim paneline dönüştürüldü
- Provider seçimi: `groq/gemini/openai/ollama`
- API key alanı (cloud providerlar için)
- Ollama host alanı
- Model listesi provider’a göre dinamik
- Sticky/fallback politikası
- Kaydet sonrası çalışan agent’a canlı LLM config apply (restart şartı azaltıldı)
- Dosya:
  - `ui/clean_main_app.py` (`CleanAIPanel`)

### 7) Rapor kalitesi ve doküman profesyonelliği
- DOCX çıktısına daha güçlü bölüm akışı eklendi:
  - Introduction, Methodology, Strategic Insights, Recommendations
- Kaynak listesi güvenilirlik + URL ile daha düzenli üretildi.
- Dosya:
  - `tools/research_tools/advanced_report.py`

### 8) Telegram token log gürültüsü azaltıldı
- Token yoksa warning yerine info log.
- Dosya:
  - `ui/clean_main_app.py`

## Mevcut Teknik Durum

### Çalışan çekirdek dosyalar
- Launcher: `wiqo.py`, `main.py`
- Desktop UI: `ui/clean_main_app.py`
- Agent: `core/agent.py`
- Task Engine: `core/task_engine.py`
- LLM Router/Client: `core/llm_client.py`
- Tool registry: `tools/__init__.py`
- Wizard entry: `ui/wizard_entry.py`

### Ayar anahtarları (önemli)
- `llm_provider`
- `llm_model`
- `api_key`
- `ollama_host`
- `llm_sticky_selection`
- `llm_fallback_mode`
- `llm_fallback_order`

## Bilinen Açık Noktalar / Teknik Borç
- `CleanAIPanel` şu an `ui/clean_main_app.py` içinde büyüdü.
  - Sonraki adım: `ui/ai_settings_panel.py` dosyasına taşınıp modülerleştirilecek.
- Projede çok sayıda eski/legacy UI dosyası var (`main_app.py`, `main_window.py`, vb.).
  - Kullanım dışı akışlar sadeleştirilmeli.
- Otomatik test altyapısı eksik:
  - `pytest` ortamda yüklü değil (`No module named pytest`).
- `.pyc` ve geçmişten kalan artefact’lar çalışma ağacında fazla.
  - Temizlik planı gerekli (dikkatli, kullanıcı dosyası silmeden).

## Sonraki Oturum İçin Net Plan
1. Legacy temizlik:
   - Aktif olmayan eski UI dosyalarını envanterle, kademeli sadeleştirme yap.
2. Test altyapısı:
   - `venv` içine `pytest` kur, kritik senaryolar için smoke test ekle.
3. LLM UX iyileştirme:
   - AI paneli test butonunu async/non-blocking hale getir.
   - Test sonuçlarını detay paneline (latency + hata kodu) yaz.
4. Rapor kalitesi:
   - DOCX/PDF için tek şablon standardı ve kaynak alıntı format birliği.

## Hızlı Operasyon Notları
- Çalıştır:
  - `python3 /Users/emrekoca/Desktop/bot/wiqo.py`
- Hızlı derleme kontrol:
  - `python3 -m py_compile ui/clean_main_app.py core/task_engine.py core/llm_client.py`
- Wizard seçimi kontrol:
  - logda `Setup wizard selected: ui.apple_setup_wizard.AppleSetupWizard` görülmeli.

## Not
- Bu dosya, “nerede kaldık?” için kanonik oturum özeti olarak tutuluyor.
- Her büyük değişiklikten sonra tarih/saat ve “Bu Oturumda Yapılanlar” bölümü güncellenecek.
