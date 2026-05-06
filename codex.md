# Elyan Codex Operating System

Bu dosya, Elyan üzerinde çalışan AI coding agent’ların (Codex, Claude, Gemini vb.) nasıl davranacağını belirleyen ana yönetim katmanıdır.

Bu bir README değildir.  
Bu bir "instruction kernel" ve "agent governance system"dir.

Bu dosya yok sayılırsa sistem bozulur.

---

# 0. TEMEL TANIM

Elyan:

Local-first çalışan, kullanıcı verisini cihaz dışına çıkarmayan, çoklu LLM destekli, gerçek aksiyon alabilen (tools / MCP / computer-use), kaynak okuyup doğrulayabilen ve karar üretebilen bir agent sistemidir.

Bu proje:

- chatbot değildir
- demo değildir
- script collection değildir

Bu:

**decision + execution agent system**

---

# 1. ANA PRENSİPLER

Her karar bu kurallara göre verilir:

- Local-first bozulmaz
- Privacy-first bozulmaz
- Minimalizm korunur
- Mevcut çalışan sistem kırılmaz
- Gereksiz abstraction yapılmaz
- Gereksiz refactor yapılmaz
- Büyük rewrite yapılmaz
- Kod sade kalır
- Tek işi yapan tek doğru implementasyon olur

---

# 2. PROJE GERÇEKLİĞİ (SOURCE OF TRUTH)

Elyan iki ana parçadan oluşur:

1. Elyan Runtime (local agent)
2. elyan.dev (web / control plane / dağıtım yüzeyi)

Bu iki sistem:

- aynı repo içinde olabilir
- aynı şey değildir
- birbirine bağımlı ama ayrıdır

Karıştırma.

---

# 3. AGENT MİMARİSİ

Elyan şu pipeline ile çalışır:

User Input
→ Intent Detection
→ Instruction Kernel (BU DOSYA)
→ Planner
→ Execution Strategy
→ Tool / Skill / MCP / CLI / Computer Use
→ Observation
→ Correction
→ Final Answer

---

# 4. INSTRUCTION KERNEL (EN KRİTİK KATMAN)

Bu dosya, agent davranışını sınırlar.

Agent:

- serbest davranamaz
- kendi mimarisini değiştiremez
- core yapıyı yeniden yazamaz

Bu dosya:

- CTO
- Architect
- Product owner

gibi davranır.

---

# 5. EXECUTION STRATEGY (DEĞİŞTİRME)

Bir task geldiğinde şu sıra uygulanır:

1. API varsa → API kullan
2. CLI varsa → CLI kullan
3. Skill varsa → skill kullan
4. MCP varsa → MCP kullan
5. hiçbiri yoksa → computer-use kullan

Computer-use:

- fallback’tir
- primary değildir

---

# 6. OPTIMIZATION & QUANTUM LOGIC

Elyan bir chatbot değildir.

Elyan:

→ problem çözer

Şu tip istekleri tanır:

- "en iyi dağıtım"
- "minimum maliyet"
- "optimize et"
- "en verimli plan"
- "rota hesapla"

Bu durumda şu flow çalışır:

Problem
→ Mathematical Model
→ Constraints
→ Objective
→ QUBO / Representation
→ Solver Selection
→ Solve
→ Compare
→ Explain

Quantum burada:

- hardware değildir
- yaklaşım/modelleme tekniğidir

---

# 7. SKILL SİSTEMİ

Her skill:

- izole
- typed
- deterministic
- test edilebilir

olmalı.

Skill:

- business logic içerir
- agent logic içermez

---

# 8. MCP (MODEL CONTEXT PROTOCOL)

MCP:

- external tool boundary’dir
- opsiyoneldir
- env ile açılır/kapanır

MCP hiçbir zaman:

- core’un yerine geçmez
- local veriyi zorunlu dışarı çıkarmaz

---

# 9. COMPUTER USE

Computer use:

- GUI automation’dır
- son çaredir
- fragile’dır

Agent önce her zaman:

API → CLI → Skill → MCP

dener.

---

# 10. CODE DEĞİŞİKLİĞİ KURALLARI

Kod yazarken:

- minimum değişiklik yap
- mevcut dosya yapısını bozma
- aynı işi yapan ikinci sistem ekleme
- ölü kod bırakma
- gereksiz abstraction yapma
- style bozmadan yaz

---

# 11. DOSYA VE MODÜL STRATEJİSİ

Her modül:

- tek sorumluluk taşımalı
- 300-500 LOC üstüne çıkmamalı
- büyürse bölünmeli

Yeni feature:

- yeni klasör
- izole modül

---

# 12. CLI / DESKTOP / WEB AYRIMI

CLI:
- kurulum
- setup
- debug
- automation

Desktop:
- kullanıcı deneyimi
- agent kontrolü

Web (elyan.dev):
- dağıtım
- hesap
- marketing
- control plane

Bunları karıştırma.

---

# 13. TEST VE BUILD

Kod yazıldıktan sonra:

- build kırılmamalı
- typecheck geçmeli
- CLI çalışmalı
- env eksikse düzgün hata vermeli

---

# 14. YAPILMAYACAKLAR

- proje yeniden yazılmayacak
- core agent değiştirilmeyecek
- framework değiştirilmeyecek
- fake implementation yapılmayacak
- placeholder bırakılmayacak
- gereksiz dependency eklenmeyecek

---

# 15. NASIL ÇALIŞMALISIN

Önce:

- repo’yu oku
- yapıyı anla
- çakışmaları bul
- plan çıkar

Sonra:

- küçük değişiklikler yap
- test et
- ilerle

Direkt kod yazma.

---

# 16. HEDEF

Bu repo:

- production’a hazır olmalı
- anlaşılır olmalı
- sade olmalı
- güçlü olmalı

---

# 17. GERÇEK AMAÇ

Elyan:

→ local çalışan  
→ düşünen  
→ karar veren  
→ aksiyon alan  

bir sistemdir.

---

# 18. SON KURAL

Eğer bir karar:

- sistemi karmaşıklaştırıyorsa → yanlış
- mevcut yapıyı bozuyorsa → yanlış
- gereksizse → yanlış

Doğru çözüm:

→ en basit çalışan çözümdür