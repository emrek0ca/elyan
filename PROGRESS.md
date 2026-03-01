# ELYAN PROGRESS PLAN

Bu dosya, Elyan projesinin mevcut durumunu, hedeflerini ve uygulanacak ilerleme planini tek yerde toplar.
Odak: yeni ozellik sisirmeden, var olan sistemi daha otonom, daha dogru ve daha guvenilir hale getirmek.

---

## 1) Mevcut Durum Ozeti

Elyan su an:
- CLI + Gateway + Dashboard + coklu kanal mimarisine sahip
- Tool-calling, planner, pipeline ve multi-agent altyapisini barindiriyor
- Bircok gorevde plan/execute yapabiliyor ancak bazi karmasik komutlarda tutarlilik sorunu var
- Kanal bazli davranis farklari (ozellikle onay/callback akislari) gorulebiliyor
- Bazi akislarda gereksiz artifact/manifest paylasimi olabiliyor

Guclu taraflar:
- Moduler cekirdek (agent/pipeline/router/planner)
- Runtime policy ve guvenlik katmanlari
- Tool ekosistemi ve evidence altyapisi
- Test altyapisi ve unit/integration kapsami

Iyilestirme gereken alanlar:
- Dil anlama -> TaskSpec donusum tutarliligi
- Deterministik executor + verify gate kapsami
- Kanal fallback ve callback guvenilirligi
- LLM ciktilarini daha iyi normalize etme
- Karmasik gorevlerde DAG/team mode istikrari

---

## 2) Ana Hedef (Tek Cumle)

Elyan'i "talimat veren chatbot" seviyesinden "dogru anlayan, guvenli sekilde uygulayan, kanitli teslim eden otonom gorev motoru" seviyesine cikarmak.

---

## 3) Strateji (Feature Freeze Uyumlu)

Kural:
- Yeni kanal/tool patlamasi yok
- Var olan kodu sertlestirme ve sadeleştirme var
- Her degisiklik kucuk, testli, geri alinabilir olacak

Yaklasim:
1. Anlama katmanini deterministic hale getir
2. Yurutmeyi schema + guardrail ile sabitle
3. Dogrulamayi zorunlu quality gate yap
4. Kanal farklarini capability matrix ile normalize et
5. Dashboard ve runtime policy'yi tek noktadan kontrol edilir hale getir

---

## 4) Teknik Yol Haritasi

## Faz A - Dil Anlama ve TaskSpec Sertlestirme
- Tum kritik intentlerde (fs/api/automation/ui) serbest plan yerine schema-valid TaskSpec uret
- Task extraction promptlarini domain-bazli ayir
- Belirsiz parametreler icin deterministic default policy uygula
- "Komutu dosyaya oldugu gibi yazma" anti-pattern kuralini global guard yap

Done kriteri:
- TaskSpec parse/validate basarisizlik orani < %2
- FS/API golden komutlarda yanlis aksiyon olmadan calisma

## Faz B - Deterministik Executor + Verify Gates
- Planner sadece ne yapilacagini uretsin; executor nasil yapilacagini yapsin
- Her step icin beklenen evidence tipi tanimli olsun
- Gate fail durumunda standard repair loop calissin:
  - PLAN_ERROR
  - TOOL_ERROR
  - ENV_ERROR
  - VALIDATION_ERROR

Done kriteri:
- "Yaptim" denmeden once stat/hash/contains/test dogrulamasi zorunlu
- Yanlis uzanti/yanlis path hatalari sistematik kapanmis olsun

## Faz C - Kanal ve Gateway Stabilizasyonu
- Tum kanallara tek capability matrix uygula
- Gonderimde fallback zinciri: rich -> plain -> short plain
- Callback id + user eslesmesi + stale request korumasi sertlestir
- Attachment ingest formatini tek standartta normalize et

Done kriteri:
- Onay/callback kayip orani < %0.5
- Kanal farkli olsa da ayni komutta ayni semantik sonuc

## Faz D - Multi-agent / Team Mode Olgunlastirma
- DAG scheduler ile bagimsiz adimlari otomatik paralel kos
- Role-based tool allowlist'i kesin uygula
- Team mesajlasmada clarification (blocking question) mekanizmasi
- Team sonuc envelope standardini her agent icin zorunlu kil

Done kriteri:
- Paralel calismada race-condition olmadan deterministik output
- Karmasik gorevlerde tamamlanma oraninda olculebilir artis

