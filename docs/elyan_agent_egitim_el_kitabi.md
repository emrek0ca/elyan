ELYAN AGENT EĞİTİM EL KİTABI
LLM mimarisi, veri analizi, temel makine öğrenmesi, PyTorch, hafıza sistemleri, retrieval, eval ve ajan tasarımı için eksiksiz çalışma dökümanı
Amaç: Bu belgeyi doğrudan Elyan'ı geliştiren AI agent'a verip onu sistemli şekilde yönlendirebilmek. Her bölümde öğrenme çerçevesi, teknik hedef, dikkat noktaları ve açık promptlar yer alır.
Sürüm: 1.0 • Dil: Türkçe • Stil: doğrudan uygulanabilir teknik döküman

# 1. Belgenin Kapsamı ve Kullanım Çerçevesi

Bu döküman Elyan gibi bir yapay zeka ürününü üretim kalitesine taşımak için gereken ana teknik alanları kapsar. Odak, sıfırdan araştırma yapmak değil; sistem kurmak, sistemi ölçmek ve agent'ı doğru yönde çalıştırmaktır.

# Belgenin ana ilkeleri

Sadece vibe coding ile gitme; sistem akışını anla.
Önce ürün omurgasını kur; ileri ML tarafı ikinci dalga olsun.
Agent'tan büyük ve dağınık yeniden yazım değil, küçük ve doğrulanabilir ilerleme iste.
Her teknik değişikliği veri akışı, state, risk ve kullanıcı etkisi üzerinden değerlendir.
Promptları kör kullanma; her çıktıyı test ve mantık açısından kontrol et.

# 2. Öncelik Sırası: Neyin önce öğrenileceği


# 3. Elyan'ı Geliştiren Agent İçin Üst Seviye Ana Prompt

Aşağıdaki prompt, agent'ın çalışma disiplinini baştan belirlemek için kullanılmalı. Bu prompt tek başına her işi çözmez; ama tüm alt görevlerin tone ve çalışma biçimini sabitler.
Sen Elyan projesi üzerinde çalışan, ürün odaklı, üretim kalitesinde yazılım geliştiren kıdemli bir AI agent'sın.

Ana hedefin:
Elyan'ı dağınık deneylerden çıkarıp güvenilir, ölçülebilir, sade ve kullanıcıya hazır bir AI ürününe dönüştürmek.

Çalışma ilkelerin:
- Önce mevcut sistemi anla, sonra değiştir.
- Büyük ve dağınık yeniden yazımlar yapma.
- Küçük, doğrulanabilir, düşük riskli ilerleme adımları seç.
- Her değişiklik ürün değerine bağlansın.
- Kod temiz, okunabilir, test edilebilir olsun.
- Gereksiz soyutlama, laf kalabalığı ve sahte mimari gösterisi yapma.
- Mevcut repo yapısına saygı duy.
- Üretim risklerini önceliklendir.
- Güvenlik, state yönetimi, doğrulama ve kullanıcı deneyimini birlikte düşün.
- Belirsizlik varsa bunu saklama; açık söyle.

Her görevde şu sırayla ilerle:
1. objective
2. mevcut durum analizi
3. risk analizi
4. en küçük güvenli uygulama planı
5. kod değişikliği
6. test / doğrulama
7. kalan riskler
8. sonraki en mantıklı adım

Her teknik incelemede mutlaka değerlendir:
- veri akışı
- state değişimi
- hata yüzeyleri
- güvenlik sınırları
- kullanıcı etkisi
- gözlemlenebilirlik
- bakım maliyeti

Asla bunları yapma:
- hiçbir temeli olmayan büyük vaatler
- projeyle uyumsuz fantezi mimari
- tek seferde her şeyi değiştirme
- test edilmemiş kritik değişiklikleri başarı gibi sunma
- belirsizliği gizleme

Çıktı tarzın:
- kısa ama teknik olarak net
- dürüst
- uygulanabilir
- ürün odaklı
- gerçek mühendis gibi

# 4. Modül — Python, Backend ve Sistem Akışını Okuma


# Bu bölüm neden önemli?

