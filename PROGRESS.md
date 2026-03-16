# ELYAN PROGRESS

Son guncelleme: 2026-03-15
Durum: aktif gelistirme, production-path odakli sertlestirme

Bu dosya repo icindeki diger markdownlarin yerine gecen tek merkezi kayittir.
Amac:
- mimariyi tek yerden anlatmak
- son donemde yapilan tum buyuk degisiklikleri toplamak
- bugun hangi noktada oldugumuzu netlestirmek
- kalan riskleri ve sonraki teknik yonu kaydetmek

## 1. Urun Tanimi

Elyan = coklu otonom sistem gorev orkestrasyon platformu.

Temel platform sinirlari:
- gorev planlama
- rota optimizasyonu
- goruntuden tespit
- araclar arasi gorev dagitimi
- operasyon paneli
- operator onayli / yari otonom / tam otonom modlar

Urun gelisim ilkesi:
- yeni yetenekler bu 6 omurgayi guclendiriyorsa eklenir
- bunun disindaki yan yetenekler ancak bu cekirdek orkestrasyonu destekliyorsa tutulur
- basit deterministic gorevler gereksiz team-mode veya multi-agent akislara itilmez

## 2. Repo Ozeti

Elyan, kullanici istegini niyet/parca/plana cevirip arac kullanan bir ana ajan uzerinden calisan, gerektiginde sub-agent ve team-mode ile parcali yurutme yapan otonom operator sistemidir.

Ana omurga:
- `core/agent.py`: ana karar ve teslim mantigi
- `core/pipeline.py`: validate -> route -> execute -> verify -> deliver akisi
- `core/sub_agent/*`: task packet, validator, team scheduler, isolated execution
- `tools/research_tools/*`: arastirma, claim contract, semantic retrieval, structured data
- `tools/pro_workflows.py`: belge, proje paketi, research delivery, revision delivery
- `tools/document_tools/*`: format renderer, word editor, output surfaces
- `core/gateway/*`: REST/websocket/dashboard son kullanici yuzeyi

## 3. Markdown Konsolidasyon Notu

Bu repo taranarak markdown envanteri cikarildi.

Tespit edilen sayilar:
- toplam `.md` dosyasi: 2038
- `.elyan` altindaki run/report artifact markdownlari: 1740
- `artifacts/` altindaki benchmark/stability/task markdownlari: 150
- projeye ait kalan markdownlar: 109
- `venv/.venv/site-packages` altindaki vendor/lisans markdownlari bu konsolidasyonun disinda tutuldu

Bu dosya, asagidaki eski kaynaklarin ozetini de icerir:
- yol haritasi / roadmap
- teknik genel mimari notlari
- onboarding, deployment, dashboard, security, cli ve channel docs
- orchestration refactor notlari
- onceki `PROGRESS.md`

## 4. Mimari Durum

Mevcut ana akis:
`user input -> normalize -> intent/capability route -> plan -> tool execution -> verification -> delivery -> telemetry`

Aktif buyuk yetenekler:
- deterministic + LLM destekli intent/capability routing
- file/system/browser/screen/operator tool execution
- research + evidence + claim contract akisi
- document generation + revision safety
- multi-agent / team-mode / workflow-profile destekli coding akisi
- dashboard / health / recent-runs / evidence gorunurlugu

## 5. Son Donemde Tamamlanan Buyuk Gelistirmeler

### 4.1 Arastirma Dogrulugu ve Evidence Katmani

Tamamlananlar:
- `advanced_research` ciktisina zorunlu `research_contract` eklendi
- `claim_list`, `citation_map`, `critical_claim_ids`, `uncertainty_log`, `conflicts` zorunlu kalite sinyali haline geldi
- `quality_summary` artik final metin heuristiginden degil contract verisinden turetiliyor
- kritik claim coverage ve uncertainty sayilari run summary/dashboard yuzeyine tasindi
- `claim_map.json` ve `revision_summary.md` artifact haline getirildi

Kazanclar:
- "tamamlandi" yerine "partial/manual review" sinyali daha dogru uretildi
- kaynaksiz veya tek kaynaga dayanan kritik claimler dogrudan kaliteye yansiyor
- belge ile kanit matrisi arasinda izlenebilir bag kuruldu

