# ROADMAP.md — Elyan Stratejik Yol Haritası

**Son Güncelleme**: 2026-04-12
**Strateji**: A ile Kazan (Türkiye KOBİ) → B ile Büyü (Ambient/Proaktif Global)
**Aktif Faz**: P1 kullanıcı deneyimi + Faza A connector altyapısı

---

## STRATEJİK YÖNELIM

### Neden A + B?

Piyasadaki tüm büyük oyuncular (Anthropic, OpenAI, Google, Microsoft) reaktif kuruyorlar — sen sormadan hareket etmiyorlar. Hepsi İngilizce-first, cloud-first, genel amaçlı.

Elyan iki aşamada farklılaşır:

**Faza A — Türkiye KOBİ Operatörü**
- Yabancı şirketlerin asla değmeyeceği derinlik: e-Fatura, Logo/Netsis, SGK, KEP
- Iyzico zaten entegre → ilk gelir buradan
- KVKK uyumlu by design — veri yerinden çıkmıyor
- Gerçek müşteri + gerçek kullanım verisi = Faza B'nin yakıtı

**Faza B — Ambient/Proaktif Global Ajan**
- Reaktif → Proaktif dönüşüm: dünyada kimse ciddiye almıyor
- A fazından toplanan veriyle eğitilmiş pattern engine
- "Sessiz ortak" konumu — arka planda yaşar, önemli anlarda ortaya çıkar
- Global çıkış: Türkiye'de kanıtlanmış ürün

---

## STRATEJİK FAZLAR

### Faza A — Türkiye KOBİ Operatörü (0-12 Ay)

#### A-1: Türkiye Connector Paketi (Ay 1-3)
**Hedef**: Türk iş dünyasının günlük acılarını çözen connector'lar

| Connector | Açıklama | Öncelik |
|-----------|----------|---------|
| e-Fatura | GİB entegrasyonu, fatura oluştur/gönder/arşivle | P0 |
| e-Arşiv | e-Arşiv fatura portalı | P0 |
| Iyzico (mevcut) | Ödeme al, abonelik yönet | ✓ |
| Logo | Logo GO/Tiger muhasebe entegrasyonu | P1 |
| Netsis | Netsis Wings/Standard entegrasyon | P1 |
| Luca | Luca muhasebe connector | P1 |
| e-Devlet | Belge sorgulama, vergi borcu, sicil | P2 |
| SGK | Bildirim takibi, borç sorgulama | P2 |
| KEP | Kayıtlı Elektronik Posta yönetimi | P2 |

**Teknik gereksinim**:
- Her connector `integrations/turkey/` altında kendi paketi
- `ConnectorBase` abstract class'tan türetilmeli
- Her connector: bağlantı testi, health check, retry logic
- Tüm çağrılar audit log'a düşmeli
- KVKK: kişisel veri işlenmeden önce consent kaydı

#### A-2: Türkçe Dil ve Kültür Katmanı (Ay 1-2)
- Tüm UI metinleri Türkçe-first (mevcut bazıları İngilizce)
- Tarih formatı: DD.MM.YYYY (GİB standardı)
- Para birimi: TRY öncelikli
- İş yazışması şablonları: Türk iş kültürüne uygun
- Hata mesajları Türkçe (mevcut `translateBillingError` genişletilmeli)

#### A-3: KOBİ Operatör Senaryoları (Ay 2-4)
Tek komutla çalışan, gerçek KOBİ acılarını çözen akışlar:

```
"Bu ayın KDV özetini çıkar"
→ Muhasebe yazılımından veri çek
→ GİB formatına dönüştür
→ Taslak hazırla, göster, onayla, gönder

"Tedarikçi faturalarını işle"
→ e-posta eklerini tara
→ e-Fatura/PDF oku, muhasebe yazılımına kaydet
→ ödeme planını takvime ekle

"Aylık raporu hazırla"
→ Muhasebe verisi + banka ekstreleri + müşteri listesi
→ Şablona dök, PDF oluştur, yetkililere gönder
```