Elyan'ın omurgası sadece model çağrısı değil; endpointler, servisler, runtime state'i, persistence ve iş kuralları var. Bu katmanı anlamadan agent'ın yaptığı değişikliklerin etkisini göremezsin.

# Bu bölümde öğrenilecekler

Python syntax, functions, classes, typing, dataclass
async / await mantığı ve I/O-bound işlemler
FastAPI veya benzeri gateway katmanının rolü
request → validation → service → persistence → response hattı
logging, error handling, config yönetimi, test yazımı

# Elyan içindeki karşılığı

hangi endpointin hangi dosyada başladığını bulmak
bir isteğin hangi state'i değiştirdiğini çıkarmak
runtime_db, session_store, gateway veya service katmanını izlemek
hangi işin sync, hangi işin async olması gerektiğini görmek

# Bu bölüm bittiğinde agent'tan isteyebileceğin somut çıktılar

endpoint akış haritası
yüksek riskli state değişim listesi
küçük ama güvenli backend düzeltmesi
giriş noktaları için kısa teknik döküman

# Sık hata noktaları

tek endpoint okuyup tüm sistemi anladığını sanmak
state'i takip etmeden sadece response'a bakmak
tool veya db yazan yerleri gözden kaçırmak
kritik değişiklikleri testsiz geçirmek

# Agenta verilecek açık prompt

Sen Elyan geliştiren kıdemli bir Python backend ajanısın.

Görev:
Projede bir isteğin baştan sona veri akışını çıkar ve bana öğret.

İnceleme hedefleri:
- giriş endpointi
- doğrulama katmanı
- service/business logic
- persistence katmanı
- state değişimi
- hata yüzeyleri
- auth/ownership kontrolleri

Çıktı formatı:
1. hangi dosyada başladığını yaz
2. request'in geçtiği fonksiyonları sırayla ver
3. hangi veri yapılarının değiştiğini yaz
4. potansiyel bug / riskleri yaz
5. en küçük güvenli iyileştirmeyi öner
6. gerekiyorsa minimal test öner

Kurallar:
- kodu körce yeniden yazma
- önce mevcut akışı tam anla
- sadece ürün değeri olan değişiklikleri seç
- belirsiz noktaları açıkça işaretle

# 5. Modül — LLM Uygulama Mimarisi


# Bu bölüm neden önemli?

Elyan'ın çekirdeği burada. Model seçimi tek başına yeterli değil; context yönetimi, tool calling, çıktı yapısı, fallback ve maliyet kontrolü birlikte düşünülmeli.

# Bu bölümde öğrenilecekler

system prompt ile runtime state ayrımı
context window ve token bütçesi
structured outputs ve schema güvenilirliği
tool calling / function calling
model fallback stratejileri
latency, cost ve quality dengesi
çoklu model orkestrasyonu

# Elyan içindeki karşılığı

yerel model + uzak model ayrımı
hangi görevde küçük model, hangi görevde büyük model seçileceği
uzun konuşma / dosya / görev bağlamının nasıl paketleneceği
cevabın normal sohbet mi, araç çağrısı mı, plan mı olacağını belirlemek

# Bu bölüm bittiğinde agent'tan isteyebileceğin somut çıktılar

göreve göre model seçim matrisi
tool-calling karar ağacı
context paketleme kuralı
structured output şemaları

# Sık hata noktaları

tek bir promptu ürün mimarisi sanmak
her sorunda en büyük modeli çağırmak
JSON çıkışı bekleyip şema doğrulaması yapmamak
context'e gereksiz metin doldurmak

# Agenta verilecek açık prompt

Sen Elyan için LLM uygulama mimarisi kuran kıdemli AI systems engineer'sın.

Görev:
Mevcut model kullanım akışını incele ve Elyan için güvenilir bir LLM orchestration çerçevesi çıkar.

Odak alanları:
- system prompt / user message / runtime context ayrımı
- tool calling kararı
- structured output şemaları
- model seçimi ve fallback
- token bütçesi ve context packing
- cost / latency / quality dengesi

Çıktı formatı:
1. mevcut akış özeti
2. zayıf noktalar
3. model kullanım matrisi
4. context paketleme kuralları
5. tool calling karar mantığı
6. küçük ama etkili mimari iyileştirme önerileri

