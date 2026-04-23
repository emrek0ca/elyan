# ELYAN_AGENT_CONSTITUTION.md

## 1. Amaç

Elyan sıradan bir chatbot değildir.  
Elyan; gizlilik odaklı, self-hosted, modüler, sürekli gelişebilen bir AI sistemi olarak inşa edilir.

Bu projede her agentın temel görevi şudur:

- ürünü bozmak değil güçlendirmek
- kod yığını üretmek değil sistemi sadeleştirmek
- rastgele özellik eklemek değil kontrollü yetenek geliştirmek
- sahte “hazır” hissi vermek değil gerçekten çalışan ürün çıkarmak
- Elyan’ı zamanla daha güçlü hale getirmek ama her adımda çekirdeği korumak

Elyan’ın merkezinde şu çekirdek döngü vardır:

**ask -> retrieve -> read -> reason -> answer -> cite -> evaluate -> improve**

Bu döngü bozulursa hiçbir yeni özellik değerli değildir.

---

## 2. Değiştirilemez Kurallar

### 2.1 Ürünü büyütmeden önce ürünü sağlamlaştır
Önce çalışan çekirdek.
Sonra yeni yetenek.

### 2.2 Daha az kodla daha çok iş
Aynı işi daha az kod, daha az katman, daha az bağımlılık ile yapabiliyorsan onu yap.

### 2.3 Sıfırdan yazma refleksi yasak
Olgun, yaşayan, aktif JS/TS kütüphanesi varsa önce onu değerlendir.
Kendi parser’ını, crawler’ını, editor’ünü, chart sistemini, otomasyon katmanını gereksiz yere sıfırdan yazma.

### 2.4 Yarım özelliği görünür bırakma
UI’de görünen her şey çalışmalıdır.
Çalışmayan yüzeyi kaldır, gizle veya açıkça scope dışı bırak.

### 2.5 Agent gibi değil mühendis gibi davran
Her değişiklik:
- neden yapıldı
- neyi etkiliyor
- neyi sadeleştiriyor
- ne riski var
- nasıl geri alınır

bunlarla düşünülmelidir.

### 2.6 Çekirdeği kirletme
Deneysel sistemler, gelecekteki feature’lar, öğrenme motorları, masaüstü otomasyonu veya ağır belge işleme doğrudan core response path içine gömülmez.

### 2.7 Matematiksel doğrulukta tahmin değil araç
Kesin sonuç gereken yerde modelin tahmini değil deterministik hesap motoru kullan.
Yaklaşık cevap ile exact hesap ayrımını açık tut.

---

## 3. Elyan’ın Gerçek Ürün Tanımı

Elyan’ın ilk görevi:
- kullanıcıdan soru almak
- uygun retrieval stratejisi seçmek
- web veya belge kaynaklarını toplamak
- kaynakları temizlemek
- gerekirse araçlarla hesap yapmak
- net cevap üretmek
- atıf vermek
- kaliteyi değerlendirmek

Elyan’ın uzun vadeli görevi:
- yeni yetenekler kazanmak
- daha iyi retrieval yapmak
- daha iyi belge anlamak
- daha iyi araç kullanmak
- daha doğru hesap yapmak
- daha iyi otomasyon kararları vermek
- bunu yaparken kod tabanını çöp haline getirmemek

---

## 4. Mimari Prensip

## 4.1 Çekirdek katmanlar

Elyan şu katmanlarla düşünülmelidir:

1. **UI Layer**
   - chat arayüzü
   - belge arayüzleri
   - çıktı render
   - citation görünümü
   - grafik ve görsel sunum

2. **API / Orchestration Layer**
   - request alma
   - mode seçimi
   - capability routing
   - tool invocation
   - response composition

3. **Core Intelligence Layer**
   - query planning
   - retrieval planning
   - context construction
   - reasoning orchestration
   - answer synthesis
   - citation mapping
   - evaluation hooks

4. **Capability Layer**
   - web search
   - scraping
   - browser actions
   - document read/write
   - charts
   - images
   - math engine
   - desktop automation
   - future memory/learning/eval systems

5. **Persistence / Runtime Layer**
   - config
   - state
   - logs
   - cache
   - optional DB/storage
   - artifacts
   - audit trail

Her katmanın sınırı net olmalı.
Bir katman başka katmanın işini çalmamalı.

---

## 5. Kütüphane Politikası

Aşağıdaki ilke zorunludur:

**Önce güçlü kütüphane, sonra custom kod.**

Önerilen standart yönelim:

- App/web çatısı: Next.js + TypeScript
- AI orchestration/tooling: Vercel AI SDK
- Şema ve doğrulama: Zod
- Hafif HTML extraction: Cheerio
- Dinamik tarayıcı otomasyonu: Playwright
- Crawl orchestration: Crawlee
- PDF extraction: unpdf
- DOCX okuma: Mammoth
- DOCX üretme/yazma: docx
- Zengin belge düzenleme: Tiptap
- Grafikler: Recharts
- Kontrollü desktop automation: @nut-tree/nut-js
- Matematik: math.js
- Hassas decimal hesap: decimal.js
- Görsel üretim/edit: resmi provider SDK’ları ve izole capability adapter’ları

Kural:
- aynı sorunu çözen birden çok dağınık kütüphane ekleme
- eskimiş veya yarım bırakılmış çözümleri sırf “zaten var” diye tutma
- yeni kütüphane ekliyorsan hangi custom kodu sildiğini de belirt

---

## 6. Capability Sistemi

Elyan tek büyük monolit feature yığını olarak büyümeyecek.
Capability tabanlı büyüyecek.

Her capability şu kontrata uymalı:

- adı net olacak
- tek sorumluluğu olacak
- input schema’sı olacak
- output schema’sı olacak
- timeout politikası olacak
- hata modeli olacak
- yan etkileri açık olacak
- audit edilebilir olacak
- disable edilebilir olacak

Örnek capability alanları:

- `web_search`
- `web_read`
- `browser_automation`
- `document_extract_pdf`
- `document_extract_docx`
- `document_write_docx`
- `summarize_document`
- `generate_chart`
- `generate_image`
- `edit_image`
- `math_exact`
- `math_symbolic`
- `desktop_mouse_keyboard`
- `desktop_screen_read`
- `future_memory_search`
- `future_learning_evaluate`

Her capability core path’e gömülmez.
Router/orchestrator üzerinden çağrılır.

---

## 7. AI Mühendisliği Standardı

### 7.1 Model her şeyi “bilmek” zorunda değil
Model:
- plan yapar
- karar verir
- araç çağırır
- kaynakları birleştirir
- cevap sentezler

Ama model:
- kesin matematik motoru değildir
- güvenilir scraper değildir
- dosya parser’ı değildir
- işletim sistemi katmanı değildir

Bunlar capability’lerle çözülür.

### 7.2 Tool-first yaklaşım
Şu durumlarda önce tool düşün:
- yüksek matematik
- kesin sayısal hesap
- belge ayrıştırma
- tablo/veri işleme
- grafik üretimi
- ekran okuma
- browser kontrolü
- dosya yazma
- yapılandırılmış çıktı

### 7.3 Context disiplini
Gereksiz bağlam yükleme.
Her capability yalnızca ihtiyaç duyduğu bağlamı alır.
“Her şeyi prompta dök” yaklaşımı yasak.

### 7.4 Cevap kalitesi
Cevaplar:
- net
- kaynaklı
- kısa ama yetersiz olmayan
- gerekli yerde yapılandırılmış
- belirsizlikte dürüst
- gerekirse hesap/araç sonucuna dayalı

---

## 8. Otomasyon Mühendisliği Standardı

### 8.1 Kontrolsüz otomasyon yasak
Elyan bilgisayarda “her şeyi” yapmaya kalkmaz.
Her otomasyon:
- kullanıcı tetiklemeli
- izinli
- kapsamı belirli
- loglu
- geri alınabilir
- varsayılan olarak güvenli

### 8.2 Desktop automation sınırı
Mouse, keyboard, screen ve window işlemleri yalnızca açık capability olarak sunulur.
Core answering path’in içine gizlenmez.

### 8.3 Browser automation sınırı
Tarayıcı otomasyonu scraping, login gerektiren iş akışı, form doldurma veya sayfa içi veri toplama için kullanılabilir.
Ancak:
- timeout gerekir
- selector stratejisi gerekir
- başarısızlık fallback’i gerekir
- sınırsız gezinme yasaktır

### 8.4 Dosya sistemi sınırı
Belge oluşturma/düzenleme capability’leri belirlenmiş dizinlerde çalışır.
Rastgele sistem dosyalarına dokunulmaz.

---

## 9. Matematiksel ve Analitik Standart

Elyan yüksek matematiksel işlemleri “tahmin ederek” yapmaz.

### 9.1 Exact vs Approx ayrımı
Her hesap şu sınıflardan birine girer:
- exact symbolic
- exact decimal / arbitrary precision
- approximate numeric
- statistical / probabilistic
- simulation

Yanıt verirken hangi sınıfta sonuç verdiğini sistem bilmeli.

### 9.2 Zorunlu araç kullanımı gereken durumlar
Aşağıdaki işlerde model tek başına güvenilmez:
- uzun cebirsel dönüşümler
- hassas finansal hesap
- istatistiksel özet ve dağılım
- matris işlemleri
- grafik verisi üretimi
- sembolik ifade işleme
- yüksek hassasiyetli decimal işlemler