#### A-4: Decision Fabric — Karar Hafızası (Ay 3-5)
Elyan'ın en kritik farklılaştırıcılarından biri: sadece **ne** yaptığını değil **neden** yaptığını hatırlamak.

```python
# Her kritik aksiyonla birlikte bağlam kaydedilir
{
  "karar": "Tedarikçi X sözleşme yenilenmedi",
  "bağlam": "Q3 fiyat artışı + 3 kargo gecikmesi",
  "onaylayan": "kullanıcı",
  "tarih": "2026-03-14",
  "workspace_id": "...",
  "referans_event_ids": [...]
}
```

Arayüz: "Neden bu tedarikçiyle çalışmıyoruz?" → Elyan cevaplar.

#### A-5: Türkiye İlk Müşteri Edinimi (Ay 2-6)
- 10 pilot KOBİ (muhasebe yoğun sektörler: inşaat, tekstil, ithalat-ihracat)
- Onboarding: 15 dakikada çalışan sistem
- Ölçüm: günlük aktif kullanım, zaman tasarrufu, hata azalması
- Feedback döngüsü: 2 haftada bir kullanıcı görüşmesi

---

### Faza B — Ambient/Proaktif Global Ajan (12-24 Ay)

#### B-1: Pattern Engine (Ay 10-13)
A fazından toplanan gerçek kullanım verisi pattern engine'i besler.

```python
class PatternEngine:
    """
    Kullanıcı davranışını izler, tekrarlayan işleri tespit eder,
    proaktif öneri üretir.

    Girdi: activity_log events (her tool çağrısı, her onay, her red)
    Çıktı: PatternProposal (öneri tipi, güven skoru, tetikleyici)
    """

    def detect_recurring(self, window_days=30) -> list[Pattern]:
        # "Her Pazartesi 09:00'da aynı 3 adım"
        pass

    def suggest_automation(self, pattern: Pattern) -> AutomationProposal:
        # Otomasyona almayı öner, kullanıcı onayı iste
        pass

    def score_confidence(self, pattern: Pattern) -> float:
        # Öneri güveni: kaç kez tekrarlandı, ne kadar benzer
        pass
```

**Kritik kural**: Düşük güvenli öneri asla gösterilmez. Kullanıcı rahatsız edilmemeli.

#### B-2: Proaktif Bildirim Sistemi (Ay 12-14)
```
"Yarın 09:00'da Müşteri X sunumu — geçen ay şunları konuşmuştunuz.
 Slaytları o bağlamla güncelledim. Onaylarsanız kaydedeyim."

"Bu tedarikçiyle son iletişimden 3 hafta geçti.
 Takip mesajı hazırladım. Göndermemi ister misiniz?"

"Her ay sonu aynı raporu hazırlıyorsun.
 Bu ay verilerini topladım, taslak hazır."
```

Bildirim kuralları:
- Gün içinde maksimum 3 proaktif bildirim
- Reddedilen öneri tipi 30 gün sessiz kalır
- Kullanıcı "şimdi değil" diyebilir, hatırlatma zamanı seçebilir

#### B-3: Ambient Context Engine (Ay 13-16)
A fazındaki `PersonalContextEngine`'i genişlet:
- Takvim: "1 saat sonra toplantı var, bağlamı hazırlayayım mı?"
- Uygulama değişimi: "Faturalamaya geçtin — devam eden görev var"
- Mesai sonu: "Bugün 3 yarım kalan görev — yarın için sıralayayım mı?"

#### B-4: Global Çıkış Hazırlığı (Ay 18-24)
- İngilizce UI (çeviri katmanı, Türkçe core bozulmadan)
- Connector API: üçüncü parti connector marketplace
- Multi-tenant SaaS hazırlığı (hosted version)
- Pricing: global plan + Türkiye özel plan

---

## TEKNİK FAZLAR (Devam Eden)