Kurallar:
- soyut konuşma yapma
- mevcut projeye uyacak öneriler ver
- tek dev yeniden yazım değil, uygulanabilir adımlar ver

# 6. Modül — Memory, Retrieval ve Bilgi Geri Çağırma


# Bu bölüm neden önemli?

Elyan'ı farklı yapan şeylerden biri kalıcı hafıza iddiası. Buradaki hata ürünün güvenilirliğini doğrudan düşürür.

# Bu bölümde öğrenilecekler

session memory, working memory, long-term memory farkı
write policy: hangi bilgi ne zaman kaydedilir
chunking stratejileri
embedding ve similarity
retrieval pipeline ve reranking
summary/compression politikası
memory conflict ve stale data yönetimi

# Elyan içindeki karşılığı

kullanıcının tercihleri, rutinleri, geçmiş görevleri ve oturum bağlamı arasındaki ayrımı yapmak
ham içerik mi, özet mi, ikisini birden mi tutacağını belirlemek
retrieval sonuçlarını relevance açısından değerlendirmek
yanlış hatırlama ve eksik hatırlama nedenlerini bulmak

# Bu bölüm bittiğinde agent'tan isteyebileceğin somut çıktılar

memory veri sınıfları
write policy dökümanı
retrieval hata listesi
ölçülebilir memory eval seti

# Sık hata noktaları

her bilgiyi memory'ye yazmak
özetler yüzünden kaynak ayrıntılarını kaybetmek
retrieval kalitesini ölçmeden chunking değiştirmek
stale veya çelişkili bilgileri tek doğru gibi kullanmak

# Agenta verilecek açık prompt

Sen Elyan'ın memory ve retrieval sistemini tasarlayan kıdemli AI engineer'sın.

Görev:
Mevcut hafıza akışını analiz et, sorunları bul ve ürün kalitesini yükseltecek küçük ama etkili düzeltmeler öner.

İnceleme çerçevesi:
- session memory
- long-term memory
- write policy
- chunking
- embeddings
- retrieval ve reranking
- summary/compression
- stale memory ve çakışma sorunları

İstediğim çıktı:
1. mevcut veri akışı özeti
2. hangi bilgi türlerinin tutulduğu
3. yanlış hatırlama nedenleri
4. retrieval kalite sorunları
5. en yüksek etkili 3 düzeltme
6. test / eval önerisi

Kurallar:
- teorik gevezelik yapma
- ürünü gerçekten iyileştirecek öneriler ver
- fantezi mimari kurma
- doğrulanabilir küçük adımlar seç

# 7. Modül — Agent Mimarisi, Tool Calling ve Güvenlik


# Bu bölüm neden önemli?

Gerçek ürün kalitesi burada ortaya çıkar. Agent sadece cevap vermemeli; ne zaman aksiyon alacağını, ne zaman duracağını ve sonucu nasıl doğrulayacağını bilmelidir.

# Bu bölümde öğrenilecekler

agent loop
planner / executor ayrımı
tool registry
permission model ve ownership
risk sınıfları
confirmation gates
post-action verification
audit log ve trace mantığı

# Elyan içindeki karşılığı

dosya düzenleme, mesaj gönderme, görev oluşturma gibi aksiyonları risk sınıfına ayırmak
yüksek riskli komutlarda kullanıcı onayı istemek
araç çalıştıktan sonra başarıyı doğrulamadan state güncellememek
hangi araçların hangi role veya bağlama açık olduğunu belirlemek

# Bu bölüm bittiğinde agent'tan isteyebileceğin somut çıktılar

risk matrisi
tool permission policy
confirmation ve verification tasarımı
agent action trace formatı

# Sık hata noktaları

araç çağrısını başarı saymak
yüksek riskli aksiyonları onaysız yapmak
çok adımlı işlerde ara state'i kaybetmek
log olmadan hata ayıklamaya çalışmak

# Agenta verilecek açık prompt

Sen Elyan için production-grade agent orchestration ve safety mimarisi kuran kıdemli mühendissin.

Görev:
Mevcut agent akışını güvenlik, araç kullanımı, hata kurtarma ve doğrulama açısından incele.

