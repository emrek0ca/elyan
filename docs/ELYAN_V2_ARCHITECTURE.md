# Elyan v2 Architecture & Vision

Bu doküman, Elyan'ın "kişisel dijital operatör"den çok cihazlı, çok kanal destekli, görev yöneten, state tutan, tool kullanan ve gerektiğinde insan onayı isteyen bir "operasyon düzlemi"ne dönüşümünü tanımlar.

## 7 Katmanlı Mimari

1. **Gateway Core:** Sürekli açık kalacak merkez servis. Telegram, web, mobil, desktop, CLI tüm girişler event olarak buraya düşer. State dağıtık değil, merkezde yönetilir.
2. **Protocol Layer:** Tüm trafik typed (Zod/JSON Schema). Event sözleşmeleri: `MessageReceived`, `SessionResolved`, `RunQueued`, vb. Kanal adapter'ları sadece event üretir/tüketir, core bozulmaz.
3. **Session Engine:** Her kullanıcı/sohbet/proje bir session kimliği ile temsil edilir. Her session'ın kendi lane'i vardır. Aynı session içinde iki run aynı anda çalışmaz (per-session serialization). Tool yarışları ve hafıza bozulmaları engellenir.
4. **Context & Memory Engine:** Hibrit memory. Kaynak gerçek dosya/JSON/Markdown, arama için index katmanı. Audit edilebilir ve hızlı retrieval sağlar.
5. **Tool Runtime:** Tool (çalıştırılabilir fonksiyon), Skill (davranış şablonu) ve Plugin (paket) ayrımları nettir. Sistem büyürken çamura dönüşmesi engellenir.
6. **Node Fabric:** Bulut, masaüstü, mobil, VPS node'ları. Her node capability'lerini (terminal, browser vs.) ilan eder. Gateway işi en uygun node'a verir.
7. **UX / Command Center:** Aktif session'lar, çalışan görevler, bekleyen onaylar, memory yazımları, node sağlık durumu gibi metriklerin izlendiği premium kullanıcı paneli.

## Temel Mimari Kuralları
- Core değişmez, özellikler eklenti olur.
- State event tabanlı tutulur.
- Her session tek lane’den akar.
- Yan etkiler yalnızca tool runtime içinde olur.
- Memory write-back kontrollü yapılır.
- Her yeni capability önce shadow mode’da test edilir.
- Her feature flag ile açılıp kapanır.
- Her run yeniden oynatılabilir transcript üretir.

## Çekirdek Algoritmalar

### Giriş Algoritması
Kanal fark etmeksizin standartlaştırma:
```
receive(event) -> validate_schema -> normalize -> resolve_actor -> resolve_workspace -> resolve_session -> resolve_agent -> enqueue(session_lane, event) -> trigger_scheduler(session_lane)
```

### Session Lane Algoritması
```python
if lane.locked:
    apply_queue_policy(event)
else:
    lock(lane)
    start_run()
```
Queue policy seçenekleri: `collect`, `followup`, `interrupt`, `steer`, `backlog-summarize`.

### Context Assembly Algoritması
Sabit prompt yerine lifecycle bazlı (ingest, assemble, compact, after-turn):
```python
context = {system_rules, user_profile, workspace_state, recent_transcript, pinned_memory, project_memory, retrieved_docs, tool_state, current_goal, execution_constraints}
budget = token_budget(model)
ordered = prioritize(context)
trimmed = compact_to_budget(ordered, budget)
```

### Planlama ve Yürütme Algoritması
```python
plan = planner(context)
for step in plan:
    if step.type == "tool":
        result = execute_tool(step)
        append_transcript(result)
        update_context(result)
    elif step.type == "message_block":
        stream_block(step)
    elif step.type == "approval":
        pause_run_and_wait_human()
    elif step.type == "delegate":
        dispatch_subagent(step)
```

### Tool Execution Algoritması
Üç güvenlik kapısı: yetki, risk seviyesi, çıktı doğrulama.
```python
check_capability(tool, node)
check_permission(user, workspace, tool)
check_budget(cost, latency, risk)
execute(tool)
validate_output(schema)
write_tool_result()
```

### Memory Write-Back Algoritması
4 seviye: working (scratchpad), episodic (günlük özet), profile (tercihler), project (kalıcı bilgi).
```python
extract_candidates(run_output)
score(candidate, usefulness, persistence, sensitivity)
if score > threshold:
    write_to_memory_store(candidate)
    index(candidate)
```
Örnek yapı: `memory/profile.md`, `memory/projects/<project>/MEMORY.md`, `memory/daily/YYYY-MM-DD.md`, `memory/runs/<session>/<run>.json`.

### Deterministic Routing Algoritması
Mesaj yönlendirmesi model kararına bırakılmaz. Öncelik sırası:
1. explicit session binding
2. explicit workspace binding
3. active task owner
4. project specialist match
5. channel default agent
6. fallback general operator

## Büyüme Roadmap'i
1. **Faz 1: Çekirdek Omurga (2 hafta):** Gateway daemon, typed WS API, session store, transcript log, lane lock.
2. **Faz 2: Context ve Memory (2 hafta):** Hybrid memory, project workspace, retrieval pipeline.
3. **Faz 3: Tool Runtime ve Plugin Sistemi (2 hafta):** Tool/skill registry, capability negotiation, safe runner.
4. **Faz 4: Node Sistemi ve Çok Cihazlı Çalışma (2 hafta):** Desktop/VPS/mobile node'lar, remote execution.
5. **Faz 5: Otonomi ve Onay Sistemi (2 hafta):** Planner-executor-validator ayrımı, approval gates.
6. **Faz 6: Premium UX ve Ticarileştirme (2 hafta):** Command center, cost dashboard, client workspace.

## Elyan'ın OpenClaw'dan 5 Büyük Farkı
1. Daha iyi UX
2. Gerçek hybrid memory
3. Cost-aware model router
4. Approval-first autonomy
5. Node orchestration + consumer-grade polish
