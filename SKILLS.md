# SKILLS.md — Session Tracking & İmplementasyon Playbook

**Amaç**: Bağlam kaybetmeden tam olarak devam edebilmek için.
**Son Güncelleme**: 2026-04-12
**Strateji**: Faza A (Türkiye KOBİ) → Faza B (Ambient/Proaktif Global)

---

## Session Protokolü

Her çalışmada:
1. **Bu dosyayı oku** — nereden kaldığını anla
2. **PROGRESS.md'yi oku** — aktif görev listesi
3. **AGENTS.md Bölüm 2'yi oku** — Codex kuralları (halüsinasyon önleyici)
4. **`git status` kontrol et** — beklenmedik değişiklik var mı?
5. **Öncelik sırasına göre çalış** (P0 → P1 → P2 → P3)
6. **Her görev bitince** bu dosyayı ve PROGRESS.md'yi güncelle
7. **Commit** → her P0 ayrı, P1/P2 gruplandırılabilir

---

## Faza A Durumu — Türkiye KOBİ Operatörü

### Tamamlanan ✓
- Workspace-first billing (Iyzico, Credits, plan kataloğu)
- Workspace RBAC + membership + seat enforcement
- Explicit owner bootstrap
- CSRF enforcement (gateway seviyesinde)
- Mobile intake (WhatsApp/Telegram/iMessage)
- Desktop shell (onboarding, home, billing, settings)
- Workspace intelligence loop
- Personal context engine (OS polling)

### Tamamlanan — P0
- [x] `getCurrentLocalUser()` boş email bug → `elyan-service.ts:~1889`
- [x] `OnboardingScreen 2.tsx` silindi / repo yüzeyinden temizlendi
- [x] Vite build doğrulandı
- [x] `.env.example` güncellendi

### Aktif — P1
- [x] Session token localStorage yedekle
- [x] Rate limiter auth endpoint'lerine bağla
- [ ] OnboardingScreen LLM kurulum adımı

### Sırada — P2 (Güvenlik)
- [ ] WebSocket token URL'den kaldır
- [ ] `hmac.compare_digest` webhook imzası
- [ ] Query string admin auth kaldır

### Sırada — P3 (Türkiye Connector Altyapısı)
- [ ] `integrations/turkey/` dizini + `ConnectorBase`
- [ ] e-Fatura connector iskeleti
- [ ] Decision Fabric (`core/decision_fabric.py`)
- [ ] Logo connector iskeleti
- [ ] SGK connector iskeleti

---

## Faza B Hazırlığı — Ambient Engine (Feature Flag Kapalı)

### Tasarım (Şimdi), Aktivasyon (12 ay sonra)
- [ ] `core/ambient/pattern_engine.py` iskeleti — veri topla, öğren
- [ ] `core/ambient/proactive_engine.py` iskeleti — öneri üret (kapalı)
- [ ] Activity log schema genişletme (pattern detection için)

---

## Geçmiş Session'lar

### Session 0-6: Phase 4-5 (Cognitive Architecture)
- CEO Planner ✓
- Deadlock Detector ✓
- Focused-Diffuse Modes ✓
- CLI Cognitive Commands ✓
- Dashboard Widgets ✓
- Dashboard API ✓
- Adaptive Tuning ✓

### Session 7: Computer Use Integration
- Vision Analyzer (Qwen2.5-VL) ✓
- Action Planner ✓
- Action Executor ✓
- Evidence Recorder ✓
- Approval Engine ✓
- 104 test, 100% passing ✓

### Session Mevcut (2026-04-09): Stratejik Yeniden Yapılanma
- Tüm .md dosyaları stratejiye göre güncellendi
- A+B strateji planı dokümante edildi
- Codex anti-hallucination kuralları eklendi
- Türkiye connector mimari planlandı
- Decision Fabric tasarlandı
- Pattern Engine iskeleti planlandı

---

## Codex Anti-Hallucination Checklist

Bir göreve başlamadan önce:

```
[ ] AGENTS.md Bölüm 2'yi okudum
[ ] Kullanacağım fonksiyon/sınıfın var olduğunu grep ile doğruladım
[ ] SQLAlchemy 2.0 text() zorunluluğunu hatırlıyorum
[ ] Routing guard sırasını değiştirmeyeceğim
[ ] _finalize_turn() → record_task_outcome() akışına dokunmayacağım
[ ] Test-first — önce test yazacağım
[ ] Stub bırakmayacağım
[ ] Var olan çalışan kodu "refactor" bahanesiyle kırmayacağım
[ ] Feature flag olmadan planner/router değiştirmeyeceğim
[ ] Silent catch kullanmayacağım
```

---

## Türkiye Connector Geliştirme Sıralaması

Önce temel kur, sonra özellik ekle:

```
1. integrations/turkey/base.py    — ConnectorBase abstract
2. integrations/turkey/tests/     — test dizini
3. e_fatura.py                    — GİB e-Fatura (en kritik)
4. e_arsiv.py                     — e-Arşiv
5. logo.py                        — Logo Go/Tiger
6. netsis.py                      — Netsis Wings
7. sgk.py                         — SGK bildirim
8. e_devlet.py                    — e-Devlet sorgulama
9. kep.py                         — KEP yönetimi
```

Her connector tamamlanma kriterleri:
- [ ] `health_check()` implement ve test edildi
- [ ] `test_credentials()` implement ve test edildi
- [ ] Gerçek/sandbox API test ortamı belgelendi
- [ ] KVKK: kişisel veri işleme consent logu var
- [ ] Hata mesajları Türkçe
- [ ] Retry logic mevcut
- [ ] Audit log'a düşüyor

---

## Kod Kalite Standartları

### Python
- Tüm fonksiyonlarda type annotation
- Her class/method için docstring (Türkçe veya İngilizce — tutarlı ol)
- Unit test: branch coverage ≥ 80%
- Integration test: happy path + error scenario

### TypeScript/React
- Zod ile schema validation
- `z.any()` kullanma — tip güvenliği şart
- `useEffect` dependency array eksiksiz
- Async effect cleanup (AbortController veya disposed flag)
- Silent `catch {}` yasak — en azından logla

### Genel
- Dev kodu production'a sızmasın (`console.log`, debug print, TODO yorum)
- Her yeni dosya için karşılık gelen test dosyası
- Kötü adlandırmadan kaçın: `data`, `result`, `temp`, `helper` → spesifik isim

---

## Session Sonrası Commit Örneği

```bash
# Sadece değiştirilen dosyalar — git add -A kullanma
git add apps/desktop/src/services/api/elyan-service.ts
git commit -m "$(cat <<'EOF'
fix: getCurrentLocalUser boş email ile signIn çağırmasın

Empty email geldiğinde null döndürerek isAuthenticated false kalıyor.
Onboarding akışında admin token varken sahte auth state oluşmasını önler.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Sonraki Session için Başlangıç Noktası

```
1. PROGRESS.md P0 listesine bak
2. Tamamlanmamış ilk maddeyi seç
3. AGENTS.md Bölüm 2'yi bir kez daha oku
4. Test yaz, implement et, test çalıştır, commit et
5. Bu dosyayı ve PROGRESS.md'yi güncelle
```