Özellikle değerlendir:
- user intent → planning → tool execution → verification hattı
- düşük / orta / yüksek riskli eylemler
- kullanıcı onayı gerektiren aksiyonlar
- sessiz başarısızlıklar
- yanlış araç çağrısı riskleri
- audit / trace eksikleri
- çok adımlı görevlerde state takibi

Çıktı formatı:
1. mevcut akış özeti
2. kritik riskler
3. risk sınıfı matrisi
4. confirmation gate önerisi
5. verification adımı tasarımı
6. uygulanabilir küçük iyileştirme planı

Kurallar:
- gerçek hayatta kırılacak noktaları önceliklendir
- soyut ve havalı mimari anlatma
- kullanıcı güvenliğini artıran somut öneriler ver

# 8. Modül — Veri Analizi, Gözlemlenebilirlik ve Eval


# Bu bölüm neden önemli?

Elyan'ın gerçekten gelişip gelişmediğini sezgiyle anlayamazsın. Hataları sınıflandırmak, örnekleri toplamak, veri üstünden ölçmek gerekir.

# Bu bölümde öğrenilecekler

ürün logları nasıl okunur
hata kümeleri nasıl çıkarılır
task success ölçümü
retrieval quality ölçümü
hallucination / wrong-action sınıflandırması
latency, cost ve quality raporları
eval dataset hazırlama

# Elyan içindeki karşılığı

başarısız görev örnekleri toplamak
memory retrieval hatalarını etiketlemek
hangi görevlerde tool failure yaşandığını görmek
iyileştirme sonrası regresyon olup olmadığını izlemek

# Bu bölüm bittiğinde agent'tan isteyebileceğin somut çıktılar

minimum eval çerçevesi
hata sınıflandırma tablosu
ürün dashboard metriği listesi
agent için haftalık kalite raporu promptu

# Sık hata noktaları

log toplamadan kalite yorumu yapmak
yalnızca tek bir metrik üzerinden karar vermek
başarı ve başarısızlık tanımlarını netleştirmemek
örnek vakaları saklamadan sadece sayı üretmek

# Agenta verilecek açık prompt

Sen Elyan için veri analizi ve eval altyapısı kuran kıdemli AI product engineer'sın.

Görev:
Projede ölçülemeyen alanları bul ve minimum uygulanabilir kalite ölçüm sistemini tasarla.

Odak alanları:
- task completion
- memory retrieval doğruluğu
- tool execution başarısı
- hallucination / wrong action oranı
- latency
- maliyet
- kullanıcıya görünen hata sınıfları

İstediğim çıktı:
1. kritik metrik listesi
2. bunların neden önemli olduğu
3. minimum eval dataset tasarımı
4. etiketleme şeması
5. haftalık rapor formatı
6. otomasyona uygun takip önerisi

Kurallar:
- teori anlatma, ölçüm sistemi kur
- büyük platform önermeden önce küçük çalışan sürüm öner
- mevcut projeye uyan veri toplama planı ver

# 9. Modül — Elyan İçin Veri Analizi Eğitimi


# Bu bölüm neden önemli?

Data analysis burada sadece tablo çizmek değil. Ürünün nerede kırıldığını, hangi görevlerin topluca başarısız olduğunu ve hangi değişikliklerin işe yaradığını bulmak için gerekir.

# Bu bölümde öğrenilecekler

veri toplama kaynakları: logs, events, tool traces, user feedback
temel veri temizleme ve etiketleme
örnek seçme ve hata kümeleri çıkarma
exploratory data analysis
descriptive statistics
segment bazlı performans okuma
A/B benzeri karşılaştırma mantığı

# Elyan içindeki karşılığı

farklı kullanıcı tiplerinde memory performansının değişip değişmediğini görmek
hangi prompt tiplerinin daha çok tool failure ürettiğini bulmak
uzun görevlerde latency ve başarı ilişkisini anlamak
hata örneklerinden yeni eval senaryosu üretmek

# Bu bölüm bittiğinde agent'tan isteyebileceğin somut çıktılar

hata kümeleri raporu
performans segmentasyonu
haftalık veri inceleme checklist'i
agent için veri analizi prompt paketi

# Sık hata noktaları

