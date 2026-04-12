# Elyan — Mimari Döküman (v2)

**Son Güncelleme**: 2026-04-09
**Strateji**: A+B — Türkiye KOBİ Operatörü → Ambient/Proaktif Global Ajan

---

## Genel Bakış

Elyan kişisel dijital operatörden çok cihazlı, çok kanal destekli, görev yöneten, state tutan, tool kullanan ve gerektiğinde insan onayı isteyen bir "operasyon düzlemi"ne evrilmektedir.

**Kritik ayrım**: Elyan reaktif bir asistan değil, proaktif bir operatördür.
- ChatGPT/Claude: Konuşur, tavsiye verir.
- Elyan: Onay alır, gerçek dünyada iş yapar.

---

## 9 Katmanlı Mimari

### Katman 1: Gateway Core
Sürekli açık kalacak merkez servis. Tüm kanallar (Telegram, web, mobil, desktop, CLI) event olarak buraya düşer.

```
[Telegram] ──┐
[WhatsApp] ──┤
[Desktop]  ──┼──→ Gateway Core → Session Engine → Execution
[Web]      ──┤
[CLI]      ──┘
```

### Katman 2: Protocol Layer
Tüm trafik typed (Zod/JSON Schema). Kanal adapter'ları sadece event üretir/tüketir.

Temel event sözleşmeleri:
- `MessageReceived`, `SessionResolved`, `WorkspaceResolved`
- `RunQueued`, `RunStarted`, `PlanCreated`
- `ToolRequested`, `ToolApproved`, `ToolRejected`, `ToolStarted`, `ToolSucceeded`, `ToolFailed`
- `VerificationPassed`, `VerificationFailed`
- `MemoryWriteRequested`, `MemoryWritten`
- `RunCompleted`, `RunFailed`, `RunCancelled`

### Katman 3: Session Engine
Her kullanıcı/sohbet/proje bir session ile temsil edilir. Per-session serialization — aynı session içinde iki run aynı anda çalışmaz.

Queue politikaları: `followup`, `interrupt`, `merge`, `backlog`, `summarize`

### Katman 4: Context & Memory Engine
Hibrit memory. Kaynak gerçek dosya/JSON/Markdown, arama için index katmanı.

```
Memory Tipleri:
├── Profile Memory   — tercihler, kurallar
├── Project Memory   — kararlar, milestone'lar
├── Episodic Memory  — günlük özet, ne yapıldı
├── Decision Fabric  — karar + bağlam + neden (YENİ)
└── Run Logs         — tool çağrıları, audit trail
```

### Katman 5: Tool Runtime + Türkiye Connectors
Tool (çalıştırılabilir), Skill (davranış şablonu), Plugin (paket) ayrımı nettir.

**Türkiye Connector Paketi** (Faza A — YENİ):
```
integrations/turkey/
├── base.py           — ConnectorBase abstract
├── e_fatura.py       — GİB e-Fatura entegrasyonu
├── e_arsiv.py        — e-Arşiv
├── logo.py           — Logo muhasebe
├── netsis.py         — Netsis
├── sgk.py            — SGK bildirim
├── e_devlet.py       — e-Devlet
└── kep.py            — KEP yönetimi
```

Her connector üç yüzey sağlar:
1. `health_check()` — bağlantı durumu
2. `test_credentials()` — kimlik doğrulama
3. İş mantığı metodları (send_invoice, query_debt, vb.)

### Katman 6: Commercial Plane
- Elyan Credits bazlı ödeme (ham provider token satılmaz)
- Planlar: free, pro, team, enterprise
- Truth zinciri: `billing_events → entitlement_snapshots → credit_ledger`
- Iyzico provider abstraction

### Katman 7: Decision Fabric (YENİ)
Sadece ne yaptığını değil neden yaptığını kaydeden hafıza katmanı.

```python
@dataclass
class Decision:
    id: str
    summary: str           # "Tedarikçi X sözleşme yenilenmedi"
    context: str           # "Q3 fiyat artışı + 3 kargo gecikmesi"
    actor_id: str
    workspace_id: str
    timestamp: str
    related_event_ids: list[str]
    tags: list[str]
```

Kullanım: "Neden bu tedarikçiyle çalışmıyoruz?" → Elyan 6 ay önceki kararı ve gerekçesini söyler.

### Katman 8: Ambient Engine (Faza B — Feature Flag Kapalı)
Pattern detection ve proaktif öneri sistemi.

```
ActivityLog (A fazında birikir)
      ↓
PatternEngine (tekrar eden işleri tespit eder)
      ↓
ProactiveEngine (öneriler üretir)
      ↓
NotificationGate (güven skoru < 0.8 → sessiz kal)
      ↓
Kullanıcıya bildirim (max 3/gün)
```

**Kritik kural**: Düşük güven öneri gösterilmez. Yanlış öneri kullanıcıyı rahatsız eder, güven yıkılır.

### Katman 9: Node Fabric
Bulut, masaüstü, mobil, VPS node'ları. Her node capability'lerini ilan eder. Gateway işi en uygun node'a verir.

---

## Temel Algoritmalar

### Giriş Algoritması
```
receive(event)
→ validate_schema
→ normalize
→ resolve_actor
→ resolve_workspace
→ resolve_session
→ enqueue(session_lane, event)
→ trigger_scheduler(session_lane)
```

### Session Lane Algoritması
```python
if lane.locked:
    apply_queue_policy(event)
    # collect | followup | interrupt | steer | backlog-summarize
else:
    lock(lane)
    start_run()
```