## Faz E - LLM Kalite ve Cikti Standardizasyonu
- Domain few-shot setlerini revize et
- Kod gorevlerinde: test + lint + typecheck done gate
- Arastirma gorevlerinde: kaynak + guven skoru + risk formati
- Cevap tonu runtime policy ile anlik kontrol edilir olsun (friendly/concise/formal)

Done kriteri:
- Yanlis intent ve "talimat metni donme" vakalari belirgin dusus
- Kod ve arastirma ciktilarinda profesyonel format standardi

## Faz F - Dashboard Sadelestirme ve Operasyon
- Daginik ayarlari policy merkezli gruplara indir
- "Son Kosular" panelinde run_id, hata kodu, evidence linki goster
- "Manifest gonder" toggle ve response mode kontrolu tek yerde olsun
- Failure replay butonu ile son basarisiz gorevi yeniden dene

Done kriteri:
- Dashboard'dan runtime davranisi tek noktadan yonetilebilir
- Debug suresi belirgin azalir

---

## 5) Otonomi Artirma Kontrol Listesi

Otonomi 1 (Temel):
- Komutu dogru parse et
- Tek adim tool call dogru yurut
- Basit verify yap

Otonomi 2 (Orta):
- Cok adimli plan cikart
- Her adim evidence topla
- Hata olursa auto-repair dene

Otonomi 3 (Ileri):
- DAG paralel yurutme
- Team mode rol dagitimi
- Farkli stratejilerle fallback ve yeniden planlama

Otonomi 4 (Profesyonel):
- Kanal bagimsiz tutarli davranis
- Guvenlik/policy tavizi olmadan tam icra
- Kanitli teslim + izlenebilir audit trail

---

## 6) Kalite KPI ve Kabul Kriterleri

Hedef KPI:
- Golden gorev basari orani >= %98
- Kritik yanlis aksiyon < %1
- TaskSpec validate fail < %2
- Callback/onay hatasi < %0.5
- CI pass rate %100 (bilincli ignore haric)

Kabul:
- Ayni komut farkli kanalda semantik olarak ayni sonucu vermeli
- Cikti metni "ne yapabilirsin" degil "ne yaptim" olmalı
- Gerekmedikce manifest/attachment spam olmamali

---

## 7) Test ve Dogrulama Paketi

Golden test komutlari:
1. Duvar kagidi akisi (gorsel -> set_wallpaper -> screenshot proof)
2. HTTP health + GET + result.json + summary.md
3. FS adimli gorev (mkdir + write + verify + artifact paths)
4. Ekran analizi (analyze_screen structured output)

Yuk test:
- 20 eszamanli fs/api gorevi ile DAG smoke

Kanal E2E:
- Callback
- Attachment ingest
- Rich/plain fallback

---

## 8) Haftalik Ilerleme Plani (8 Hafta)

Hafta 1:
- Baseline olcum + hata envanteri + KPI dashboard notu

Hafta 2:
- TaskSpec strict validation + extraction hardening

Hafta 3:
- Executor verify gate kapsami + repair state machine

Hafta 4:
- Gateway/channel callback + attachment stabilizasyonu

Hafta 5:
- LLM kalite tuning (prompt/few-shot/normalization)

Hafta 6:
- Multi-agent DAG/team mode determinism calismalari

Hafta 7:
- Dashboard sadeleştirme + observability iyilestirmesi

Hafta 8:
- Release hardening + dry-run + rollback prova

---

## 9) Calisma Kurallari

- Kucuk PR / kucuk degisiklik / net rollback
- Once failing test, sonra iyilestirme
- Her duzeltme icin kok neden notu
- Dokumantasyon kodla birlikte guncellenir

---

## 10) Bu Dosya Nasil Guncellenecek?

Her sprint sonunda su bolumleri guncelle:
- "Tamamlananlar"
- "Acil Riskler"
- "Sonraki Sprint Odagi"
- "KPI Durumu"

Alt kayit formati:
- Tarih
- Degisiklik ozeti
- Etkilenen dosyalar
- Test kaniti
- Kalan risk

---

## 11) Sonraki Somut Adimlar (Hemen)

1. TaskSpec parse/validate loglarini tek formatta toplamak
2. FS golden gorevini CI'da zorunlu gate yapmak
3. Callback stale/user-match korumasini harden etmek
4. Manifest spam'i runtime policy defaultlarinda kapatmak (sadece gerekliyse ac)
5. Dashboard'da "son kosular + hata kodu + evidence" panelini sade bir blokta toplamak

