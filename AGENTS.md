# AGENTS.md — Mimari, Tasarım Felsefesi ve Codex Direktifleri

> Bu dosyayı her çalışmaya başlamadan önce oku.
> Mimariyi anlamadan kod yazma.

---

## BÖLÜM 1: STRATEJİK BAĞLAM

Elyan iki fazda büyüyor:

**Faza A (Şu an aktif)**: Türkiye KOBİ Operatörü
- e-Fatura, Logo/Netsis, SGK, KEP connector'ları
- Iyzico Credits bazlı ödeme
- KVKK uyumlu local-first

**Faza B (12 ay sonra)**: Ambient/Proaktif Global Ajan
- Pattern engine: kullanıcı davranışını izle, proaktif öner
- A fazından toplanan veriyle eğitim
- Global çıkış

Şu an A fazındayız. Faza B altyapısını (pattern detection, decision fabric) tasarlarken bozma, ilerleyen fazlarda aktive edilecek.

---

## BÖLÜM 2: CODEX — HALLÜSINASYON ÖNLEYICI KURALLAR

> Bu bölüm, AI coding agent'ların (Codex, Claude, vb.) yanlış kod yazmasını önlemek için yazılmıştır. Her kural bir geçmiş sorundan öğrenilmiştir.

### KURAL 1: Var Olmayan Fonksiyon/Sınıf Çağırma

**YASAK**:
```python
# Bu fonksiyonlar VAR OLMAYABILIR — önce kontrol et
get_cognitive_integrator()       # Yok
DeadlockPreventionWidget()       # Yok
SleepConsolidationWidget()       # Yok
```

**ZORUNLU**: Bir fonksiyon/sınıf kullanmadan önce `grep -r "def get_cognitive_integrator"` ile var olduğunu doğrula.

---

### KURAL 2: SQLAlchemy 2.0 — text() Zorunlu

**YASAK**:
```python
conn.execute("SELECT * FROM users WHERE id = ?", [user_id])  # ? ÇALIŞMAZ
conn.execute(f"SELECT * FROM users WHERE id = {user_id}")    # SQL INJECTION
```

**ZORUNLU**:
```python
from sqlalchemy import text
conn.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id})
```

---

### KURAL 3: DB Tablo Tanımlama

**YASAK**: Tablo oluşturmak için Alembic, ayrı migration script veya CREATE TABLE raw SQL.

**ZORUNLU**: `core/persistence/runtime_db.py`'de `LOCAL_METADATA` altına `Table(...)` tanımla. `create_all()` otomatik yaratır.

```python
# core/persistence/runtime_db.py — her yeni tablo buraya
from sqlalchemy import Table, Column, String, Integer, MetaData

LOCAL_METADATA = MetaData()

my_new_table = Table(
    "my_new_table",
    LOCAL_METADATA,
    Column("id", String, primary_key=True),
    Column("data", String),
)
```

---

### KURAL 4: Routing Guard Sırası — Değiştirme

`apps/desktop/src/app/routes.tsx` içindeki sıra kesinlikle bu olmalı:
1. `onboardingComplete: false` → `/onboarding`
2. `onboardingComplete: true` + `isAuthenticated: false` → `/login`
3. `onboardingComplete: true` + `isAuthenticated: true` → `/home`

**Bu sırayı değiştirme.**

---

### KURAL 5: Auth Middleware — Üç Yol

`_require_user_session()` şu üç yolu kabul eder:
1. `X-Elyan-Session-Token` header
2. `elyan_user_session` cookie
3. `X-Elyan-Admin-Token` header — sadece `_is_loopback_request()` true ise

Admin token için loopback kontrolü zorunlu. Bunu kaldırma.

---

### KURAL 6: Workspace Learning Loop — Bozma

`core/agent.py` → `_finalize_turn()` → `record_task_outcome()` zinciri.

Bu akışa dokunursan workspace intelligence öğrenemez. Değiştirme.

---

### KURAL 7: Bootstrap Sonrası mark_setup_complete()

Owner bootstrap tamamlandıktan sonra:
```python
from cli.onboard import mark_setup_complete
mark_setup_complete()
```
Bu çağrı olmadan `/healthz` → `setup_complete: false` döner ve frontend onboarding'e yönlendirir.

---

### KURAL 8: Test-First — Stub Bırakma

Her yeni özellik için önce test yaz, sonra implement et.