### Context Assembly
```python
context = {
    system_rules,
    user_profile,
    workspace_state,
    recent_transcript,
    pinned_memory,
    project_memory,
    decision_fabric_recent,  # YENİ — son kararlar
    retrieved_docs,
    tool_state,
    current_goal,
    execution_constraints,
}
budget = token_budget(model)
ordered = prioritize(context)
trimmed = compact_to_budget(ordered, budget)
```

### Tool Execution — 3 Güvenlik Kapısı
```python
check_capability(tool, node)      # 1: Node bu tool'u destekliyor mu?
check_permission(user, workspace, tool)  # 2: Kullanıcı yetkili mi?
check_budget(cost, latency, risk) # 3: Credit/latency/risk uygun mu?
execute(tool)
validate_output(schema)
write_tool_result()
audit_log(action, result)         # Her zaman
```

### Memory Write-Back
```python
extract_candidates(run_output)
for candidate in candidates:
    score = score(candidate,
        usefulness=...,
        persistence=...,
        sensitivity=...
    )
    if score > threshold:
        write_to_memory_store(candidate)
        index(candidate)
```

### Pattern Detection (Faza B)
```python
# Günlük çalışır, feature flag kapalıyken sadece biriktirir
activity_events = load_activity_log(window_days=30)
patterns = detect_recurring_sequences(activity_events)
for pattern in patterns:
    if pattern.confidence > 0.8 and pattern.frequency > 5:
        proposal = generate_automation_proposal(pattern)
        queue_for_user_review(proposal)
```

---

## Kritik Mimari Kurallar

1. **Core değişmez** — özellikler eklenti olur, core bozulmaz
2. **State event tabanlı** — her önemli transition event üretir
3. **Her session tek lane** — paralel execution explicit olmadan yasak
4. **Yan etkiler sadece tool runtime içinde** — UI, session engine, context engine yan etki üretemez
5. **Memory write-back kontrollü** — scoring olmadan yazma
6. **Shadow mode zorunlu** — yeni capability önce shadow mode'da test
7. **Feature flag ile aç/kapat** — her yeni davranış flag arkasında
8. **Replay edilebilir** — her run yeniden oynatılabilir transcript üretir
9. **KVKK uyumlu** — kişisel veri işlenmeden önce consent kaydı
10. **Local-first** — bilgisayar kontrolü asla buluta gitmiyor

---

## Güvenlik Mimarisi

### Auth Katmanı
- Session token: `X-Elyan-Session-Token` header veya `elyan_user_session` cookie
- Admin token: sadece loopback (`_is_loopback_request()` true ise)
- CSRF: `elyan_csrf_token` cookie + `X-Elyan-CSRF` header
- Rate limiting: `_AUTH_FAILURE_ATTEMPTS` dict (bağlanması bekliyor)

### Güvenlik Boşlukları (Düzeltme Sıralaması)
| Sorun | Seviye | Durum |
|-------|--------|-------|
| WebSocket token URL'de | KRİTİK | P2'de düzeltiliyor |
| Webhook timing attack | KRİTİK | P2'de düzeltiliyor |
| Query string admin auth | YÜKSEK | P2'de kaldırılıyor |
| Rate limiter bağlanmamış | ORTA | P1'de tamamlanıyor |
| localStorage session token | ORTA | P1'de planlanıyor |
| Dosya yükleme MIME kontrolü | YÜKSEK | P2'de ekleniyor |

---

## Türkiye Lokalizasyonu

### Neden Önemli
Yabancı şirketler bu derinliğe asla inmeyecek:
- GİB API protokolleri
- Türk muhasebe yazılımı entegrasyonları (Logo, Netsis, Luca)
- KVKK uyumluluk gereksinimleri
- Türk iş kültürü ve yazışma tarzı
- TRY bazlı para yönetimi

### Implementasyon Kuralları
- Tüm Türkiye connector'ları `integrations/turkey/` altında
- Her connector `ConnectorBase`'den türetilmeli
- Test/production ortam URL'leri ayrı config'de
- Hata mesajları Türkçe
- Tarih formatı DD.MM.YYYY
- Her API çağrısı audit log'a düşmeli

---

## Büyüme Sıralaması

```
Şu An (Faza A):
├── P0: Kritik bug'lar düzelt
├── P1: UX iyileştirmeleri
├── P2: Güvenlik güçlendirme
└── P3: Türkiye connector altyapısı

6-12 Ay (Faza A devam):
├── e-Fatura, Logo, Netsis connector'ları
├── Decision Fabric (karar hafızası)
├── KOBİ pilot müşteriler
└── Admin control plane

12-24 Ay (Faza B):
├── Pattern Engine aktifleştirme
├── Proaktif bildirim sistemi
├── Ambient Context Engine
└── Global çıkış hazırlığı
```

---

## Elyan'ın Rakiplerden Farkı

| Özellik | Rakipler | Elyan |
|---------|----------|-------|
| Çalışma yeri | Bulut (cloud) | Local-first |
| Bağlam | Sadece yazdıkların | OS, dosyalar, uygulama durumu |
| Hafıza | Konuşma süresi | Kalıcı, workspace + karar bağlamı |
| Yan etkiler | Sıfır | Gerçek dünya (dosya, API, terminal) |
| Türkiye derinliği | Yüzeysel | e-Fatura, Logo, SGK, KEP |
| Proaktivite | Reaktif | Proaktif (Faza B) |
| Veri gizliliği | Buluta gider | KVKK uyumlu, yerinde kalır |
| Ticaret | USD/EURO | Iyzico + Elyan Credits |