### 4.2 Research Delivery ve Belge Revizyon Guvenligi

Tamamlananlar:
- `research_document_delivery` claim bagli section modeli uzerinden calisiyor
- section-level word revizyonu eklendi:
  - `rewrite_section`
  - `replace_section`
  - `append_risk_note`
  - `generate_revision_summary`
- follow-up revizyonlar onceki `claim_map.json` ile bagli calisiyor
- `yalnizca ozeti guncelle`, `daha kisa yap`, `kurumsal yap`, `pdf yap` gibi istekler revision hattina alinabildi

Kazanclar:
- tum belgeyi serbest yeniden yazma yerine hedefli revizyon
- claim/source baglarini koruyan daha guvenli duzenleme
- revizyon sonrasi neyin degistigi gorulebilir hale geldi

### 4.3 Belge Ciktisinin Profesyonellesmesi

Tamamlananlar:
- varsayilan research delivery content-only moda cekildi
- belge govdesinden sistem basliklari, claim dump, kaynak guven satirlari temizlendi
- varsayilan `citation_mode=none` olacak sekilde sadeleştirildi
- Word/PDF/MD/HTML ayni section modelinden uretilir hale geldi
- basliklar sade konu metnine cekildi; gereksiz "Arastirma Raporu -" prefiksi kaldirildi

Kazanclar:
- kullaniciya giden belge icerik odakli oldu
- kanit detayi arka planda artifact olarak kaldi
- formatlar arasi icerik tutarliligi arttı

### 4.4 Smart Fetch, Structured Data ve Semantic Retrieval

Tamamlananlar:
- statik fetch + render fallback mantigi eklendi
- JS agirlikli kaynaklar icin Playwright fallback yolu kuruldu
- semantic retrieval katmani eklendi; model yoksa lexical fallback mevcut
- structured data / time-series yoluyla ekonomi benzeri konularda daha deterministik veri ozeti uretilebiliyor
- `ResearchOrchestrator` ile planner/web/data/retrieval/critic ayrimi baslatildi

Kazanclar:
- resmi kurum ve zor sayfa yapilarinda daha yuksek veri erisimi
- passage secim kalitesinde iyilesme
- arastirma kodunda gorevlerin ayrisabilir hale gelmesi

### 4.5 Main-Agent / Sub-Agent / Team-Mode Sertlestirmesi

Tamamlananlar:
- research kalite gate'leri sub-agent validator'a indirildi
- `superpowers_lite` ve `superpowers_strict` workflow profilleri eklendi
- design -> approval -> plan -> workspace -> task packets -> review -> finish branch akisi tanimlandi
- `design`, `implementation_plan`, `workspace_report`, `review_report`, `finish_branch_report` artifact zinciri kuruldu
- NEXUS / agency-agents esintili specialist hint, handoff ve review telemetry eklendi

Kazanclar:
- coding odakli gorevlerde daha zorunlu ve izlenebilir process
- main-agent contract owner, sub-agent execution worker rolune yaklasti
- team-mode sonuclari dashboard ve run summary yuzeyine tasindi

### 4.6 Dashboard, Recent Runs ve Operator Gorunurlugu

Tamamlananlar:
- recent runs API ve dashboard alanlari genisletildi
- gorunur metrikler eklendi:
  - claim coverage
  - critical claim coverage
  - uncertainty count
  - conflict count
  - manual review claim count
  - workflow profile / phase / approval / review / workspace mode

Kazanclar:
- operator artik neden `partial` oldugunu gorebiliyor
- research ve coding workflow'leri ayni telemetry omurgasina yaziyor

### 4.7 Screen / Vision Dayanikliligi

Tamamlananlar:
- `"High"`, `"Medium"`, `%85`, `0.85` gibi confidence degerlerini parse edememe sorunu kapatildi
- screen operator zincirindeki float-cast cokmeleri giderildi
- gateway suggestion katmani da ayni normalizasyona getirildi

Kazanclar:
- ekran okuma akisi daha az kirilgan hale geldi
- text label confidence degerleri runtime'i dusurmuyor

### 4.8 Cleanup Sprint Sertlestirmesi