**YASAK**:
```python
def my_new_feature():
    pass  # TODO: implement later

def my_new_feature():
    raise NotImplementedError("coming soon")
```

**ZORUNLU**: Ya tam implement et, ya da o özelliği bu PR'a alma.

---

### KURAL 9: Feature Flag Olmadan Planner/Router Değişikliği

`core/agent.py`, `core/pipeline.py`, `core/gateway/server.py` içindeki planner, router veya verifier mantığını feature flag olmadan değiştirme.

```python
# core/feature_flags.py — yeni flag buraya
MY_NEW_FEATURE = FeatureFlag("my_new_feature", default=False)

# Kullanım
if feature_flags.MY_NEW_FEATURE.enabled:
    # yeni davranış
else:
    # eski davranış
```

---

### KURAL 10: Async/Threading Karışıklığı

**YASAK**:
```python
# Flask route içinde async çalıştırma
import asyncio
result = asyncio.run(some_async_function())  # Thread pool'u bloke eder
```

```python
# Async context'te threading lock
import threading
lock = threading.RLock()  # asyncio context'te deadlock riski
async with lock:  # YANLIŞ
    ...
```

**ZORUNLU**: Async context → `asyncio.Lock()`. Sync context → `threading.RLock()`. Karıştırma.

---

### KURAL 11: Dosya Yükleme Güvenliği

Kullanıcıdan gelen dosyalarda:
1. MIME type whitelist kontrolü
2. Dosya boyutu sınırı
3. Filename sanitization (`secure_filename()` veya eşdeğeri)
4. Upload dizini dışına çıkma kontrolü

---

### KURAL 12: WebSocket Token

Token'ı asla URL parametresine koyma:
```typescript
// YASAK — browser history'ye düşer
socketUrl.searchParams.set("token", token);
```

Token'ı WebSocket bağlantı kurulduktan sonra ilk message payload'unda gönder.

---

### KURAL 13: Monolith Dosyalara Dokunma Politikası

`core/agent.py` (14K satır) ve `core/gateway/server.py` (10K satır) yüksek risk dosyaları.

- Küçük, targeted değişiklik → kabul
- "Refactor" veya "reorganize" amaçlı büyük değişiklik → ONAY GEREKTİRİR
- Yeni fonksiyon ekleme → ok, ama existing fonksiyonlara dokunma

---

### KURAL 14: Error Handling — Silent Catch Yasak

**YASAK**:
```python
try:
    result = some_operation()
except:
    pass  # sessizce yut
```

**ZORUNLU**:
```python
try:
    result = some_operation()
except SomeSpecificError as e:
    logger.error(f"operation failed: {e}", exc_info=True)
    raise  # veya anlamlı fallback
```

---

### KURAL 15: Türkiye Connector Geliştirme Standardı

`integrations/turkey/` altındaki her connector:

```python
from integrations.base import ConnectorBase

class EFaturaConnector(ConnectorBase):
    """
    GİB e-Fatura connector.

    Üretim URL: https://efatura.gib.gov.tr
    Test URL: https://efaturatest.gib.gov.tr
    """

    def health_check(self) -> bool:
        """Bağlantı testi — her başlangıçta çağrılır."""
        ...

    def test_credentials(self) -> bool:
        """Kullanıcı credentials geçerli mi?"""
        ...
```

---

## BÖLÜM 3: MİMARİ FELSEFE

### Yedi Tasarım İlkesi

1. **Doğruluk > Hız** — matematiksel kesinlik, her karar geri alınabilir
2. **Güvenlik > Özellik Hızı** — approval gates zorunlu, audit trail şart
3. **Gözlemlenebilirlik > Gizli Davranış** — her önemli aksiyon loglanır
4. **Modülerlik > Kısayol Hack'leri** — temiz interface'ler, bağımlılık enjeksiyonu
5. **Açık Politika > Örtülü Güven** — config-driven davranış
6. **Local-First** — bilgisayar kontrolü asla buluta gitmiyor
7. **Fail-Safe Tasarım** — varsayılan olarak reddet, approval non-optional

### Mimari Karar Kayıtları (ADR)