### Tamamlanan ✓
- Phase 1: Canonical commercial domain (billing types, plan kataloğu)
- Phase 2: Iyzico provider abstraction
- Phase 3: Workspace RBAC + membership + owner bootstrap
- Phase 7 (kısmi): Gateway CSRF enforcement

### Aktif

#### Phase 0 — P0 Taskları (Tamamlandı / Doğrulandı)
1. `getCurrentLocalUser()` boş email guard mevcut
2. `OnboardingScreen 2.tsx` repo yüzeyinden kaldırıldı
3. Vite build doğrulandı
4. `.env.example` güncellemesi mevcut (`ELYAN_ADMIN_TOKEN`, `ELYAN_PORT`)

#### Phase 4 — Admin Control Plane
- Workspace overview
- Subscription management
- Credit ledger UI
- Token pack purchase flow
- Member/role management
- Approval queue
- Connector health dashboard

#### Phase 5 — Learning Fabric
- User memory (mevcut foundation üzerine)
- Workspace intelligence (mevcut temel çalışıyor)
- Global aggregate intelligence
- Privacy classify + consent gate
- Offline eval + shadow/canary promotion

#### Phase 6 — Runtime Credit Enforcement
- LLM/tool usage → commercial ledger bağlantısı
- Calibrated usage estimator
- Soft degrade ordering (included → purchased → degraded)

### Güvenlik Fazı (Paralel)

#### SEC-1: Kritik Güvenlik Düzeltmeleri
1. WebSocket token URL'den çıkar → WS message payload'a taşı
2. `hmac.compare_digest` ile webhook imzası
3. Query string admin auth kaldır (`query.get("token")`)
4. Dosya yükleme MIME whitelist + boyut sınırı
5. Prompt injection firewall → case-insensitive + semantic

#### SEC-2: Auth Güçlendirme
6. Rate limiter'ı auth endpoint'lerine bağla (altyapı mevcut)
7. Session token localStorage → HttpOnly cookie
8. Sign-out: localStorage + WebSocket + in-flight temizlik
9. Path traversal: symlink-safe `resolve()`

#### SEC-3: Altyapı
10. `requirements.txt` exact pin (`==`)
11. SQLite transaction isolation seviyesi
12. Audit log şifrelemesi

---

## Mühendislik Disiplini

### Preservation-First (Değiştirme Değil, Genişlet)
- Çalışan davranışı önce koru
- Replacement yerine wrapper, adapter, verifier
- Non-trivial değişiklikler feature flag ile
- Planner/router/verifier değişiklikleri shadow mode olmadan aktifleştirme

### Test Protokolü
Her değişiklik sonrası:
```bash
# 1. Python syntax
.venv/bin/python -c "import ast; ast.parse(open('core/gateway/server.py').read()); print('OK')"

# 2. TypeScript
cd apps/desktop && PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/tsc --noEmit

# 3. Backend + healthz
.venv/bin/python main.py start --port 18789 &
sleep 6
curl -s http://127.0.0.1:18789/healthz | python3 -m json.tool | grep admin_token

# 4. Frontend build
cd apps/desktop && PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/vite build 2>&1 | tail -10
```

---

## Açık Riskler

| Risk | Seviye | Mitigation |
|------|--------|------------|
| `core/agent.py` 14.766 satır monolith | YÜKSEk | Dokunmadan çalıştır, yavaş refactor |
| `core/gateway/server.py` 10K satır | YÜKSEK | Modul extraction plan hazırlanıyor |
| WebSocket token URL'de açıkta | KRİTİK | SEC-1'de düzeltiliyor |
| Webhook imzası timing attack | KRİTİK | SEC-1'de düzeltiliyor |
| Rate limiting tanımlandı ama bağlanmamış | ORTA | SEC-2'de tamamlanıyor |
| Stripe route'ları deprecated, frontend taşınmadı | ORTA | Iyzico migration devam ediyor |
| Learning fabric hala design seviyesinde | ORTA | Phase 5'te implemente ediliyor |