Tamamlananlar:
- `.elyan` altindaki `runs`, `reports`, `jobs` agaclari icin retention/cleanup motoru eklendi
- run store baslangicinda throttled artifact pruning devreye alindi
- proactive maintenance artik artifact cleanup da yapiyor
- repo ici markdown politikasi eklendi; `PROGRESS.md` disinda yeni proje markdowni pre-commit tarafinda bloklanir
- legacy `revision_summary`, workflow report ve dashboard artifact'lari `.txt` tarafina cekildi
- `pyproject.toml` icindeki silinmis `README.md` referansi `PROGRESS.md` olarak duzeltildi

Kazanclar:
- `.elyan` icindeki artifact birikimi daha kontrollu hale geldi
- yeni markdown yayilimi repo seviyesinde engelleniyor
- packaging/build metadata kirikligi kapatildi

### 4.9 Micro-Orchestration ve Karar Yolu Gorunurlugu

Tamamlananlar:
- basit browser/app gorevleri icin `micro_orchestration` execution route eklendi
- simple deterministic gorevler team-mode veya multi-agent fallback'ina gereksizce itilmemeye baslandi
- execution trace metadata alani eklendi:
  - `execution_route`
  - `autonomy_mode`
  - `autonomy_policy`
  - `orchestration_decision_path`
- sub-agent packet planlamasina ownership ve wave ozetleri eklendi:
  - `parallel_waves`
  - `max_wave_size`
  - `parallelizable_packets`
  - `serial_packets`
  - `ownership_conflicts`
- dashboard recent-runs yuzeyi route/autonomy/decision/team-wave sinyallerini gosterecek sekilde genisletildi

Kazanclar:
- Elyan ana urun tanimina daha yakin bir gorev orkestrasyon davranisi sergiliyor
- main-agent kontrat sahibi, sub-agent scoped executor ayrimi daha net hale geliyor
- operator paneli artik yalniz sonucu degil karar yolunu da gosterebiliyor

## 5. Bugun Itibariyla Bilinen Teknik Borclar

Hala dikkat isteyen alanlar:
- markdown bagimliliklari kod tabaninda hala fazla ve daginik
- bazi artifact isimleri sabit string olarak tekrarlaniyor
- sub-agent task packet scheduling bazı durumlarda gereksiz seri kaliyor
- confidence/score parsing mantigi birkac farkli yerde tekrarlaniyor
- research/document/handover yollarinda eski artifact isimlerine bagli legacy dallar var

## 6. Bu Turdaki Konsolidasyon ve Sertlestirme Hedefi

Bu turun hedefi:
- markdown dokumantasyonu tek dosyada toplamak
- proje markdownlarini temizlemek
- kodu eksik markdown durumuna daha dayanikli hale getirmek
- performans ve guvenlik icin tekrar eden mantigi azaltmak
- multi-task ile main-agent/sub-agent koordinasyonunu iyilestirmek

## 7. Operasyonel Ilkeler

Kalici kararlar:
- evidence over claims
- content-only user delivery, evidence-artifact arkada
- contract-first validation
- explicit approval before mutating coding workflows
- scope-guarded sub-agent execution
- quality gate gecmeden "done" denmez

## 8. Sonraki Teknik Odak

Yuksek oncelikli:
- ortak confidence/coercion util'i ile tekrar azaltma
- task packet target-file sanitization ve scope sertlestirmesi
- disjoint task packet'leri paralel kosturacak team scheduler iyilestirmesi
- markdown yoklugunda graceful fallback davranislari
- path handling ve artifact persistence sertlestirmesi

Orta oncelikli:
- artifact adlandirmalarinin merkezi hale getirilmesi
- legacy `.md` bekleyen akislarda `.txt`/fallback destegi
- verifier/report surfaces icin daha ortak formatter

## 9. Kisa Sonuc

Elyan artik sadece "arac kullanan ajan" degil:
- claim-contract tabanli research engine
- content-only document delivery system
- process-enforced coding workflow engine
- team-mode ve specialist handoff destekli multi-agent orchestrator
- dashboard/evidence odakli operator platformu

Bu dosya, repo icinde kalan tek merkezi markdown kaynagi olarak tutulacaktir.