**ADR-001**: Elyan bir Operator Runtime'dır, chatbot değil
**ADR-002**: Üç katmanlı intent routing (Kural → Fuzzy → LLM)
**ADR-003**: Core sistemler singleton pattern
**ADR-004**: Operator aksiyonları için evidence zorunlu
**ADR-005**: Approval seviyeleri (AUTO, CONFIRM, SCREEN, TWO_FA)
**ADR-006**: Karmaşık projeler INTAKE→PLAN→EXECUTE→VERIFY→DELIVER
**ADR-007**: Bilgisayar görüşü tamamen local (Qwen2.5-VL via Ollama)
**ADR-008**: Inter-agent mesaj bus (AgentMessageBus singleton)
**ADR-009**: Agent task lifecycle (parent-child, deadline, status)
**ADR-010**: Paralel agent execution (CDG engine)
**ADR-011**: Otonom model seçimi (politika karar verir, agent değil)
**ADR-012**: Agent learning loop (OutcomeFeedback per task)
**ADR-013**: ElyanCore orchestrator wrapper
**ADR-014**: Bilgisayar kontrol katmanı hibrit yaklaşım
**ADR-015**: Ses mimarisi tamamen local pipeline
**ADR-016**: Decision Fabric — karar + bağlam birlikte saklanır
**ADR-017**: Pattern Engine — A fazı verisiyle Faza B eğitimi
**ADR-018**: Türkiye Connector Paketi — ConnectorBase abstract class

---

## BÖLÜM 4: 8 KATMANLI MİMARİ

| Katman | Bileşen | Kararlılık | Sahip |
|--------|---------|------------|-------|
| Session & Policy | SessionMgr, Vault, ApprovalLog, PolicyEngine, MemoryEngine | ⭐⭐⭐⭐⭐ | Core |
| Intent & Routing | IntentParser, LLM Orchestrator | ⭐⭐⭐⭐ | Intent |
| Execution & Agents | TaskEngine, ToolExec, ApprovalWorkflow | ⭐⭐⭐ | Exec |
| Turkey Connectors | e-Fatura, Logo, SGK, KEP | ⭐⭐⭐ | Turkey |
| Commercial | Billing, Credits, Entitlement, Iyzico | ⭐⭐⭐⭐ | Commerce |
| Decision Fabric | KararHafızası, AuditTrail | ⭐⭐⭐ | Memory |
| Pattern Engine | ActivityLog, PatternDetect, ProactiveEngine | ⭐⭐ | Ambient |
| UI / Command Center | Desktop App, Approvals, LiveRun | ⭐⭐⭐ | UI |

---

## BÖLÜM 5: EXECUTION MODEL

Her kullanıcı isteği için:

```
1. input al
2. schema validate et
3. normalize et
4. session çöz
5. workspace çöz
6. context topla
7. execution mode karar ver
8. plan çalıştır
9. gerekirse tool çağır
10. sonucu doğrula
11. memory güncelle
12. her önemli şeyi logla
13. durum ve sonuçla yanıtla
```

Validation, policy, doğrulama veya loglama atlama.

---

## BÖLÜM 6: SESSION MODEL

Her session:
- `session_id`
- `actor_id`
- `workspace_id`
- `lane_state`
- `active_run_id`
- `queued_events`
- `last_context_summary`

Queue politikaları: `followup`, `interrupt`, `merge`, `backlog`, `summarize`

---

## BÖLÜM 7: MEMORY MODEL

| Tip | İçerik | Örnek |
|-----|--------|-------|
| Profile | Kullanıcı tercihleri, davranış kuralları | "Onay olmadan dosya silme" |
| Project | Proje kararları, milestone'lar | "Iyzico Q3'de entegre edildi" |
| Episodic | Günlük özet, ne yapıldı | "Bugün e-Fatura connector tamamlandı" |
| Decision | Karar + bağlam + neden | "Tedarikçi X → fiyat artışı yüzünden kesildi" |
| Run Log | Tool çağrıları, ne değişti, rollback | Tool çağrı detayları |

---

## BÖLÜM 8: KALİTE KAPSISI

Bir değişikliği merge etmeden önce kontrol et:

- [ ] Session isolation bozuluyor mu?
- [ ] Policy bypass var mı?
- [ ] Log olmadan side effect oluyor mu?
- [ ] Dosya güvensiz mutate ediliyor mu?
- [ ] Memory daha az auditable oldu mu?
- [ ] Gereksiz coupling artıyor mu?
- [ ] Aksiyon doğrulanabiliyor mu?
- [ ] Failure kurtarılabiliyor mu?
- [ ] Türkiye connector'ı KVKK uyumlu mu?
- [ ] Test yazıldı mı?