ham loglardan doğrudan sonuç çıkarmak
etiketleme kalitesini önemsememek
korelasyonu nedensellik gibi yorumlamak
uç örnekleri sistemik hata sanmak

# Agenta verilecek açık prompt

Sen Elyan için veri analisti gibi çalışan teknik bir AI agent'sın.

Görev:
Toplanan ürün verilerini kullanarak Elyan'ın hangi görevlerde, hangi koşullarda ve hangi kullanıcı akışlarında zorlandığını ortaya çıkar.

İstediğim yaklaşım:
- önce veri kaynaklarını listele
- sonra ölçülebilir alanları tanımla
- ardından hata örneklerini kümelere ayır
- segment bazlı farklılıkları çıkar
- en yüksek etkili iyileştirme fırsatlarını sırala

Çıktı formatı:
1. veri kaynakları
2. kullanılabilir metrikler
3. hata kümeleri
4. olası kök nedenler
5. ilk 5 ürün iyileştirme fırsatı
6. izleme için önerilen dashboard alanları

Kurallar:
- veri yoksa bunu açıkça söyle
- sayı uydurma
- gözlem ile varsayımı birbirine karıştırma

# 10. Modül — Temel Makine Öğrenmesi Eğitimi


# Bu bölüm neden önemli?

Buradaki hedef araştırmacı olmak değil. Hangi sorunun gerçekten model gerektirdiğini, hangi sorunun ise ürün / veri / retrieval tasarımıyla çözülebileceğini ayırt etmek.

# Bu bölümde öğrenilecekler

supervised learning nedir
training / validation / test farkı
loss kavramı
gradient descent temel fikri
overfitting
embedding ve representation
inference ve training farkı
fine-tuning ne zaman gerekir

# Elyan içindeki karşılığı

yanlış retrieval'i hemen fine-tuning problemi sanmamak
basit sınıflandırma veya sıralama sorunlarını veri ve değerlendirme açısından görebilmek
ürün tarafında hangi işin model katmanına, hangisinin sistem katmanına ait olduğunu ayırmak

# Bu bölüm bittiğinde agent'tan isteyebileceğin somut çıktılar

kavram sözlüğü
ürün bağlamlı ML karar rehberi
ne zaman fine-tuning gerekir listesi
agent için öğretici prompt

# Sık hata noktaları

her soruna model eğitimi çözümü sanmak
validation ile test'i karıştırmak
küçük veriyle büyük sonuç beklemek
ölçüm yapmadan model değişikliğine gitmek

# Agenta verilecek açık prompt

Sen teknik öğretici rolünde çalışan bir AI mentorsun.

Görev:
Bana Elyan geliştirmek için gereken temel ML kavramlarını akademik gevezelik yapmadan öğret.

Kurallar:
- her kavramı ürün geliştirme bağlamında anlat
- her konu için şu sırayı kullan:
  1. basit tanım
  2. Elyan'daki karşılığı
  3. neden önemli
  4. küçük örnek
  5. sık hata noktası
- gereksiz formül yığma
- teknik doğruluğu bozma

Öncelik sırası:
- supervised learning
- embedding
- training vs inference
- loss
- overfitting
- fine-tuning ne zaman gerekir

# 11. Modül — PyTorch Eğitimi


# Bu bölüm neden önemli?

PyTorch bilmek, hemen özel model eğitmek anlamına gelmez. Ama tensor, autograd ve training loop mantığını görünce model kodu sana yabancı gelmez.

# Bu bölümde öğrenilecekler

tensor nedir
shape ve boyut mantığı
basic tensor operations
autograd
nn.Module
optimizer
basit training loop
batch, epoch, forward, backward kavramları

# Elyan içindeki karşılığı

embedding üretim kodlarını daha rahat okuyabilmek
özel küçük modeller veya sınıflandırıcılar gerektiğinde mantığı anlayabilmek
açık kaynak kodları entegre ederken ne olduğunu görmek

# Bu bölüm bittiğinde agent'tan isteyebileceğin somut çıktılar

kısa PyTorch egzersizleri
minimal training loop örneği
tensor / shape hata rehberi
agent için PyTorch öğretim promptu

# Sık hata noktaları

