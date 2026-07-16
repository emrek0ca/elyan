import type { ReactNode } from "react";
import { Link } from "react-router-dom";

const UPDATED_AT = "15 Temmuz 2026";

type LegalShellProps = {
  kicker: string;
  title: string;
  lead: string;
  children: ReactNode;
};

function LegalShell({ kicker, title, lead, children }: LegalShellProps) {
  return (
    <main>
      <section className="page-hero section-shell">
        <div>
          <span className="section-number">Yasal · {kicker}</span>
          <h1>{title}</h1>
          <div className="page-lead">
            <p>{lead}</p>
            <p>Son güncelleme: {UPDATED_AT}</p>
          </div>
        </div>
      </section>
      <article className="legal section-shell">{children}</article>
    </main>
  );
}

export function PrivacyPage() {
  return (
    <LegalShell
      kicker="Gizlilik"
      title="Gizlilik Politikası"
      lead="Elyan'da hangi bilgilerin hangi sistem sınırında işlendiğini açıklar."
    >
      <h2>Elyan nasıl çalışır?</h2>
      <p>
        Elyan; mobil uygulama, backend kontrol düzlemi ve bilgisayarda çalışan
        yerel runtime'dan oluşur. Mobil uygulama görev göndermek ve sonucu
        göstermek için kullanılır. Backend kimlik doğrulama, abonelik, cihaz
        eşleştirme, görev yönlendirme ve görev durumu gibi kontrol düzlemi
        işlerini yürütür. Bilgisayar araçları ve özel yerel işlemler masaüstü
        runtime'ında çalışır.
      </p>
      <h2>İşlenen bilgi grupları</h2>
      <p>
        Hizmeti sunmak için hesap ve oturum bilgileri, eşleştirilmiş cihaz
        bilgileri, abonelik ve kullanım kayıtları, görev yönlendirme ve durum
        bilgileri ile güvenlik ve hata teşhisine yönelik teknik kayıtlar
        işlenebilir. Bir özelliğin cihaz izni gerektirmesi halinde işletim
        sistemi izin ekranı veya Elyan'ın işlem onayı kullanılır.
      </p>
      <h2>Yerel dosyalar ve bilgisayar eylemleri</h2>
      <p>
        Özel dosyalar ve bilgisayar bağlamı yerel runtime tarafından işlenir. Bu
        içerikler, kullanıcı açıkça izin vermedikçe backend kontrol düzlemine
        gönderilmez. Dosya yazma, belge dışa aktarma, tarayıcı ya da bilgisayar
        kontrolü, otomasyon oluşturma ve yan etkili dış servis çağrıları açık
        izin gerektirir.
      </p>
      <h2>Yapay zekâ hizmetleri</h2>
      <p>
        Bir görev bulut modeli gerektiriyorsa, isteği yanıtlamak için gerekli
        içerik seçilen model sağlayıcısına iletilebilir. Göndermeden önce
        uygulamada sunulan veri paylaşımı açıklamalarını ve izinlerini dikkate
        al. Ayrıntılar için <Link to="/ai">Yapay Zekâ Bildirimi</Link>'ni oku.
      </p>
      <h2>Hesap ve verileri silme</h2>
      <p>
        Mobil uygulamada Ayarlar bölümünden “Hesabı sil” seçeneği
        kullanılabilir. Uygulama bu işlemden önce kalıcı silme uyarısı ve onay
        gösterir; onaylanan istek hesap silme uç noktasına gönderilir ve yerel
        oturum temizlenir. Adımlar için{" "}
        <Link to="/account-deletion">Hesap ve Veri Silme</Link> sayfasına bak.
      </p>
      <h2>İletişim</h2>
      <p>
        Gizlilik veya hesapla ilgili yardım için{" "}
        <Link to="/support">Destek</Link> sayfasını kullan.
      </p>
    </LegalShell>
  );
}

