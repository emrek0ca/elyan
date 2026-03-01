# ELYAN AGENT GUIDE

Bu dosya, Elyan projesinde calisan gelistiriciler ve agentlar icin hizli rehberdir.

## 1) Proje Ne Hakkinda?

Elyan, Turkce/Ingilterice komutlari anlayip eyleme donusturen bir otonom gorev ajan platformudur.
Sadece sohbet etmez; planlar, tool cagirir, islem yapar, dogrular ve sonuc uretir.

Ana hedef:
- Kullanici komutunu anlamak
- Gorevi adimlara bolmek
- Guvenli sekilde uygulamak
- Kanit/artifact uretmek
- Tutarli ve profesyonel cevap vermek

## 2) Kritik Klasor ve Dosya Haritasi

### Cekirdek
- `core/agent.py`: Ana agent girisi, intentten eyleme gecis, tool entegrasyonu
- `core/pipeline.py`: Validate -> Route -> Plan -> Execute -> Verify -> Deliver akisi
- `core/pipeline_state.py`: Asamalar arasi state/paylasim katmani
- `core/intelligent_planner.py`: Planlama ve gorev ayristirma
- `core/capability_router.py`: Yetenek/karmaşıklik yonlendirmesi
- `core/runtime_policy.py`: Preset ve runtime policy cozumleyici

### Multi-agent ve Sub-agent
- `core/multi_agent/orchestrator.py`: Multi-agent orkestrasyon
- `core/multi_agent/specialists.py`: Uzman roller
- `core/sub_agent/`: Session/manager/executor/validator/team altyapisi

### Gateway ve Kanallar
- `core/gateway/server.py`: HTTP/WebSocket gateway sunucusu + dashboard API
- `core/gateway/router.py`: Kanal mesajini agente baglayan router
- `core/gateway/adapters/`: Telegram/Discord/Slack vb kanal adapterleri

### Toollar
- `tools/`: Dosya, sistem, API, DB, browser, deploy vb toollar
- `tools/system_tools.py`: Bilgisayar kontrolu, screenshot, wallpaper, UI islemleri

### CLI
- `cli/main.py`: `elyan` komut girisi
- `cli/onboard.py`: Ilk kurulum sihirbazi
- `cli/commands/`: Alt komutlar (gateway, models, channels, doctor, ...)

### Konfig
- `config/elyan_config.py`: Ana config yonetimi
- `~/.elyan/elyan.json`: Runtime config dosyasi (yerel)

### UI
- `ui/web/dashboard.html`: Dashboard arayuzu

### Testler
- `tests/unit/`: Birim testler
- `tests/integration/`: Entegrasyon testleri

## 3) Kod Nasil Yazilmali?

### Temel ilkeler
- Kisa, okunabilir, deterministik kod yaz.
- Mevcut mimariyi bozmadan ekleme yap (no-regression).
- Kodu buyutmeyen, net sorumluluklu degisiklikler tercih et.
- Yan etkisi olan adimlarda kanit/evidence uret.

### Tasarim kurallari
- Planner ile executor ayri sorumlulukta olsun.
- LLM "ne yapilacak" der, sistem "nasil yapilacak" ve "dogrulama"yi yapar.
- Tool cagirilari schema/kontrat ile calissin.
- Her kritik eylem sonrasinda verify gate olsun.

### Guvenlik ve policy
- Runtime policy disina cikma.
- Riskli toollarda guardrail/path check uygulamadan calistirma.
- Varsayilan olarak gereksiz artifact/manifest spam yapma.
- Secret degerleri loglama; keychain/env referansi kullan.

### Test disiplini
- Yeni degisiklikte en az hedef unit test ekle/guncelle.
- Kritik akislarda smoke test calistir.
- Mevcut gecen testleri bozacak kapsamli refactor yapma.

### Kod stili
- Kisa fonksiyonlar, net isimlendirme, erken return.
- Gereksiz soyutlama ve tekrarli koddan kac.
- Uygun yerde tip ipuclari kullan.
- Hata mesajlari eyleme donuk ve anlasilir olsun.

## 4) Gelistirme Akisi (Onerilen)

1. Sorunu netlestir (intent/plan/execute/verify hangi katmanda?).
2. En kucuk guvenli degisiklikle duzelt.
3. Unit test + smoke test calistir.
4. Gerekirse runtime policy/config etkisini kontrol et.
5. Kisa degisiklik ozeti ve dogrulama notu birak.

## 5) Hedef Kalite Cizgisi

- Dogru anlama + dogru uygulama + kanitli sonuc
- Kanal/CLI fark etmeden tutarli davranis
- Gereksiz karmasiklik olmadan profesyonel, bakimi kolay kod