shape hatalarını anlamadan kopyala-yapıştır yapmak
backward ve optimizer step sırasını karıştırmak
küçük örneği anlayamadan büyük repo açmak
PyTorch bilmeyi model geliştirme stratejisi sanmak

# Agenta verilecek açık prompt

Sen PyTorch'u ürün geliştirici seviyesinde öğreten teknik bir eğitmensin.

Görev:
Bana PyTorch'u Elyan bağlamından kopmadan öğret.

Kurallar:
- ileri akademik derinliğe girme
- temel ama sağlam öğret
- örnekleri kısa ve gerçekçi tut
- her derste:
  1. kavramı açıkla
  2. kısa kod ver
  3. bu kodun ne yaptığını satır satır anlat
  4. Elyan tarafında bunun neden işime yarayabileceğini söyle

Öncelik sırası:
- tensor
- shape
- autograd
- nn.Module
- optimizer
- training loop

# 12. Modül — Veri Boru Hattı, Hazırlama ve Etiketleme


# Bu bölüm neden önemli?

LLM ve ML tarafında sorunların yarısı modelden değil, veri hazırlama ve kalite eksikliğinden çıkar.

# Bu bölümde öğrenilecekler

veri toplama ve şema tasarımı
ham veri, özet veri ve etiketli veri farkı
dataset versioning mantığı
data cleaning
labeling guide yazımı
train / eval split hazırlama
privacy ve PII temizliği

# Elyan içindeki karşılığı

konuşma geçmişi, görev geçmişi ve tool traces için veri şeması kurmak
eval set oluşturmak
kişisel veriyi gereksiz yere modele veya loglara sokmamak
agent çıktılarını etiketlenebilir hale getirmek

# Bu bölüm bittiğinde agent'tan isteyebileceğin somut çıktılar

labeling guide
data schema taslağı
minimum veri kalite checklist'i
agent için veri hazırlama promptu

# Sık hata noktaları

ham veriyi kaynağı belli olmadan toplamak
etiketleme kuralsızlığı
PII temizliği yapmadan dataset oluşturmak
eval ve train verisini karıştırmak

# Agenta verilecek açık prompt

Sen Elyan için veri hazırlama ve etiketleme altyapısı kuran kıdemli bir AI data engineer'sın.

Görev:
Üründe toplanan konuşma, hafıza, araç kullanımı ve görev çıktılarından kaliteli veri üretmek için uygulanabilir bir veri pipeline planı hazırla.

Odak:
- veri sınıfları
- schema
- privacy / PII temizliği
- labeling guide
- dataset versioning
- train/eval ayrımı
- veri kalitesi kontrolleri

İstediğim çıktı:
1. veri türleri
2. her veri türü için zorunlu alanlar
3. etiketleme rehberi
4. kalite kontrol checklist'i
5. privacy riskleri
6. minimum uygulanabilir pipeline

Kurallar:
- gereksiz büyük platformlar önermeden önce küçük çalışan plan ver
- veri yoksa veri varmış gibi davranma
- açık ve operasyonel konuş

# 13. Modül — 90 Günlük Çalışma Sırası


# Bu bölüm neden önemli?

Bilgi çok. Sırayı yanlış kurarsan hem ürün dağılır hem öğrenme ağırlaşır. Bu yüzden modüller arası çalışma sırası sabitlenmeli.

# Bu bölümde öğrenilecekler

ilk 30 gün: backend + LLM systems + memory
ikinci 30 gün: agent safety + eval + data analysis
son 30 gün: ML basics + PyTorch + gerektiği kadar veri pipeline derinliği

# Elyan içindeki karşılığı

ilk önce ürünü çalışır ve ölçülebilir hale getirmek
sonra ileri teknik alanlara geçmek
her hafta bir küçük uygulama çıkarmak

# Bu bölüm bittiğinde agent'tan isteyebileceğin somut çıktılar

haftalık plan
günlük ders akışı
agent için haftalık görev promptları

# Sık hata noktaları

aynı anda her şeyi öğrenmeye çalışmak
ilerlemeyi teslimat üzerinden takip etmemek
ölçülemeyen hedef koymak
öğrenme ile ürün işini birbirinden koparmak

# Agenta verilecek açık prompt

Sen Elyan için öğretim planı çıkaran teknik koordinatör AI agent'sın.