---

## BÖLÜM 9: BİLİNEN SORUNLAR (Teknik Borç)

### KRİTİK — Production'ı Bloke Eden

**[C-1] Çift `run_store.py`**
- `/core/run_store.py` → async, dataclass, JSON persistence
- `/core/evidence/run_store.py` → sync, farklı constructor
- Fix: `/core/run_store.py` canonical, diğeri kaldırılmalı

**[C-4] Threading vs Async Lock Karışıklığı**
- `core/performance/cache_manager.py`: `asyncio.Lock()` ✓
- `core/performance_cache.py`: `threading.RLock()` → deadlock riski

### YÜKSEK — Release Öncesi

**[H-1] `core/agent.py` Monolith** — 14.766 satır
Dokunmadan çalıştır. Yavaş refactor planı hazırlanıyor.

**[H-2] Stub Modüller**
- `core/health_checks.py` — implement edilmemiş
- `core/realtime_actuator/` — tamamen stub

**[H-3] Üç Ayrı Real-Time Sistem**
- MetricsStore, Socket.IO, EventBroadcaster birleştirilmeli

### ORTA — Teknik Borç

**[M-1] Tutarsız Response Formatları**
- `dashboard_api.py`: `{"success": bool, "data": ...}`
- `http_server.py`: `(dict, int)` tuple
Birleşik ResponseContract gerekli.

**[M-2] Hardcoded Config**
Port `18789`, path `~/.elyan/runs`, timeout `600.0` her yere hardcoded.

---

## BÖLÜM 10: TEST DURUMU (2026-04-09)

- **Toplam**: ~2791 test
- **Geçen**: ~2718
- **Başarısız**: ~57 (pre-existing, dokunma)
- **Güvenlik testi**: 2 (yetersiz — SEC fazında artacak)

Başarısız test dağılımı:
- `test_agent_routing` (16) — agent.py monolith mock uyumsuzluğu
- `test_computer_use_*` (9+9err) — computer use stabil değil
- `test_llm_router` (4) — LLM mock timeout
- Diğer (10+) — dağınık pre-existing

**Kural**: Pre-existing başarısız testlere dokunma, yeni kod yazarken bunları bozmadan ilerle.

---

## BÖLÜM 11: FAZA A — CODEX İÇİN GÖREV SIRALAMA

### Şu An Yapılacak (P0)

1. **`elyan-service.ts:~1889` email bug**
   - `getCurrentLocalUser()` → email boşsa `null` döndür
   - Test: empty email gelince `isAuthenticated` false kalmalı

2. **`OnboardingScreen 2.tsx` sil**
   - `apps/desktop/src/screens/onboarding/OnboardingScreen 2.tsx`
   - Hiçbir yerde import edilmiyor, sadece sil

3. **Vite build test**
   - `cd apps/desktop && PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/vite build`
   - Hatasız geçmeli

4. **`.env.example` güncelle**
   - Ekle: `ELYAN_ADMIN_TOKEN=` ve `ELYAN_PORT=18789`

### Sonra (P1 — Güvenlik)
5. WebSocket token URL'den kaldır
6. `hmac.compare_digest` webhook imzası
7. Rate limiter auth endpoint'lerine bağla
8. Session token localStorage → HttpOnly cookie yönü planla

### Sonra (P2 — Türkiye Connector Başlangıcı)
9. `integrations/turkey/` dizini oluştur
10. `ConnectorBase` abstract class tanımla
11. e-Fatura connector iskeleti (test credentials, health check)
12. Decision Fabric: `core/decision_fabric.py` tasarla

---

## SONUÇ: Elyan Ciddi Bir Operatör Sistemi

Altyapı gibi inşa et, oyuncak gibi değil.

Her değişiklik Elyan'ı şuna yaklaştırmalı:
- Güvenilir execution
- Güvenli otonomi
- Modüler genişletilebilirlik
- Local-first güç
- Premium operator UX
- Auditable hafıza
- Türkiye'de gerçek iş çözen connector'lar
- Proaktif ambient zeka (Faza B)

Emin değilsen:
**Daha basit** → **Daha güvenli** → **Daha gözlemlenebilir** → **Daha kolay genişletilebilir**
