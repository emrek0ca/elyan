# 🧠 ELYAN AI AGENT FRAMEWORK — Tam Teknik Dokümantasyon

> **Versiyon:** 20.1.0 | **Dil:** Python 3.12+ | **Lisans:** Proprietary  
> **Son Güncelleme:** 2026-02-22

---

## İçindekiler

1. [Genel Mimari](#1-genel-mimari)
2. [Giriş Noktaları](#2-giriş-noktaları)
3. [Core — Ana Motor](#3-core--ana-motor)
4. [Gateway & Channel Adapters](#4-gateway--channel-adapters)
5. [Multi-Agent Sistemi](#5-multi-agent-sistemi)
6. [Reasoning Motoru](#6-reasoning-motoru)
7. [Tools — Araç Kütüphanesi](#7-tools--araç-kütüphanesi)
8. [Security Modülleri](#8-security-modülleri)
9. [Config & Settings](#9-config--settings)
10. [UI — Arayüzler](#10-ui--arayüzler)
11. [Scheduler & Otomasyon](#11-scheduler--otomasyon)
12. [Handlers — Telegram Komutları](#12-handlers--telegram-komutları)
13. [Utils & Yardımcılar](#13-utils--yardımcılar)
14. [Pipeline Akışı](#14-pipeline-akışı)
15. [Dosya Listesi (Tam)](#15-dosya-listesi-tam)

---

## 1. Genel Mimari

```
┌─────────────────────────────────────────────────────────┐
│                   KULLANICI GİRİŞİ                       │
│   Telegram / Discord / Slack / WhatsApp / WebChat / CLI  │
└──────────────┬──────────────────────────────────────────┘
               ▼
┌──────────────────────────┐
│   Gateway Server         │  ← HTTP/WS Sunucu (aiohttp)
│   core/gateway/server.py │  ← 2670+ satır, 80+ API endpoint
└──────────┬───────────────┘
           ▼
┌──────────────────────────┐
│   Gateway Router         │  ← Mesaj yönlendirme, welcome flow
│   core/gateway/router.py │  ← Adapter yönetimi
└──────────┬───────────────┘
           ▼
┌──────────────────────────┐
│   Agent (Ana Motor)      │  ← 4700+ satır, tüm pipeline
│   core/agent.py          │  ← Validation → Routing → LLM → Tools
└──────────┬───────────────┘
           ▼
┌──────────────────────────────────────────────┐
│              İŞLEM KATMANLARI                 │
├──────────┬──────────┬──────────┬─────────────┤
│ Neural   │ Intent   │ LLM     │ Tool        │
│ Router   │ Parser   │ Client  │ Executor    │
│          │          │         │             │
│ Rolü ve  │ Komutu   │ AI'a    │ Dosya/web/  │
│ modeli   │ çözer    │ sorar   │ sistem ops  │
│ seçer    │          │         │             │
└──────────┴──────────┴──────────┴─────────────┘
```

**Ana Akış:**
1. Kullanıcı bir kanaldan mesaj gönderir
2. Gateway Server mesajı alır, Router'a yönlendirir
3. Agent pipeline başlar: validation → context → routing → intent → LLM → tool execution → response
4. Yanıt aynı kanaldan geri gönderilir

---

## 2. Giriş Noktaları

### `main.py` — CLI Entry Point (789 satır)
Ana CLI uygulaması. Click framework ile 11 komut sunar.

| Komut | İşlev |
|-------|-------|
| `elyan` | İlk çalışmada `setup`, sonra durum özeti |
| `elyan setup` | İnteraktif kurulum sihirbazı (dil, model, API key, Telegram) |
| `elyan start` | Gateway sunucusunu başlatır |
| `elyan stop` | Gateway'i PID ile durdurur |
| `elyan restart` | Stop + Start |
| `elyan dashboard` | Web paneli tarayıcıda açar |
| `elyan models` | Model yönetimi (use/ollama/pull/key) |
| `elyan status` | Sistem durumu + modül kontrolü |
| `elyan doctor` | Sağlık kontrolü + otomatik onarım |
| `elyan team` | Ajan takımı durumu + test |
| `elyan config` | JSON config göster |
| `elyan logs` | Son loglar |

**Önemli fonksiyonlar:**
- `_load_dotenv()` — `.env`, `bot/.env`, `~/.elyan/.env` dosyalarından env vars yükler
- `_run_gateway(port)` — Agent + Server oluşturup async loop'ta çalıştırır
- `_ollama_ok()` / `_ollama_models()` — Yerel Ollama durumunu kontrol eder

### `setup.py` / `pyproject.toml` — Paket Kurulumu
`pip install -e .` ile kurulum. `elyan` CLI komutunu `main:main` entry point'e bağlar.

### `elyan_entrypoint.py` — Alternatif Giriş
Doğrudan Python ile çalıştırma alternatifi.

---

## 3. Core — Ana Motor

### `core/agent.py` — Beyin (4715 satır, 212KB)
**Elyan'ın kalbi.** Tüm pipeline'ı orkestrasyonlar.

**Ana Metot: `process(user_input, channel, user_id)`**

```
Pipeline Adımları:
1. Input Validation     → Boş/zararlı girdi kontrolü
2. Short Input Guard    → Kısa/belirsiz mesajları yakalar
3. Context Intelligence → Kullanıcı bağlamını analiz eder
4. Neural Routing       → Rolü (code/reasoning/creative/inference) belirler
5. Intent Parsing       → Komutu deterministic olarak çözer
6. LLM Call            → AI modeline sorar
7. Tool Extraction     → LLM yanıtından tool çağrısı çıkarır
8. Tool Execution      → Aracı çalıştırır
9. Self-Correction     → Sonucu doğrular, gerekirse tekrar dener
10. Response Format    → Kullanıcıya uygun formatta yanıt
```

**Önemli İç Mekanizmalar:**
- **Self-Correction V2** (satır 916): `write_file`, `create_web_project_scaffold` gibi yazma araçları için doğrulama + otomatik tekrar
- **Contract Repair Loop** (satır 934): Çıktı sözleşmesi ihlallerinde otomatik onarım
- **Feedback Store**: Kullanıcı geri bildirimlerinden öğrenme
- **LLM Fallback**: Ana model başarısız olursa yedek modele geçiş

### `core/neural_router.py` — Model ve Rol Yönlendirici (100 satır)
Kullanıcı girdisini analiz ederek hangi LLM rolüne yönlendirileceğini belirler.

**Roller:**
| Rol | Tetikleyiciler | Örnek |
|-----|---------------|-------|
| `code` | kod, python, javascript, react, html | "React ile site yap" |
| `reasoning` | planla, analiz et, neden, mimari | "Proje mimarisi tasarla" |
| `creative` | hikaye, şiir, blog, yaratıcı | "Blog yazısı yaz" |
| `inference` | Varsayılan | "Hava nasıl?" |

**Complexity Score:** code/reasoning = 0.8, diğerleri = 0.3  
0.7 üstü = factory flow (tam pipeline), altı = hızlı yanıt

### `core/kernel.py` — Tool Registry (2872 satır)
Tüm araçları (124+) kayıt altına alır. `tools.execute(name, params)` ile çalıştırır.

### `core/llm_client.py` — LLM İstemcisi (13KB)
OpenAI, Anthropic, Google, Groq, Ollama API'lerine bağlanır. Unified interface sağlar.

### `core/model_orchestrator.py` — Provider Yöneticisi (5.7KB)
Birden fazla LLM sağlayıcısını yönetir. Config'den provider'ları yükler, API key'leri kontrol eder.

### `core/llm_cache.py` — Yanıt Cache (5.7KB)
LLM yanıtlarını hash-based cache'ler. Aynı sorguyu tekrar göndermez.

### `core/llm_optimizer.py` — Prompt Optimizasyonu (9KB)
Prompt'u modele göre optimize eder. Token sayısını azaltır.

### `core/memory.py` — Uzun Süreli Bellek (37KB)
SQLite tabanlı bellek sistemi. Kullanıcı tercihleri, conversation history, öğrenilen kalıplar.

### `core/conversation_memory.py` — Sohbet Bağlamı (6KB)
Son N mesajı tutar. LLM'e context olarak gönderir.

### `core/learning_engine.py` — Öğrenme Motoru (39KB)
Kullanıcı kalıplarını öğrenir. Başarılı/başarısız araç kullanımlarını kaydeder. Gelecek tahminleri yapar.

### `core/context_intelligence.py` — Bağlam Analizi (4.2KB)
Kullanıcı mesajından domain (web_dev, file_ops, research vb.) çıkarır. Özel davranış promptları ekler.

### `core/intent_parser.py` + `core/intent_parser/` — Niyet Çözücü
Deterministic kural tabanlı intent parsing. LLM çağırmadan komutu çözer.

### `core/quick_intent.py` — Hızlı Niyet Algılama (10KB)
Basit komutları (dosya aç, klasör listele) regex ile anında yakalar. LLM'e gitmeden hızlı yanıt.

### `core/fuzzy_intent.py` — Bulanık Niyet (36KB)
Yazım hatalarına toleranslı niyet eşleştirme. Levenshtein distance + n-gram matching.

### `core/fast_response.py` — Hızlı Yanıt (12KB)
Basit sorulara (selamlaşma, teşekkür) LLM çağırmadan anında yanıt verir.

### `core/parameter_extractor.py` — Parametre Çıkarıcı (8.5KB)
LLM yanıtından tool parametrelerini (dosya adı, URL, vb.) çıkarır.

### `core/output_contract.py` — Çıktı Sözleşmesi (20KB)
Tool çıktılarını doğrular. Dosya gerçekten yazıldı mı? İçerik doğru mu? Schema uyumlu mu?

### `core/artifact_quality_engine.py` — Kalite Kontrolü (3.7KB)
Oluşturulan dosyaların (HTML, Python, Excel) kalite puanını hesaplar.

### `core/task_engine.py` — Görev Motoru (86KB)
Karmaşık görevleri adım adım çalıştırır. Plan oluşturur, her adımı sırayla execute eder.

### `core/intelligent_planner.py` — Akıllı Planlayıcı (35KB)
Karmaşık görevler için çok adımlı plan üretir. Bağımlılık analizi, paralel adım optimizasyonu.

### `core/comprehensive_executor.py` — Kapsamlı Yürütücü (20KB)
Planlanan adımları yürütür. Hata durumunda geri alma (rollback) desteği.

### `core/enhanced_operations.py` — Gelişmiş Operasyonlar (36KB)
Dosya organizasyonu, toplu işlem, akıllı arama, gelişmiş dosya yönetimi.

### `core/workflow_engine.py` — İş Akışı Motoru (16KB)
Tekrarlanabilir iş akışları tanımlar ve çalıştırır.

### `core/action_lock.py` — Aksiyon Kilidi (1.4KB)
Aynı anda birden fazla görevin çakışmasını önler.

### `core/monitoring.py` — Sistem İzleme (6.9KB)
CPU, RAM, Disk, Batarya durumunu `psutil` ile izler. Health snapshot'lar üretir.

### `core/pricing_tracker.py` — Maliyet Takibi (4.9KB)
LLM API kullanımının token ve dolar maliyetini hesaplar.

### `core/pipeline_state.py` — Pipeline Durumu (2.4KB)
Son işlem durumunu saklar. Başarı oranı, ortalama süre hesaplar.

### `core/feedback.py` — Geri Bildirim (9.8KB)
Kullanıcı geri bildirimlerini toplar. Hata düzeltme ipuçları üretir.

### `core/self_healing.py` — Otomatik Onarım (4.4KB)
Hata tespit edildiğinde otomatik düzeltme dener.

### `core/self_improvement.py` — Otomatik İyileştirme (16KB)
Başarısız tool çağrılarından öğrenir. Parametre tahminlerini iyileştirir.

### `core/response_tone.py` — Ton Yöneticisi (19KB)
Yanıtın tonunu ayarlar: professional, friendly, technical, concise, creative.

### `core/i18n.py` — Çoklu Dil (2.3KB)
Türkçe/İngilizce mesaj çevirileri.

### `core/smart_cache.py` — Akıllı Cache (7.7KB)
Sonuç cache'leme. Kısa/boş yanıtları cache'lemez.

### `core/response_cache.py` — Yanıt Cache (9.8KB)
LLM yanıtlarını cache'ler. TTL ve max-size yönetimi.

### `core/error_handler.py` — Hata Yöneticisi (6.5KB)
Hataları yakalar, kullanıcıya anlamlı mesaj verir, log'a kaydeder.

### `core/timeout_guard.py` — Zaman Aşımı (2.9KB)
Tool çağrılarına timeout koyar. Sonsuz döngüyü önler.

### `core/event_system.py` — Event Bus (12KB)
Asenkron olay sistemi. Modüller arası iletişim.

### `core/speed_optimizer.py` — Hız Optimizasyonu (4.8KB)
Yanıt süresini ölçer ve optimize eder.

### `core/performance_profiler.py` — Performans Profiler (14KB)
Her pipeline adımının süresini ölçer. Darboğazları tespit eder.

### `core/connection_pool.py` — Bağlantı Havuzu (6.6KB)
HTTP bağlantılarını yeniden kullanır. Kaynak tasarrufu.

### `core/batch_processor.py` — Toplu İşlem (7.1KB)
Birden fazla görevi paralel çalıştırır.

### `core/session_manager.py` — Oturum Yönetimi (12KB)
Kullanıcı oturumlarını yönetir. Multi-turn sohbet bağlamı.

### `core/user_profile.py` — Kullanıcı Profili (4.4KB)
Kullanıcı tercihlerini saklar. Dil, model, kanal tercihleri.

### `core/knowledge_base.py` — Bilgi Tabanı (3.7KB)
Statik bilgi deposu. FAQ ve önceden tanımlı yanıtlar.

### `core/config_manager.py` — Config Yöneticisi (13KB)
Çalışma zamanında config değişikliklerini yönetir.

### `core/state_model.py` — Durum Modeli (2.5KB)
Pipeline durumunu Pydantic model ile temsil eder.

### `core/goal_graph.py` — Hedef Grafiği (5.7KB)
Karmaşık hedefleri alt hedeflere böler. DAG yapısı.

### `core/search_engine.py` — Arama Motoru (13KB)
Dosya sistemi ve bellek üzerinde arama.

### `core/smart_paths.py` — Akıllı Yol Çözücü (6.4KB)
Kullanıcının kastettiği dosya/klasör yolunu tahmin eder ("masaüstü" → `/Users/x/Desktop`).

### `core/embedding_codec.py` — Embedding (1.7KB)
Metin embedding'leri için codec.

### `core/semantic_memory.py` — Semantik Bellek (1.9KB)
Embedding tabanlı benzer bellek arama.

### `core/path_memory.py` — Yol Belleği (1.4KB)
Sık kullanılan dosya yollarını hatırlar.

### `core/visualization_engine.py` — Görselleştirme (14KB)
Grafik, tablo, chart oluşturma.

### `core/multimodal_processor.py` — Multi-Modal (18KB)
Görüntü, ses, video işleme. Screenshot analizi.

### `core/operator_policy.py` — Operatör Modu (2.1KB)
Kısa/minimal yanıt politikası. Gereksiz sohbeti engeller.

### `core/subscription.py` — Abonelik (4KB)
Lisans/abonelik yönetimi.

### `core/quota.py` — Kota Yönetimi (6.4KB)
API kullanım kotası. Günlük/aylık limitler.

### `core/tool_usage.py` — Tool Kullanım İstatistikleri (2.4KB)
Hangi tool ne kadar kullanıldı, başarı oranı.

### `core/tool_health.py` — Tool Sağlık Kontrolü (8.2KB)
Her tool'un çalışıp çalışmadığını kontrol eder.

### `core/tool_request.py` — Tool İstek Yöneticisi (13KB)
Tool çağrılarını queue'ya alır, önceliklendirir.

### `core/tool_governance.py` — Tool Yönetişimi (3KB)
Tool kullanım kuralları ve politika uygulaması.

### `core/startup_checker.py` — Başlangıç Kontrolü (17KB)
Sistem başlarken tüm modülleri kontrol eder.

### `core/advanced_analytics.py` — Gelişmiş Analitik (8.9KB)
Kullanım istatistikleri, trend analizi.

### `core/advanced_cache.py` — Gelişmiş Cache (13KB)
Multi-tier cache. Memory → Disk → Expire.

### `core/advanced_features.py` — Gelişmiş Özellikler (18KB)
Ek özellikler paketi.

### `core/advanced_security.py` — Gelişmiş Güvenlik (15KB)
Anomali tespiti, saldırı önleme.

### `core/async_llm_handler.py` — Async LLM (15KB)
Asenkron LLM çağrıları. Streaming support.

### `core/automation_engine.py` — Otomasyon (12KB)
Otomatik görev çalıştırma.

### `core/deterministic_runner.py` — Determinist Çalıştırıcı (6.4KB)
LLM'siz, kural tabanlı komut çalıştırma.

### `core/file_organizer.py` — Dosya Organizatörü (14KB)
Dosyaları otomatik kategorize eder ve düzenler.

### `core/integration_hub.py` — Entegrasyon Merkezi (17KB)
3. parti servis entegrasyonları.

### `core/job_queue.py` — İş Kuyruğu (11KB)
Arka plan işleri için kuyruk sistemi.

### `core/license_manager.py` — Lisans (8.2KB)
Lisans doğrulama ve yönetimi.

### `core/mutator.py` — Kod Mutasyonu (5.5KB)
Otomatik kod değişikliği/refactoring.

### `core/predictive_maintenance.py` — Öngörücü Bakım (14KB)
Sistem sorunlarını önceden tespit eder.

### `core/predictive_tasks.py` — Görev Tahmini (10KB)
Kullanıcının bir sonraki isteğini tahmin eder.

### `core/prompt_templates.py` — Prompt Şablonları (2.3KB)
Sistem, kullanıcı, tool prompt şablonları.

### `core/query_builder.py` — Sorgu Oluşturucu (16KB)
Veritabanı sorguları oluşturur.

### `core/registry.py` — Ana Registry (2.3KB)
Global modül kayıt sistemi.

### `core/request_router.py` — İstek Yönlendirici (7KB)
HTTP isteklerini uygun handler'a yönlendirir.

### `core/smart_notifications.py` — Akıllı Bildirimler (8.3KB)
Proaktif bildirimler. Kullanıcıyı önemli olaylardan haberdar eder.

### `core/briefing_manager.py` — Brifing (6.1KB)
Günlük özet raporları oluşturur.

### `core/model_manager.py` — Model Yöneticisi (2.3KB)
LLM modellerini listeleme ve değiştirme.

---

## 4. Gateway & Channel Adapters

### `core/gateway/server.py` — Ana Sunucu (2670+ satır, 118KB)
aiohttp tabanlı HTTP/WebSocket sunucusu. Dashboard UI ve tüm API'leri serve eder.

**API Endpoint Grupları (80+):**

| Grup | Endpoint'ler | İşlev |
|------|-------------|-------|
| Core | `/api/message`, `/api/status` | Mesaj gönderme, durum |
| Config | `/api/config`, `/api/agent/profile` | Config okuma/yazma |
| Models | `/api/models`, `/api/models/ollama/*` | Model yönetimi |
| Channels | `/api/channels/*` | Kanal CRUD, test, sync |
| Tasks | `/api/tasks`, `/api/tasks/suggest` | Görev yönetimi |
| Analytics | `/api/analytics` | İstatistikler |
| Tools | `/api/tools/*` | Tool listesi, policy, diagnostics |
| Skills | `/api/skills/*` | Skill yönetimi |
| Automation | `/api/routines/*` | Rutin CRUD, zamanlama |
| Security | `/api/security/*` | Güvenlik olayları, onay |
| Memory | `/api/memory/*` | Bellek istatistikleri |
| Dashboard | `/`, `/dashboard`, `/ws/dashboard` | Web UI |
| Webhooks | `/hook/{event}`, `/whatsapp/webhook` | Dış servis webhook'ları |

### `core/gateway/router.py` — Mesaj Yönlendirici (19KB)
- Gelen mesajları doğru adapter'a yönlendirir
- Welcome flow yönetir (yeni kullanıcıya hoş geldin)
- Typing indicator gönderir
- Adapter health monitoring

### `core/gateway/message.py` — Mesaj Modeli (1KB)
Unified mesaj formatı. Tüm kanallardan gelen mesajları standart formata çevirir.

### `core/gateway/response.py` — Yanıt Modeli (555 byte)
Unified yanıt formatı.

### Channel Adapter'lar (`core/gateway/adapters/`):

| Adapter | Dosya | Boyut | Açıklama |
|---------|-------|-------|----------|
| **Base** | `base.py` | 1.3KB | Tüm adapter'ların base class'ı |
| **Telegram** | `telegram.py` | 12KB | python-telegram-bot ile polling/webhook |
| **Discord** | `discord.py` | 3.4KB | Discord bot entegrasyonu |
| **Slack** | `slack.py` | 2.5KB | Slack bot entegrasyonu |
| **WhatsApp** | `whatsapp.py` | 20KB | WhatsApp Business API |
| **WhatsApp Bridge** | `whatsapp_bridge.py` | 15KB | WhatsApp Bridge protokolü |
| **WebChat** | `webchat.py` | 2.7KB | Tarayıcı WebSocket chat |
| **Signal** | `signal_adapter.py` | 9.5KB | Signal messenger |
| **iMessage** | `imessage_adapter.py` | 11KB | Apple iMessage (macOS) |
| **Teams** | `teams_adapter.py` | 8.2KB | Microsoft Teams |
| **Matrix** | `matrix_adapter.py` | 6.8KB | Matrix protokolü |
| **Google Chat** | `google_chat_adapter.py` | 11KB | Google Workspace Chat |

---

## 5. Multi-Agent Sistemi

### `core/multi_agent/specialists.py` — Uzman Ajanlar (11KB)
6 uzman ajan tanımlı. Her biri farklı göreve özelleşmiş:

| Ajan | Emoji | Rol | Anahtar Kelimeler |
|------|-------|-----|-------------------|
| Koordinatör | 🎯 | Takım lideri | karmaşık görevler |
| Araştırmacı | 🔬 | Araştırma | araştır, analiz, rapor |
| Yazılımcı | 🏗️ | Kod/içerik | yaz, oluştur, site, uygulama |
| Operasyon | ⚙️ | Sistem ops | sil, taşı, kopyala, kur |
| Kalite Kontrol | 🔍 | Test/QA | test, kontrol, hata |
| İletişimci | 💬 | Chat | merhaba, teşekkür, selam |

**`select_for_input()` Algoritması:**
1. Chat/greeting pattern → İletişimci (kısa mesajlar)
2. Araştırma keywords → Araştırmacı
3. Yazılım/oluşturma keywords → Yazılımcı
4. Sistem operasyonları → Operasyon
5. Test/kontrol → Kalite Kontrol
6. Context fallback → Koordinatör

### `core/multi_agent/orchestrator.py` — Orkestratör (19KB)
Karmaşık görevleri alt görevlere böler, her birini uygun ajana dağıtır, sonuçları birleştirir.

### `core/multi_agent/router.py` — Ajan Router (1.6KB)
Mesajı kanal ve kullanıcıya göre doğru ajana yönlendirir.

### `core/multi_agent/neural_router.py` — Ajan Neural Router (5.8KB)
AI tabanlı ajan seçimi. Keyword matching yetersiz kalırsa LLM ile karar verir.

### `core/multi_agent/contract.py` — İş Sözleşmesi (4.7KB)
Ajan görev sözleşmeleri. Girdi/çıktı formatı, doğrulama kuralları.

### `core/multi_agent/qa_pipeline.py` — Kalite Pipeline (5.4KB)
Ajan çıktılarını kalite kontrolünden geçirir.

### `core/multi_agent/rollback.py` — Geri Alma (4.6KB)
Başarısız görevleri geri alır. Dosya değişikliklerini undo eder.

### `core/multi_agent/budget.py` — Bütçe Kontrolü (2.1KB)
Token/API bütçesini ajan bazında takip eder.

### `core/multi_agent/pool.py` — Ajan Havuzu (1.4KB)
Ajan instance'larını yönetir.

### `core/multi_agent/swarm_consensus.py` — Swarm Konsensüs (4.1KB)
Birden fazla ajanın üzerinde uzlaştığı kararlar.

### `core/multi_agent/golden_memory.py` — Altın Bellek (3.7KB)
En başarılı ajan çıktılarını saklar. Gelecek referans.

### `core/multi_agent/audit_bundle.py` — Denetim (3.9KB)
Ajan aktivitelerini loglar.

### `core/multi_agent/job_templates.py` — Görev Şablonları (1.4KB)
Sık kullanılan görev türleri için hazır şablonlar.

### `core/multi_agent/tool_governance.py` — Tool Yönetişimi (7.1KB)
Hangi ajanın hangi tool'u kullanabileceğini belirler.

---

## 6. Reasoning Motoru

### `core/reasoning/chain_of_thought.py` — Düşünce Zinciri (6.4KB)
Step-by-step mantık yürütme. Karmaşık soruları adım adım çözer.

### `core/reasoning/task_decomposer.py` — Görev Ayrıştırıcı (5.5KB)
Büyük görevi küçük alt görevlere böler. Bağımlılık grafiği oluşturur.

### `core/reasoning/code_validator.py` — Kod Doğrulayıcı (5.1KB)
Üretilen kodu syntax ve mantık hatalarına karşı kontrol eder.

### `core/reasoning/deep_researcher.py` — Derin Araştırmacı (6.6KB)
Web araştırması + analiz + sentez. Çok kaynaklı rapor üretir.

### `core/reasoning/multi_model_router.py` — Çok Model Yönlendirici (6.1KB)
Görev tipine göre en uygun LLM'i seçer. Farklı roller için farklı modeller.

### `core/reasoning.py` — Ana Reasoning (19KB)
Reasoning pipeline'ın ana modülü.

---

## 7. Tools — Araç Kütüphanesi (124+ Araç)

### `tools/__init__.py` — Tool Registry (24KB)
Tüm araçları dict olarak kayıt eder. `AVAILABLE_TOOLS` global dictionary.

### Dosya Araçları
| Dosya | İşlev |
|-------|-------|
| `file_tools.py` (12KB) | read, write, delete, copy, move, list, search |
| `file_monitoring.py` (11KB) | Dosya değişiklik izleme (watchdog) |

### Kod & Script
| Dosya | İşlev |
|-------|-------|
| `code_execution_tools.py` (12KB) | Python/Node.js kod çalıştırma |
| `code_executor.py` (10KB) | Güvenli sandbox'ta kod yürütme |
| `script_tools.py` (1.6KB) | Shell script çalıştırma |
| `terminal_tools.py` (14KB) | Terminal komutları, process yönetimi |

### Web & Tarayıcı
| Dosya | İşlev |
|-------|-------|
| `browser/` (8 dosya) | Playwright ile tam tarayıcı kontrolü |
| `browser_automation.py` (10KB) | Web scraping, form doldurma |
| `web_tools/` (4 dosya) | HTTP istekleri, web arama |

### Sistem
| Dosya | İşlev |
|-------|-------|
| `system_tools.py` (25KB) | OS bilgi, process, disk, ağ |
| `network_tools.py` (2.4KB) | Ping, port tarama, DNS |
| `macos_tools/` (6 dosya) | macOS özel: Finder, Spotlight, AppleScript |

### Medya & Görsel
| Dosya | İşlev |
|-------|-------|
| `media_tools.py` (3.3KB) | Resim/video işleme |
| `vision_tools.py` (5.1KB) | Ekran görüntüsü alma, OCR |
| `multimodal_tools.py` (12KB) | Görüntü analizi, ses tanıma |
| `screen_recorder.py` (1.8KB) | Ekran kaydı |

### Ofis & Doküman
| Dosya | İşlev |
|-------|-------|
| `office_tools/` (5 dosya) | Excel, Word, PowerPoint oluşturma |
| `document_tools/` (4 dosya) | PDF, Markdown, rapor |
| `document_generator/` (2 dosya) | Şablonlu doküman üretimi |

### AI & Araştırma
| Dosya | İşlev |
|-------|-------|
| `ai_tools.py` (3.1KB) | Ollama model listesi/pull |
| `research_tools/` (7 dosya) | Web araştırma, sentez, deep research |

### İletişim
| Dosya | İşlev |
|-------|-------|
| `email_tools.py` (9.2KB) | E-posta gönderme/okuma |
| `voice_tools.py` (1.3KB) | Ses dosyası oluşturma |
| `voice/` (6 dosya) | TTS, STT, sesli komut |

### `pro_workflows.py` — Pro İş Akışları (78KB)
En büyük tool dosyası. Karmaşık iş akışları:
- Web proje scaffold (HTML/CSS/JS/React/Next.js)
- E-ticaret panel kontrolü
- Toplu dosya işleme
- Rapor oluşturma
- Veri analizi

---

## 8. Security Modülleri

| Dosya | Boyut | İşlev |
|-------|-------|-------|
| `security/validator.py` | 3.2KB | Input validation, XSS/injection önleme |
| `security/rate_limiter.py` | 5.1KB | Dakikada max istek limiti |
| `security/tool_policy.py` | 7.5KB | Tool allow/deny/requireApproval kuralları |
| `security/approval.py` | 9.3KB | Tehlikeli araçlar için kullanıcı onayı |
| `security/audit.py` | 12KB | Tüm aksiyonların audit log'u |
| `security/keychain.py` | 11KB | macOS Keychain ile API key saklama |
| `security/privacy_guard.py` | 2.5KB | Kişisel veri maskeleme |
| `security/whitelist.py` | 1KB | İzin verilen kullanıcı listesi |
| `core/security/` | 3 dosya | Prompt firewall, secure vault |

---

## 9. Config & Settings

### `config/elyan_config.py` — Ana Config (5.7KB)
Pydantic model tabanlı konfigürasyon. `~/.elyan/elyan.json` dosyasını okur/yazar.

**Config Yapısı:**
```json
{
  "agent": { "name", "personality", "language", "autonomous" },
  "models": {
    "default": { "provider", "model" },
    "fallback": { "provider", "model" },
    "roles": { "reasoning", "inference", "creative", "code" }
  },
  "channels": [{ "type", "enabled", "token" }],
  "tools": { "allow", "deny", "requireApproval" },
  "security": { "operatorMode", "rateLimitPerMinute" },
  "memory": { "enabled", "path", "maxSizeMB" },
  "gateway": { "port", "host" }
}
```

### `config/settings.py` — Legacy Settings (2KB)
### `config/settings_manager.py` — Settings Manager (17KB)
Migration ve backward compatibility.

---

## 10. UI — Arayüzler

### `ui/web/dashboard.html` — Web Dashboard (3772 satır, 199KB)
Tek dosyalık enterprise kontrol paneli. Tailwind CSS + glassmorphism tasarım.

**Dashboard Sekmeleri:**
| Sekme | İçerik |
|-------|--------|
| Genel Bakış | Gateway durumu, CPU/RAM, aktif görevler, maliyet, canlı aktivite |
| Kanallar | Kanal CRUD, test, health monitoring |
| Skills | Skill yönetimi, install/remove/toggle |
| Görevler | Aktif görevler, görev geçmişi |
| Otomasyon | Rutin CRUD, zamanlama, NLP rutin oluşturma |
| Analitik | Kullanım istatistikleri, maliyet analizi, model dağılımı |
| Güvenlik | Güvenlik skoru, audit log, tool kontrolleri |
| Araçlar | Tool listesi, policy yönetimi, diagnostics |
| Ayarlar | Model seçimi, API key yönetimi, agent profili, kanal ayarları |

**WebSocket:** Real-time push bildirimler, aktivite feed, production overlay.

### Desktop UI (PyQt6 tabanlı):
| Dosya | İşlev |
|-------|-------|
| `ui/clean_main_app.py` (55KB) | Ana masaüstü uygulaması |
| `ui/apple_setup_wizard.py` (60KB) | macOS tarzı kurulum sihirbazı |
| `ui/settings_panel_ui.py` (71KB) | Detaylı ayarlar paneli |
| `ui/ai_settings_panel.py` (26KB) | AI model ayarları |
| `ui/clean_chat_widget.py` (31KB) | Chat widget |
| `ui/ollama_manager.py` (31KB) | Ollama model yönetimi GUI |
| `ui/themes.py` (22KB) | Tema sistemi (dark/light) |
| `ui/menubar_app.py` (5.1KB) | macOS menü bar uygulaması |
| `ui/tray_app.py` (3.8KB) | System tray uygulaması |
| `ui/qr_generator.py` (4.4KB) | QR kod oluşturucu |

---

## 11. Scheduler & Otomasyon

### `core/scheduler/cron_engine.py` — Cron Motoru (12KB)
APScheduler tabanlı zamanlayıcı. Cron ifadeleri ile görev planlama.

### `core/scheduler/routine_engine.py` — Rutin Motoru (48KB)
Kullanıcı tanımlı rutinler. NLP'den rutin oluşturma. Adım adım çalıştırma.

### `core/scheduler/heartbeat.py` — Heartbeat (1.5KB)
Sistem canlılık kontrolü. Periyodik health check.

### `core/scheduler/idle_worker.py` — Boşta Çalışan (3.8KB)
Sistem boştayken arka plan görevleri çalıştırır.

### Proactive Sistem (`core/proactive/`):
| Dosya | İşlev |
|-------|-------|
| `alerts.py` (8.9KB) | Proaktif uyarılar |
| `briefing.py` (3.7KB) | Günlük brifing |
| `briefing_sources.py` (11KB) | Brifing veri kaynakları |
| `email_triage.py` (11KB) | E-posta önceliklendirme |
| `intervention.py` (2.8KB) | Kullanıcı müdahalesi gerektiren durumlar |
| `scheduler.py` (7.8KB) | Proaktif görev zamanlayıcı |
| `watchdog_handler.py` (3.8KB) | Dosya sistemi izleme |

---

## 12. Handlers — Telegram Komutları

### `handlers/telegram_handler.py` — Ana Handler (73KB)
Telegram bot'un ana komut işleyicisi. Mesaj alma, komut routing, yanıt gönderme.

| Dosya | İşlev |
|-------|-------|
| `command_router.py` (1.6KB) | Slash komut yönlendirme |
| `telegram_extensions.py` (13KB) | Ek Telegram özellikleri |
| `telegram_browser_commands.py` (7.7KB) | /browse, /screenshot |
| `telegram_routines_commands.py` (11KB) | /routine CRUD |
| `telegram_alerts_commands.py` (7.7KB) | /alert yönetimi |
| `telegram_email_commands.py` (6.3KB) | /email komutları |
| `telegram_proactive_commands.py` (6.3KB) | /proactive ayarları |
| `telegram_voice_commands.py` (3.5KB) | Sesli mesaj işleme |
| `telegram_voice_handler.py` (6KB) | Ses tanıma pipeline |

---

## 13. Utils & Yardımcılar

| Dosya | İşlev |
|-------|-------|
| `utils/logger.py` (1.2KB) | Logging yapılandırması. Dosya + konsol output |
| `utils/ollama_helper.py` (1.3KB) | Ollama API yardımcıları |

---

## 14. Pipeline Akışı (Detaylı)

```
Kullanıcı Mesajı
      │
      ▼
┌─────────────────────────┐
│ 1. Gateway Server       │  HTTP/WS üzerinden mesaj alır
│    server.py             │  CORS, auth kontrolü
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 2. Gateway Router       │  Adapter'dan mesajı alır
│    router.py             │  Welcome flow, typing indicator
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 3. Agent.process()      │  Ana pipeline başlar
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 4. Input Validation     │  Boş/zararlı girdi kontrolü
│    security/validator    │  XSS, injection, max length
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 5. Short Input Guard    │  "tamam", "ok" gibi kısa girdiler
│                          │  LLM çağırmadan yanıt verir
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 6. Context Intelligence │  Domain tespiti (web_dev, file_ops...)
│    context_intelligence  │  Özel prompt injection
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 7. Neural Routing       │  Rol: code/reasoning/creative/inference
│    neural_router         │  Complexity: 0.3 veya 0.8
│                          │  Model seçimi: ollama/gpt/claude
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 8. Quick Intent         │  Regex ile hızlı komut eşleştirme
│    quick_intent          │  "masaüstünü listele" → ls ~/Desktop
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 9. Intent Parser        │  Deterministic intent parsing
│    intent_parser         │  action: "create_file" params: {...}
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 10. LLM Call            │  AI modeline sorgu
│     llm_client           │  System prompt + context + user input
│     + llm_optimizer      │  Token optimizasyonu
│     + llm_cache          │  Cache kontrolü
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 11. Tool Extraction     │  LLM yanıtından tool çağrısı çıkar
│     parameter_extractor  │  Parametre doğrulama
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 12. Tool Execution      │  Aracı çalıştır
│     kernel.tools.execute │  Timeout guard, error handling
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 13. Output Contract     │  Sonuç doğrulama
│     output_contract      │  Dosya yazıldı mı? İçerik doğru mu?
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 14. Self-Correction     │  Doğrulama başarısız → tekrar dene
│     (retry/repair loop)  │  Max 1 retry
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 15. Response Format     │  Yanıtı kullanıcı diline çevir
│     response_tone        │  Emoji, markdown, özet
│     i18n                 │
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 16. Learning            │  Başarılı/başarısız kalıp kaydet
│     learning_engine      │  Feedback store güncelle
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ 17. Memory Save         │  Sohbet geçmişine kaydet
│     memory               │  Kullanıcı profili güncelle
└──────────┬──────────────┘
           ▼
      Kullanıcıya Yanıt
      (aynı kanal üzerinden)
```

---

## 15. Dosya Listesi (Tam)

### Kök Dizin
```
main.py                    → CLI entry point (789 satır)
setup.py                   → Paket kurulumu
pyproject.toml             → Build konfigürasyonu
requirements.txt           → Bağımlılık listesi
Dockerfile                 → Docker container
install.sh                 → Kurulum scripti
elyan_entrypoint.py        → Alternatif entry point
mkdocs.yml                 → Dokümantasyon build config
.env                       → Çevresel değişkenler
.gitignore                 → Git ignore kuralları
```

### core/ (96+ dosya)
```
agent.py                   → Ana pipeline motoru (4715 satır)
neural_router.py           → Model/rol yönlendirici
kernel.py                  → Tool registry
llm_client.py              → LLM API istemcisi
llm_cache.py               → LLM yanıt cache
llm_optimizer.py           → Prompt optimizasyonu
model_orchestrator.py      → Provider yönetimi
memory.py                  → Uzun süreli bellek (SQLite)
learning_engine.py         → Öğrenme motoru
context_intelligence.py    → Bağlam analizi
intent_parser.py           → Niyet çözücü
quick_intent.py            → Hızlı niyet
fuzzy_intent.py            → Bulanık eşleştirme
fast_response.py           → Hızlı yanıt
parameter_extractor.py     → Parametre çıkarıcı
output_contract.py         → Çıktı doğrulama
task_engine.py             → Görev motoru (86KB)
intelligent_planner.py     → Akıllı planlayıcı
comprehensive_executor.py  → Kapsamlı yürütücü
workflow_engine.py         → İş akışı motoru
action_lock.py             → Çakışma önleyici
monitoring.py              → Sistem izleme
pricing_tracker.py         → Maliyet takibi
pipeline_state.py          → Pipeline durumu
feedback.py                → Geri bildirim
self_healing.py            → Otomatik onarım
self_improvement.py        → Otomatik iyileştirme
response_tone.py           → Ton yönetimi
error_handler.py           → Hata yönetimi
smart_cache.py             → Akıllı cache
smart_paths.py             → Yol çözücü
smart_notifications.py     → Akıllı bildirimler
session_manager.py         → Oturum yönetimi
user_profile.py            → Kullanıcı profili
conversation_memory.py     → Sohbet bağlamı
...ve 60+ daha
```

### tools/ (32+ dosya)
```
__init__.py                → Tool registry (124+ araç)
file_tools.py              → Dosya okuma/yazma/silme
system_tools.py            → Sistem bilgisi
terminal_tools.py          → Terminal komutları
code_execution_tools.py    → Kod çalıştırma
browser_automation.py      → Tarayıcı otomasyonu
pro_workflows.py           → Pro iş akışları (78KB)
email_tools.py             → E-posta
media_tools.py             → Medya işleme
vision_tools.py            → Ekran görüntüsü/OCR
ai_tools.py                → Ollama yönetimi
...ve alt dizinler
```

### security/ (9 dosya)
```
validator.py               → Input validation
rate_limiter.py            → Rate limiting
tool_policy.py             → Tool erişim politikası
approval.py                → Onay mekanizması
audit.py                   → Audit logging
keychain.py                → macOS Keychain
privacy_guard.py           → Veri maskeleme
whitelist.py               → Kullanıcı whitelist
```

---

## 16. Hardening Katmanı (v20.1.0+)

### `core/evidence_gate.py` — Kanıt Geçidi
Tool çıktısı (dosya yolu, hash, screenshot) olmadan "teslim/oluşturuldu" iddialarını response'dan siler.

**Kural:** Delivery claim var + evidence yok → `⏳ İşlem devam ediyor` ile değiştir.

### `core/job_contract.py` — İş Sözleşmesi
Her iş için typed contract: beklenen artifact'lar, izinli tool'lar, QA check'ler, delivery modu.
`verify_artifacts()` → disk'te dosya var mı kontrol eder.
`run_qa()` → file_exists, html_valid, min_file_size gibi kontrolleri çalıştırır.

### `core/pipeline.py` — Modüler Pipeline
agent.py monolitini bağımsız stage'lere böler:

| Stage | Sınıf | İşlev |
|-------|-------|-------|
| 1 | `StageValidate` | Input validation (boş, uzun, zararlı) |
| 2 | `StageRoute` | Neural routing + job type detection |
| 3 | `StageExecute` | LLM call + tool execution |
| 4 | `StageVerify` | Contract verification + QA |
| 5 | `StageDeliver` | Evidence gate + response formatting |

### `core/job_templates.py` — Zorunlu İş Şablonları
8 template: web_project, research_report, file_operations, code_project, data_analysis, communication, system_ops, browser_task.

### `tests/golden_tests.py` — Regresyon Test Paketi
19 golden test. Import check + template detection + evidence gate unit tests.

### `core/learning_engine.py` — Bellek Politikası (güncellendi)
- Sadece **başarılı** etkileşimlerden yeni pattern oluşturur
- Başarısız → mevcut pattern'ın güvenini **0.1 düşürür**
- confidence < 0.3 → pattern **silinir** (yanlış öğrenme engellenir)
- `record_outcome` başarısız işlerde tool/quality preference **yazmaz**

---

## 17. Usta Seviye Mimari — Contracted DAG with Gates (CDG)

> **Felsefe:** "En zor görevlerde bile tutarlı bitiren, kullanıcı tarzına uyan, kanıtlı teslim yapan" bir fabrika.  
> Tek bir sihirli model değil; **doğru algoritma + doğru yürütme disiplini**.

### 17.1 Çekirdek Algoritma: Plan-and-Execute + DAG + Quality Gates

Üç katman birlikte çalışır:

```
┌────────────────────────────────────────────────────────────────┐
│  A) TASK DECOMPOSITION (Görevi Parçalama)                       │
│                                                                  │
│  Kullanıcı İsteği → Goal → Deliverables → Constraints → Style   │
│                          ↓                                       │
│                    DAG (Directed Acyclic Graph)                   │
│                                                                  │
│  düğümler = alt görevler (research, outline, draft, assets,     │
│             code, packaging, QA)                                 │
│  kenarlar = bağımlılıklar (outline olmadan draft yok,           │
│             assets olmadan gallery yok)                           │
│                                                                  │
│  ► Paralel çalıştırma                                           │
│  ► Doğru sırayla yürütme                                        │
│  ► Geri dönüşlerde sadece ilgili dalı düzeltme                  │
└────────────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────────────┐
│  B) EXECUTION (İcra)                                            │
│                                                                  │
│  Her DAG düğümü için:                                           │
│  • agent + tool permission + budget + acceptance tests           │
│  • Düğümler idempotent: tekrar çalışırsa bozmamalı              │
└────────────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────────────┐
│  C) VERIFICATION (Doğrulama)                                    │
│                                                                  │
│  • Her düğümün çıktısı "contract check"ten geçer                │
│  • En sonda "end-to-end QA" (Playwright + static + content)     │
│                                                                  │
│  Ustalık = Güvenilirlik                                         │
└────────────────────────────────────────────────────────────────┘
```

### 17.2 Orkestrasyon Beyni: HTN + ReAct + Critic

Hibrit yaklaşım üç bileşenden oluşur:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  HTN         │────▶│  ReAct       │────▶│  Critic      │
│  (İskelet)   │     │  (İcra)      │     │  (Kalite)    │
├─────────────┤     ├─────────────┤     ├─────────────┤
│ Job template │     │ Think → Act  │     │ "Bu adım     │
│ standart     │     │ → Observe    │     │  bitti mi?"  │
│ alt adımlara │     │ döngüsü      │     │              │
│ böler        │     │              │     │ LLM'nin      │
│              │     │ Belirli      │     │ değil,       │
│ Determinism  │     │ adımlarda    │     │ TESTIN       │
│ sağlar       │     │ LLM          │     │ kararı       │
└─────────────┘     └─────────────┘     └─────────────┘
```

**HTN (Hierarchical Task Networks):** `research_report_job`, `web_project_job`, `coding_task_job` gibi template'ler. Görevi standart alt adımlara böler. Determinism sağlar.

**ReAct (Reason + Act):** LLM plan üretir + tool çağırır ama sadece belirli adımlarda. Her adımda `think → act → observe` döngüsü.

**Critic/Verifier:** Ayrı bir ajan (veya kural seti). LLM'nin "bitti" demesini değil, **testin** "bitti" demesini sağlar.

### 17.3 Job Template Tasarımları

#### A) Araştırma — Deep Research Job

```
Input ──▶ [1] Scope + Soru Listesi
              (hedef netleştirme, ama az soru sor)
          ──▶ [2] Kaynak Toplama
              (web: Playwright + readability extraction)
          ──▶ [3] Not Çıkarma
              (claim → source eşleştirme)
          ──▶ [4] Sentez
              (outline oluşturma)
          ──▶ [5] Rapor Yazma
              (makale)
          ──▶ [6] Kaynakça + Doğrulama
              (kaynak link/alıntı kontrolü, tarih)
          ──▶ [7] Stil Uyumu + Son QA
```

**Teknoloji:**
- Web araştırma: Playwright + readability extraction
- Bilgi modeli: "Claim Graph" (iddia-kaynak ağı)
- Doğrulama: Kaynak link kontrolü, tarih doğrulama

#### B) Dosya Oluşturma — Artifact Factory Job

```
Input ──▶ [1] Deliverable contract.json
              (dosya listesi + minimum içerik)
          ──▶ [2] Build (tam dosyalar üret)
          ──▶ [3] Write (Tool Runner → diske yaz)
          ──▶ [4] Verify (hash/size + parse checks)
          ──▶ [5] Package (zip + manifest)
```

**Teknoloji:**
- Typed artifacts + SHA256 manifest
- Patch-based repair (diff, tam dosya yerine)

#### C) Makale Yazma — Editorial Job

```
Input ──▶ [1] Audience + Tone + Format (brief)
          ──▶ [2] Outline (H1/H2 plan)
          ──▶ [3] Draft 1
          ──▶ [4] Style Pass (kullanıcı tarzı)
          ──▶ [5] Fact Check Pass (gerekiyorsa)
          ──▶ [6] Final Polish (başlık, giriş, CTA)
```

**Teknoloji:**
- **Style Card:** 10-15 satırlık kullanıcı tarz profili
- **Rubric Scoring:** Akış, netlik, özgünlük, hedefe uygunluk

#### D) Kodlama — Software Job

```
Input ──▶ [1] Spec + Acceptance Tests
              (done criteria test edilebilir)
          ──▶ [2] Implement
          ──▶ [3] Unit Tests / Type Checks / Lint
          ──▶ [4] Run / Build
          ──▶ [5] Regression Checks
          ──▶ [6] PR-Style Summary
```

**Teknoloji:**
- Statik analiz: mypy / ruff / pytest (Python), eslint / vitest (JS)
- Sandbox runner: Container-based execution
- Test-first contract: "Tests define done"

### 17.4 Kullanıcı Tarzı: Style Profile + Constraint Engine

> Ustalığın yarısı kalite, yarısı **tarz uyumu**.

#### A) Style Profile (kalıcı, kısa)

```yaml
# ~/.elyan/style_profile.yaml
language: tr
tone: kurumsal ama anlaşılır
format: kısa paragraflar, az markdown
preference: snippet değil, tam dosya
never:
  - jQuery kullanma
  - Gereksiz emoji koyma
  - Kanıtsız teslim iddiası
```

Profile Memory'de durur. Her job başında **sadece 5-7 satır** olarak prompt'a girer.

#### B) Constraint Engine (sert kurallar, LLM'den bağımsız)

| Kural | Enforcement |
|-------|------------|
| "Dosya yazdıysan tool kanıtı göster" | `evidence_gate.py` |
| "Claim varsa kaynak göster" | Response formatter |
| "Kod varsa test çalıştır" | `output_contract.py` |
| "Contract check geçmediyse teslim etme" | `job_contract.py` |

### 17.5 Çok Model Stratejisi

> Her adım için aynı ağır modeli kullanma.

| Rol | Model Tipi | Neden |
|-----|-----------|-------|
| **Router** | Küçük/ucuz | Intent + risk + template seçimi |
| **Planner** | Orta | Contract + DAG oluşturma |
| **Builder** | Güçlü | Kod / makale / içerik üretimi |
| **Critic** | Orta + kural tabanlı | Doğrulama + kalite check |
| **Tool Runner** | LLM değil | State machine, deterministic |

**Sonuç:** Hem maliyet düşer hem kalite artar.

### 17.6 İyileştirme Algoritması: Telemetry → Failure Clustering → Auto-Patch

Random öğrenme değil, **mühendislik**:

```
[1] Her fail'de "failed_check_code" üret
    Örn: HTML_MISSING_CLOSING_TAG, TOOL_WRITE_EMPTY, SOURCES_MISSING

[2] Failure clustering → en sık 10 hata

[3] Her hata için "auto-patch playbook":

    TOOL_WRITE_EMPTY
    → write_file sonrası size>0 doğrula
    → değilse retry + different strategy

    HTML_BAD_STRUCTURE
    → template enforce + validator fix

    SOURCES_MISSING
    → kaynak claim'leri zorunlu kıl
    → kaynaksız claim'leri sil
```

**Bu, öğrenmeyi deterministik ve güvenli yapar.**

### 17.7 Teknoloji Önerileri (Python 3.12)

| Alan | Teknoloji | Not |
|------|-----------|-----|
| DAG yürütme | Hafif kendi runner | NetworkX opsiyonel |
| Job queue | asyncio queue + SQLite state | Minimal, yeterli |
| Tool execution | subprocess + sandbox | Container mümkünse |
| Web automation | Playwright | Mevcut |
| Content parsing | trafilatura / readability-lxml | Web içerik çıkarma |
| Text quality | Rubric + küçük critic model | Scoring |
| Memory | SQLite + embeddings + TTL | TTL şart |
| Observability | Structured logs (JSON) + dashboard | OpenTelemetry opsiyonel |

### 17.8 Default Execution Motoru: CDG (Contracted DAG with Gates)

```
Input
  │
  ▼
┌──────────────────┐
│  CONTRACT         │  Goal → Deliverables → Constraints → Style
│  job_contract.py  │  Beklenen dosyalar + QA kuralları
└────────┬─────────┘
         ▼
┌──────────────────┐
│  DAG PLAN         │  Contract → alt görev grafiği
│  pipeline.py      │  Bağımlılıklar + paralel dallar
└────────┬─────────┘
         ▼
┌──────────────────┐
│  NODE EXECUTION   │  Her düğüm:
│  (ReAct loop)     │  think → act → observe
│                    │  tool evidence üretir
└────────┬─────────┘
         ▼
┌──────────────────┐
│  NODE QA GATE     │  Düğüm çıktısı → contract check
│  output_contract  │  Geçmediyse → patch repair
│  + evidence_gate  │  (sadece hatalı bloğu düzelt)
└────────┬─────────┘
         ▼
┌──────────────────┐
│  END-TO-END QA    │  Tüm artifact'lar → disk doğrulama
│  job_contract     │  + Playwright screenshot (web)
│  verify_artifacts │  + static checks (code)
└────────┬─────────┘
         ▼
┌──────────────────┐
│  DELIVERY         │  Evidence manifest + artifact'lar
│  evidence_gate    │  Kanıt yoksa → teslim engellenir
│                    │  SHA256 hash + dosya boyutu
└──────────────────┘
```

**Bu akış Elyan'ın "usta" seviyeye çıkmasını sağlar:**
- Her iş **contract ile başlar**
- Her adım **kanıt üretir**
- Her çıktı **test edilir**
- Teslim **sadece kanıtla yapılır**

---

## Toplam İstatistikler

| Metrik | Değer |
|--------|-------|
| **Toplam Python Dosyası** | ~200+ |
| **Toplam Kod Satırı** | ~80.000+ |
| **Core Modülleri** | 100+ dosya |
| **Tool Sayısı** | 124+ araç |
| **Channel Adapter** | 12 platform |
| **Uzman Ajan** | 6 |
| **API Endpoint** | 80+ |
| **Dashboard Satır** | 3772 |
| **Golden Tests** | 19 (19/19 pass) |
| **Job Templates** | 8 |
| **Hardening Modülleri** | 5 (evidence_gate, job_contract, pipeline, job_templates, golden_tests) |

---

*Bu dokümantasyon Elyan AI Agent Framework v20.1.0 için oluşturulmuştur.*