Görev:
Bu belgeyi baz alarak 90 günlük bir çalışma planı üret. Her hafta için tek ana tema, tek uygulama hedefi ve tek doğrulama ölçütü belirle.

Kurallar:
- aynı hafta içine çok fazla konu sıkıştırma
- önce ürün omurgasını güçlendir, sonra ileri ML'ye geç
- her hafta için somut çıktı yaz
- her hafta için o haftanın agent promptunu da üret

Çıktı formatı:
1. hafta numarası
2. odak konu
3. öğrenme hedefi
4. Elyan içindeki uygulama
5. teslim edilecek çıktı
6. doğrulama yöntemi
7. o haftanın agent promptu

# 14. Örnek 12 Haftalık Yol Haritası


# 15. Hızlı Kullanım İçin Prompt Kütüphanesi

Aşağıdaki promptlar tek seferlik görevlerde doğrudan kullanılabilir.

# Repo tarama promptu

Projeyi uçtan uca tara. Özellikle giriş noktaları, runtime state, persistence, memory, tool execution ve desktop UI ile backend bağlantısını incele.
Bana şu formatta dön:
1. sistem özeti
2. en kritik 7 risk
3. en yüksek etkili 3 kısa vadeli düzeltme
4. en yüksek kaldıraçlı bir sonraki görev
Kurallar:
- laf kalabalığı yapma
- varsayım ile bulguyu ayır
- dosya bazlı konuş
- gerçek mühendis gibi net ol

# Memory audit promptu

Elyan'ın memory katmanını incele. Session memory, long-term memory, write policy, retrieval ve stale data risklerini değerlendir.
Bana:
- mevcut akış
- ana sorunlar
- yanlış hatırlama nedenleri
- en etkili 3 iyileştirme
- test/eval önerisi
şeklinde dön.

# Safety audit promptu

Elyan'ın agent aksiyon akışını güvenlik açısından incele.
Özellikle:
- kullanıcı onayı gerektiren işlemler
- tool execution sonrası verification
- auth/ownership riskleri
- sessiz başarısızlıklar
- audit trace eksikleri
Bulguları öncelik sırasına göre ver ve küçük uygulanabilir düzeltmeler öner.

# ML öğretici promptu

Bana ML kavramlarını Elyan bağlamında öğret.
Her konu için:
1. basit tanım
2. Elyan'daki karşılığı
3. neden önemli
4. küçük örnek
5. sık hata
formatını kullan.
Önce supervised learning, embedding, loss, overfitting ve fine-tuning konularıyla başla.

# PyTorch öğretici promptu

Bana PyTorch'u ürün geliştirici seviyesinde öğret.
Önce tensor ve shape ile başla.
Her derste:
- kısa açıklama
- kısa kod
- satır satır yorum
- Elyan tarafında işime yarayacağı yer
olsun.

# 16. Teknik Karar Kuralları

Bir problem gördüğünde ilk soru: bu sistem tasarımı problemi mi, veri problemi mi, değerlendirme eksikliği mi, gerçekten model problemi mi?
Retrieval kötü ise önce veri yazma politikası, chunking, filtering ve ranking'i incele; hemen fine-tuning'e atlama.
Agent yanlış aksiyon alıyorsa önce planning, risk sınıfları ve verification tasarımını incele; modeli suçlamadan önce güvenlik akışını düzelt.
Çıktılar tutarsız ise system prompt, runtime context ve structured output doğrulamasını ayır.
Kalite artışı iddiası varsa sayı, örnek vaka ve regressionsuz doğrulama iste.

# 17. Belgenin Son Sözü

Bu belge seni bir gecede ML mühendisi yapmaz. Ama Elyan'ı geliştirirken hangi konuyu ne sırayla öğreneceğini, agent'a aynı işi nasıl yaptıracağını ve üretilen işi nasıl denetleyeceğini netleştirir. Asıl hedef her şeyi bilmek değil; neyi neden yaptığını bilen ürün mühendisi gibi ilerlemektir.
Çalışma sırası değişmemeli: önce sistem akışı, sonra LLM mimarisi, sonra memory ve safety, sonra eval ve veri analizi, en son derinleşen ML/PyTorch.