Bu durumlarda:
- math engine kullan
- precision politikasını açık tut
- gerekiyorsa ara adımları sakla
- mümkünse hesap sonucunu doğrula

### 9.3 Verification loop
Önemli hesaplarda:
1. input doğrula
2. hesapla
3. sonucu normalize et
4. ikinci kontrol yap
5. kullanıcıya sun

---

## 10. Kod Sağlığı Standardı

### Yasaklar
- giant file
- gizli side effect
- type’sız payload
- any ile geçiştirme
- duplicated logic
- fake abstraction
- dead route
- dead component
- dead command
- placeholder UI
- “ileride lazım olur” diye bırakılmış yarım sistem

### Zorunlular
- küçük modüller
- net isimler
- typed schema
- testable boundaries
- sade kontrol akışı
- minimal ama etkili yorumlar
- loglanabilir hata akışı
- launch scope disiplini

---

## 11. Sürekli Gelişim İlkesi

Elyan sürekli gelişecek.
Ama bu şu anlama gelmez:
- her gün yeni feature
- her yere memory
- her yere agent
- her yere automation
- her yere evaluation eklemek

Doğru büyüme akışı şudur:

1. çekirdeği koru
2. capability sınırı tanımla
3. küçük ama gerçek modül ekle
4. çalıştığını doğrula
5. etkisini ölç
6. gerekirse promote et
7. sonra bir sonraki capability’ye geç

### Öğrenme sistemi ilkesi
Öğrenme:
- kontrollü
- gözlemlenebilir
- geri alınabilir
- değerlendirmeli
- üretim davranışını kirletmeyen

olmalıdır.

Sessizce kendini bozan “self-improving” tiyatrosu yasak.

---

## 12. VPS / Runtime Güvenliği

Elyan canlı ortamda çalışıyorsa agent şu kurala uyar:

- yalnızca Elyan kapsamındaki servis, dosya, volume, env, port ve route’lara dokun
- başka projelere dokunma
- geniş temizlik komutları çalıştırma
- stateful değişiklikte önce backup/rollback düşün
- güncelleme akışını kontrollü yap
- env validation olmadan deploy etme
- health check ve log kontrolü olmadan “tamam” deme

Kural:
**Bu sunucu yalnızca Elyan’a ait değilmiş gibi davran.**

---

## 13. Bir Göreve Başlamadan Önce Zorunlu Checklist

Her agent önce şunu çıkarır:

1. Bu değişikliğin amacı ne?
2. Elyan’ın hangi katmanını etkiliyor?
3. Hangi dosyaları gerçekten değiştirmesi gerekiyor?
4. Hangi capability ile ilgili?
5. Hangi mevcut kod korunmalı?
6. Hangi kısım silinmeli veya sadeleşmeli?
7. Hangi risk var?
8. Bu değişiklik launch scope içinde mi?
9. Nasıl test edilecek?
10. Nasıl geri alınacak?

Bu sorulara cevap vermeden kod değişikliği yapılmaz.

---

## 14. İş Bitirme Standardı

Bir iş şu durumda bitmiş sayılır:

- build geçer
- lint geçer
- kritik akış bozulmaz
- yeni capability gerçekten çalışır
- UI’de kırık yüzey yoktur
- hata/boş/loading state’leri dürüsttür
- dead code bırakılmamıştır
- scope dışı yüzey görünür değildir
- değişiklik açıklanabilir durumdadır

“Yazdım ama sonra bakarız” bitmiş sayılmaz.

---

## 15. Agent Raporlama Formatı

Her ilerleme raporu şu 6 başlıkla gelir:

- Ne korundu
- Ne kaldırıldı
- Ne sadeleştirildi
- Hangi capability eklendi veya iyileştirildi
- Hangi kütüphane entegre edildi ve neden
- Sonraki adıma geçmeden önce kalan gerçek risk

Bunun dışında laf kalabalığı yasak.

---

## 16. Son Hüküm

Elyan’ın amacı büyük görünmek değil, güçlü olmaktır.

Her agent şunu hatırlayacak:

- Kod birikimi başarı değildir
- Özellik sayısı başarı değildir
- Mimari gösteriş başarı değildir
- Gerçek başarı:
  - daha temiz sistem
  - daha güçlü çekirdek
  - daha net capability sınırları
  - daha doğru cevaplar
  - daha güvenli otomasyon
  - daha sağlam deploy
  - daha kontrollü sürekli gelişim

Eğer bir değişiklik Elyan’ı daha anlaşılır, daha sağlam, daha doğru ve daha geliştirilebilir yapmıyorsa o değişiklik yapılmamalıdır.