export function TermsPage() {
  return (
    <LegalShell
      kicker="Koşullar"
      title="Kullanım Koşulları"
      lead="Elyan ürün yüzeylerini kullanırken geçerli temel kuralları açıklar."
    >
      <h2>Hizmetin kapsamı</h2>
      <p>
        Elyan, mobil uygulama üzerinden görev vermeyi ve eşleştirilmiş
        bilgisayardaki yerel runtime üzerinden izinli işlemler yürütmeyi
        sağlayan bir yapay zekâ ajan sistemidir. Bazı özellikler aktif internet
        bağlantısı, desteklenen bir cihaz, masaüstü runtime'ı veya ayrı bir
        abonelik gerektirebilir.
      </p>
      <h2>Hesap güvenliği</h2>
      <p>
        Hesabına ve eşleştirilmiş cihazlarına erişimi korumakla sorumlusun.
        Tanımadığın bir oturum veya cihaz görürsen uygulamadaki cihaz ve oturum
        yönetimi araçlarını kullan.
      </p>
      <h2>Kabul edilebilir kullanım</h2>
      <p>
        Elyan'ı yetkisiz erişim, zararlı yazılım, dolandırıcılık, başkalarının
        haklarını ihlal eden işlemler veya yasa dışı otomasyon için
        kullanamazsın. İzin gerektiren bir eylemi onaylamamak görevin güvenli
        biçimde durmasına neden olabilir.
      </p>
      <h2>Yapay zekâ çıktıları</h2>
      <p>
        Yapay zekâ çıktıları eksik veya hatalı olabilir. Özellikle hukuki,
        finansal, tıbbi, güvenlik açısından kritik ya da geri döndürülemez bir
        işlemden önce çıktıyı ve yapılacak eylemi doğrula.
      </p>
      <h2>Abonelikler</h2>
      <p>
        iOS'ta sunulan abonelikler Apple tarafından işlenir. Güncel fiyat,
        deneme, yenileme ve iptal bilgileri satın alma sırasında App Store
        tarafından gösterilir; abonelik yönetimi Apple hesabı üzerinden yapılır.
      </p>
      <h2>İletişim</h2>
      <p>
        Koşullar veya hesap kullanımıyla ilgili yardım için{" "}
        <Link to="/support">Destek</Link> sayfasını kullan.
      </p>
    </LegalShell>
  );
}

export function AiDisclosurePage() {
  return (
    <LegalShell
      kicker="Yapay zekâ"
      title="Yapay Zekâ Bildirimi"
      lead="Elyan'ın yapay zekâ ürettiği yanıtlar ve bilgisayar eylemleri arasındaki farkı açıklar."
    >
      <h2>Yapay zekâ ile etkileşim</h2>
      <p>
        Elyan'daki yanıtlar ve görev planları yapay zekâ sistemleri tarafından
        üretilebilir. Bunlar insan tarafından yazılmış veya önceden doğrulanmış
        içerik değildir; olgusal hata, eksik bağlam ya da yanlış yorum
        içerebilir.
      </p>
      <h2>Plan ile eylem aynı şey değildir</h2>
      <p>
        Bir yanıtın eylem önermesi, eylemin otomatik olarak yürütüldüğü anlamına
        gelmez. Bilgisayar işlemleri capability registry, güvenlik politikası ve
        ilgili adapter üzerinden yürütülür. Dosya yazma, dışa aktarma, tarayıcı
        veya bilgisayar kontrolü ve yan etkili dış servis işlemleri kullanıcı
        iznine tabidir.
      </p>
      <h2>Veri paylaşımı</h2>
      <p>
        Bir istek bulut yapay zekâ modeliyle işlendiğinde, görevi yanıtlamak
        için gereken içerik model sağlayıcısına iletilebilir. Uygulamadaki yapay
        zekâ veri paylaşımı onayları bu akış için kullanılır. Özel bilgisayar
        araçları backend tarafından doğrudan çalıştırılmaz.
      </p>
      <h2>Kullanıcının kontrolü</h2>
      <p>
        İzin ekranındaki işlem kapsamını inceleyebilir, izni reddedebilir veya
        desteklenen uzun görevleri iptal edebilirsin. Kritik sonuçları
        kullanmadan ve geri döndürülemez adımları onaylamadan önce bağımsız
        olarak doğrula.
      </p>
      <h2>Daha fazla bilgi</h2>
      <p>
        Veri akışları için <Link to="/privacy">Gizlilik Politikası</Link>'na,
        kullanım kuralları için <Link to="/terms">Kullanım Koşulları</Link>'na
        bak.
      </p>
    </LegalShell>
  );
}

