# WIQO MASTER STATUS

Son güncelleme: 13 Şubat 2026 (02:10)

## Ürün Özeti
- Wiqo: macOS odaklı, çok araçlı, TR öncelikli dijital asistan.
- Ana hedef: kullanıcının verdiği görevi doğru anlayıp güvenli biçimde planlayıp uygulamak.
- Çalışma modeli: Anla -> Planla -> Uygula -> Geri Bildirim -> Öğren.

## Tek Komut Çalıştırma (Güncel)
- Tek dosya launcher eklendi: `wiqo.py`
- Önerilen başlatma:
  - UI: `python3 /Users/emrekoca/Desktop/bot/wiqo.py`
  - CLI (Telegram): `python3 /Users/emrekoca/Desktop/bot/wiqo.py --cli`
- Eski giriş noktası hâlâ geçerli: `python main.py`

## Bu Oturumda Yapılan Kritik Düzeltmeler

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
1. `CleanAIPanel` refactor:
   - `ui/ai_settings_panel.py` oluştur, `clean_main_app.py` içinden import et.
2. Legacy temizlik:
   - Aktif olmayan eski UI dosyalarını envanterle, kademeli sadeleştirme yap.
3. Test altyapısı:
   - `venv` içine `pytest` kur, kritik senaryolar için smoke test ekle.
4. LLM UX iyileştirme:
   - Zeka paneline “Bağlantı Test Et” butonu ve provider bazlı doğrulama sonucu.
5. Rapor kalitesi:
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