export function AccountDeletionPage() {
  return (
    <LegalShell
      kicker="Hesap"
      title="Hesap ve Veri Silme"
      lead="Elyan hesabını mobil uygulamadan kalıcı olarak silmek için izlenecek adımlar."
    >
      <h2>Uygulama içinden silme</h2>
      <ol>
        <li>Elyan mobil uygulamasında hesabına giriş yap.</li>
        <li>Ayarlar bölümünü aç.</li>
        <li>“Hesabı sil” seçeneğine dokun.</li>
        <li>Kalıcı silme uyarısını oku ve işlemi onayla.</li>
      </ol>
      <p>
        Onaydan sonra uygulama kimliği doğrulanmış hesap silme isteğini
        gönderir. İstek başarılı olduğunda bu cihazdaki Elyan oturumu ve yerel
        oturum önbelleği temizlenir; giriş ekranına dönülür. Bu işlem geri
        alınamaz.
      </p>
      <h2>Silme işlemi tamamlanmazsa</h2>
      <p>
        Oturum süren dolduysa yeniden giriş yapıp tekrar dene. Geçici bağlantı
        veya sunucu hatasında bağlantı düzeldikten sonra işlemi yinele. Hesaba
        erişemiyorsan <Link to="/support">Destek</Link> sayfasındaki yardım
        kanalını kullan.
      </p>
      <h2>Aboneliği ayrıca yönet</h2>
      <p>
        Hesabı silmek, Apple tarafından yönetilen etkin bir App Store
        aboneliğini otomatik olarak iptal etmeyebilir. Aboneliğini iPhone
        Ayarları → Apple Hesabı → Abonelikler bölümünden kontrol et ve
        gerekiyorsa iptal et.
      </p>
    </LegalShell>
  );
}

export function SupportPage() {
  return (
    <LegalShell
      kicker="Destek"
      title="Elyan Destek"
      lead="Hesap, yasal bağlantılar, abonelik ve teknik sorunlar için başlangıç noktası."
    >
      <h2>Hesap ve oturum</h2>
      <p>
        Giriş, oturum veya hesap silme sorunu yaşıyorsan uygulamadaki Ayarlar ve
        cihaz yönetimi bölümlerini kontrol et. Hesap silme adımları için{" "}
        <Link to="/account-deletion">Hesap ve Veri Silme</Link> sayfasına git.
      </p>
      <h2>Abonelik</h2>
      <p>
        iOS abonelik satın alma, geri yükleme ve yönetimi App Store üzerinden
        yapılır. Etkin aboneliklerini iPhone Ayarları → Apple Hesabı →
        Abonelikler bölümünde görebilirsin.
      </p>
      <h2>Yasal ve veri kullanımı</h2>
      <p>
        <Link to="/privacy">Gizlilik Politikası</Link>,{" "}
        <Link to="/terms">Kullanım Koşulları</Link> ve{" "}
        <Link to="/ai">Yapay Zekâ Bildirimi</Link> sayfaları mobil uygulamadaki
        yasal bağlantıların web karşılıklarıdır.
      </p>
      <h2>Teknik yardım</h2>
      <p>
        Yardım talebinde uygulama sürümünü, işletim sistemini, sorunun görüldüğü
        ekranı ve güvenli hata mesajını paylaş. Parola, erişim anahtarı, oturum
        belirteci veya özel dosya içeriği gönderme.
      </p>
    </LegalShell>
  );
}

export const LEGAL_ROUTE_COMPONENTS = {
  "/privacy": PrivacyPage,
  "/gizlilik": PrivacyPage,
  "/terms": TermsPage,
  "/kullanim-kosullari": TermsPage,
  "/kosullar": TermsPage,
  "/ai": AiDisclosurePage,
  "/yapay-zeka-bildirimi": AiDisclosurePage,
  "/support": SupportPage,
  "/destek": SupportPage,
  "/account-deletion": AccountDeletionPage,
  "/hesap-silme": AccountDeletionPage,
} as const;
