import { getDesktopScreenshots, getMobileScreenshots } from '@/lib/screenshots';
import type { SiteContent } from '@/content/site.types';

const desktopVisual = {
  eyebrow: 'Masaüstü',
  title: 'İşi yapan taraf bilgisayarın.',
  body:
    'Elyan Desktop özel dosyalarını bilgisayarında tutar, görevi güvenle alır ve dosya, takvim, belge gibi işleri senin yerine yürütür.',
  screenshots: getDesktopScreenshots('tr')
} as const;

const mobileVisual = {
  eyebrow: 'Telefon',
  title: 'Cebindeki kumanda.',
  body:
    'Telefonundan konuşur, görevi başlatır ve her adımı canlı izlersin. Ağır iş bilgisayarında çalışır; telefonun hafif kalır.',
  screenshots: getMobileScreenshots('tr')
} as const;

const content: SiteContent = {
  locale: 'tr',
  language: 'Türkçe',
  direction: 'ltr',
  siteName: 'Elyan',
  siteTitle: 'Elyan — Telefonundan konuş, bilgisayarın yapsın',
  siteDescription:
    'Elyan, Türkçe konuşan kişisel yapay zekân. Sohbet eder, araştırır, belge üretir — ve istediğinde eşleştirdiğin bilgisayarda işi senin için gerçekten yapar.',
  heroStatement: 'Kişisel yapay zekâ',
  nav: [
    { href: '/tr/desktop', label: 'Masaüstü' },
    { href: '/tr/mobile', label: 'Mobil' },
    { href: '/tr/download', label: 'İndir' },
    { href: '/tr/support', label: 'Destek' }
  ],
  footer: {
    note:
      'Elyan Türkçe konuşan kişisel yapay zekân. Konuş, üret ve istediğinde bilgisayarına komut ver. Özel işlerin cihazında kalır.',
    legal: [
      { href: '/tr/privacy', label: 'Gizlilik' },
      { href: '/tr/terms', label: 'Koşullar' },
      { href: '/tr/data-deletion', label: 'Veri silme' }
    ],
    support: [
      { href: '/tr/support', label: 'Destek' },
      { href: '/tr/ai', label: 'Zekâ bildirimi' }
    ]
  },
  messages: {
    ui: {
      localeLabel: 'Dil',
      switchToEnglish: 'English',
      switchToTurkish: 'Türkçe',
      openPage: 'Aç',
      backHome: 'Ana sayfaya dön',
      screenshotLabel: 'Gerçek ürün ekranı',
      previousScreenshot: 'Önceki ekran',
      nextScreenshot: 'Sonraki ekran',
      controlLoopTitle: 'Nasıl çalışır',
      legalTitle: 'Resmî bilgi',
      finalCtaLabel: 'Başla',
      footerLegalLabel: 'Yasal',
      footerSupportLabel: 'Destek',
      primaryNavigationLabel: 'Ana menü'
    }
  },
  home: {
    title: 'Telefonundan konuş, bilgisayarın yapsın.',
    description:
      'Elyan, Türkçe konuşan kişisel yapay zekân. Sorularını yanıtlar, araştırır, belge üretir — ve istediğinde eşleştirdiğin bilgisayarda işi senin için gerçekten yapar.',
    eyebrow: 'Kişisel yapay zekâ',
    intro:
      'Çoğu yapay zekâ cevap verir ve orada durur. Elyan bir adım öteye geçer: telefonundan bir şey iste, eşleştirdiğin bilgisayar senin yerine yapsın.',
    ctas: [
      { href: '/tr/desktop', label: 'Nasıl çalışır' },
      { href: '/tr/download', label: 'İndir' }
    ],
    loopTitle: 'Sen yaşarken, işler hallolur.',
    loopSteps: [
      {
        title: 'Söyle',
        body: 'Telefondan ne istediğini yaz ya da söyle. Türkçe, doğal ve sade.',
        image: '/scenes/scene_leaving_home_1782465524838_nobg.png'
      },
      {
        title: 'Anla',
        body: 'Elyan ne demek istediğini çözer ve doğru adımları planlar.',
        image: '/scenes/scene_florist_shop_1782465536520_nobg.png'
      },
      {
        title: 'Yap',
        body: 'İş bilgisayarında gerçekleşir: dosya, takvim, araştırma, belge.',
        image: '/scenes/scene_cafe_flow_1782465546337_nobg.png'
      },
      {
        title: 'Onayla',
        body: 'Riskli bir adım varsa önce sana sorar. Kontrol her zaman sende.',
        image: '/scenes/scene_job_done_1782465567490_nobg.png'
      }
    ],
    desktopVisual,
    mobileVisual,
    boundaryTitle: 'Tek başına cevap değil — sonuç.',
    boundaryCopy: [
      {
        title: 'Konuş ve üret',
        body: 'Soru sor, yazdır, araştır; tablo, belge ve PDF oluştur — hepsi sohbet eder gibi.'
      },
      {
        title: 'Bilgisayarını kullan',
        body: 'Telefondan komut ver, eşleştirdiğin Mac veya PC işi senin için yapsın.'
      },
      {
        title: 'Kontrol sende',
        body: 'Özel işlerin bilgisayarında kalır, riskli adımlarda onayın sorulur.'
      }
    ],
    finalTitle: 'Bugün başla.',
    finalCopy:
      'Elyan’ı indir, bilgisayarını bir kez eşleştir ve ilk işini telefonundan ver.',
    finalLinks: [
      { href: '/tr/download', label: 'İndir' },
      { href: '/tr/desktop', label: 'Nasıl çalışır' },
      { href: '/tr/support', label: 'Destek' },
      { href: '/tr/privacy', label: 'Gizlilik' }
    ],
    systemWidgets: {
      velocityText: 'OTONOM • YEREL • GÜVENLİ • ',
      fabricTitle: 'Yerel Veri Dokusu (Local Fabric)'
    }
  },
  pages: {
    desktop: {
      key: 'desktop',
      heroImage: '/desk_focus.png',
      navLabel: 'Masaüstü',
      title: 'Elyan Masaüstü',
      description: 'İşi yapan taraf. Dosya, belge ve uygulamalar bilgisayarında çalışır.',
      eyebrow: 'Masaüstü',
      intro:
        'Elyan Masaüstü, telefonundan verdiğin görevleri bilgisayarında gerçekten yapan taraftır. Dosya oluşturur, belge yazar, araştırır ve uygulamaları senin için kullanır — özel verin cihazından çıkmadan.',
      sections: [
        {
          title: 'İşi gerçekten yapar',
          body: 'Klasör aç, belge yaz, PDF üret, takvime ekle, araştır. Telefondan iste; bilgisayar yapsın.'
        },
        {
          title: 'Özel verin sende kalır',
          body: 'Özel dosyaların ve yerel işlerin bilgisayarında tutulur. Buluta yalnızca görevin gerektirdiği kadarı, açık biçimde gider.'
        },
        {
          title: 'Telefonunla tek bütün',
          body: 'Telefon ve bilgisayar aynı hesapta buluşur. Birinden başlatırsın, diğeri sürdürür; her adımı canlı görürsün.'
        }
      ],
      visual: desktopVisual,
      ctas: [
        { href: '/tr/download', label: 'İndir ve kur' },
        { href: '/tr/privacy', label: 'Gizliliği incele' }
      ]
    },
    mobile: {
      key: 'mobile',
      heroImage: '/street_flow.png',
      navLabel: 'Mobil',
      title: 'Elyan Mobil',
      description: 'Cebindeki kumanda. Konuş, başlat, canlı izle.',
      eyebrow: 'Telefon',
      intro:
        'Elyan Mobil, kişisel asistanını cebine taşır. Sohbet edersin, soru sorarsın, belge ürettirirsin — ve istediğinde bilgisayarına komut verip işi canlı izlersin.',
      sections: [
        {
          title: 'Konuş, üret, araştır',
          body: 'Türkçe sohbet, anlık web araştırması, belge ve PDF üretimi — hepsi telefonundan.'
        },
        {
          title: 'Bilgisayarına komut ver',
          body: 'Telefondan görev başlat, eşleştirdiğin bilgisayar yapsın. Her adımı canlı takip et.'
        },
        {
          title: 'Hafif ve hızlı',
          body: 'Ağır iş bilgisayarında çalışır; telefonun akıcı, pili uzun ömürlü kalır.'
        }
      ],
      visual: mobileVisual,
      ctas: [
        { href: '/tr/download', label: 'İndir' },
        { href: '/tr/support', label: 'Hesap ve destek' }
      ]
    },
    download: {
      key: 'download',
      navLabel: 'İndir',
      title: 'Elyan’ı indir',
      description: 'Masaüstü kurulumu ve mevcut erişim yolları.',
      eyebrow: 'Kurulum',
      intro:
        'Bu sayfa yalnızca gerçek, doğrulanmış kurulum yollarını listeler. Sahte indirme butonu veya olmayan paket bağlantısı yoktur.',
      sections: [
        {
          title: 'Masaüstü uygulaması',
          body: 'Elyan Masaüstü, işi yapan taraftır. macOS için Homebrew formülüyle kurabilir, kaynağı depo üzerinden çalıştırabilirsin.'
        },
        {
          title: 'Mobil uygulama',
          body: 'Elyan Mobil yakında App Store ve Google Play’de. Hazır olduğunda gerçek mağaza bağlantıları burada yayınlanacak.'
        },
        {
          title: 'Gerçek sürüm disiplini',
          body: 'İmzalı sürüm paketleri hazır oldukça bu sayfa yalnızca gerçek platform bağlantılarını gösterir.'
        }
      ],
      ctas: [
        { href: 'https://raw.githubusercontent.com/emrek0ca/elyan/main/Formula/elyan.rb', label: 'Homebrew formülü' },
        { href: 'https://github.com/emrek0ca/elyan', label: 'Kaynak repo' }
      ]
    },
    privacy: {
      key: 'privacy',
      navLabel: 'Gizlilik',
      title: 'Gizlilik Politikası',
      description: 'Elyan kişisel verilerinizi nasıl işler ve korur.',
      eyebrow: 'Gizlilik ve Veri Güvenliği',
      intro:
        'Elyan, özel işleri cihazınızda tutan kişisel bir yapay zekâ asistanıdır. Bu politika hangi verileri neden işlediğimizi, hangi izinleri nasıl kullandığımızı, hesap silme ve destek yollarınızı açıklar. Yürürlük tarihi: 22 Haziran 2026.',
      sections: [],
      legal: [
        {
          title: '1. Kapsam ve İletişim',
          body: [
            'Bu politika Elyan web sitesi, Elyan Mobile, Elyan Desktop ve Elyan control-plane servisleri için geçerlidir.',
            'Gizlilik, hesap, veri erişimi, düzeltme, dışa aktarma veya silme talepleri için support@elyan.dev adresinden bize ulaşabilirsiniz.'
          ]
        },
        {
          title: '2. İşlediğimiz Veri Kategorileri',
          body: [
            'Hesap verileri: e-posta, kullanıcı kimliği, oturum bilgileri, kimlik doğrulama yöntemi ve güvenli hesap yönetimi için gereken kayıtlar.',
            'Cihaz ve eşleştirme verileri: eşleştirilen cihaz tanımlayıcıları, cihaz türü, bağlantı durumu, runtime readiness, son heartbeat zamanı ve güvenli görev yönlendirme için gereken teknik metadata.',
            'Görev ve sohbet verileri: kullanıcının yazdığı istemler, görev durumları, yanıtlar, artifact metadata\'sı, hata durumları ve sohbet devamlılığı için gereken sınırlı bağlam.',
            'Destek verileri: bize e-posta veya destek talebiyle gönderdiğiniz iletişim bilgileri, mesajlar ve sorunu çözmek için gerekli ek açıklamalar.',
            'Abonelik verileri: App Store veya Google Play üzerinden alınan abonelik durumları, plan bilgileri ve ödeme doğrulaması için gereken mağaza tarafından sağlanan işlem metadata\'sı. Tam kart bilgileri Elyan tarafından tutulmaz.'
          ]
        },
        {
          title: '3. İzinler, World Signals ve Hassas Bağlam',
          body: [
            'Elyan yalnızca kullanıcının etkinleştirdiği özellikler için izin ister. Takvim, saat, cihaz durumu, bildirimler, sağlık/aktivite sinyalleri veya benzer cihaz bağlamları izin verilmedikçe kullanılmaz.',
            'Bu sinyaller desteklendiğinde ham günlük veri yığını olarak değil, görev kalitesini artırmak için sınırlı ve özet bağlam paketleri halinde işlenir. Örneğin uyku, enerji, aktivite veya yoğunluk gibi üst seviye sinyaller sohbet bağlamına geçici destek sağlayabilir.',
            'Sağlık ve iyi oluş sinyalleri tıbbi tanı, tedavi, acil durum değerlendirmesi veya kalıcı sağlık profili oluşturmak için kullanılmaz. Elyan bir tıbbi hizmet veya acil yardım sistemi değildir.'
          ]
        },
        {
          title: '4. Local-First Mimari ve Dosya İşleme',
          body: [
            'Elyan Desktop özel dosyalar, yerel araçlar ve cihaz içi çalışma bağlamı için local-first sınırı korur. Yerel runtime, özel bilgisayar eylemlerini kullanıcının cihazında yürütür.',
            'Dosya, görsel, PDF, tablo veya belge eklediğinizde Elyan bunları yalnızca görevi yerine getirmek için işler. Bir dosyanın sunucuya gönderilmesi gerekiyorsa bu işlem açık görev bağlamıyla sınırlıdır; mümkün olan yerlerde özet, metadata veya işlenmiş paket kullanılır.',
            'Özel dosyalarınız reklam, profil çıkarma veya dış pazarlama amacıyla kullanılmaz.'
          ]
        },
        {
          title: '5. Elyan Zekâ Katmanı ve Güvenli Altyapı',
          body: [
            'Elyan; yanıt üretimi, görev yönlendirme, kimlik doğrulama, veri tabanı, bildirim ve güvenlik süreçlerini kendi zekâ katmanı ve güvenli işletim altyapısı içinde yönetir.',
            'Veri kullanımı, hizmetin çalışması için gereken en dar kapsamla sınırlıdır. Kişisel verileriniz reklam veya dış pazarlama amacıyla satılmaz.',
            'Elyan tek ürün kimliğiyle sunulur. Kullanıcı içerikleri, açık rıza veya hizmetin çalışması için gereken görev bağlamı dışında model geliştirme amacıyla kullanılmaz.'
          ]
        },
        {
          title: '6. Saklama, Hesap Silme ve Veri Hakları',
          body: [
            'Hesap verileri hesabınız aktif olduğu sürece veya yasal, güvenlik ya da faturalandırma yükümlülükleri gerektirdiği kadar saklanır. Geçici görev logları ve teknik hata kayıtları operasyonel ihtiyaç süresiyle sınırlı tutulur.',
            'Hesabınızı uygulama içindeki Ayarlar veya Hesap alanından silebilir ya da support@elyan.dev adresinden silme talebi gönderebilirsiniz. Silme akışı için ayrıca /tr/data-deletion sayfası yayınlanmıştır.',
            'Hesap silme sonrasında kimlik, sohbet geçmişi, eşleştirilmiş cihaz bağlantıları ve kullanıcıya bağlı görev kayıtları makul teknik süre içinde silinir veya anonimleştirilir. Yasal olarak tutulması gereken ödeme, güvenlik ve uyuşmazlık kayıtları gerekli süre boyunca saklanabilir.',
            'Verilerinize erişme, düzeltme, dışa aktarma, işlemeyi sınırlama veya silme talebi için support@elyan.dev adresine yazabilirsiniz.'
          ]
        },
        {
          title: '7. Güvenlik',
          body: [
            'Elyan; kimlik doğrulama, yetkilendirme, güvenli cihaz eşleştirme, oturum kontrolü ve erişim sınırlarıyla verilerinizi korumaya çalışır.',
            'Hiçbir internet hizmeti mutlak güvenlik garantisi veremez. Şüpheli erişim, güvenlik açığı veya hesabınızla ilgili olağan dışı etkinlik fark ederseniz support@elyan.dev adresine bildirin.'
          ]
        },
        {
          title: '8. Çocukların Gizliliği',
          body: [
            'Elyan 13 yaşından küçük çocuklara yönelik değildir. 13 yaşından küçük bir kullanıcıya ait kişisel verinin işlendiğini fark edersek, doğrulama sonrası ilgili verileri silmek için gerekli adımları atarız.'
          ]
        },
        {
          title: '9. Uluslararası Aktarım ve Politika Güncellemeleri',
          body: [
            'Elyan hizmetleri farklı bölgelerde çalışan güvenli altyapı bileşenleri üzerinden sunulabilir. Bu durumda veriler, hizmetin sağlanması ve güvenliği için gerekli koruma tedbirleriyle işlenir.',
            'Bu politikayı ürün, mevzuat veya mağaza gereklilikleri değiştikçe güncelleyebiliriz. Önemli değişiklikleri web sitesi, uygulama içi bildirim veya e-posta yoluyla duyurabiliriz.'
          ]
        }
      ],
      ctas: [
        { href: '/tr/support', label: 'Veri yönetimi ve destek' },
        { href: '/tr/data-deletion', label: 'Hesap ve veri silme' },
        { href: '/tr/terms', label: 'Kullanım Koşulları' }
      ]
    },
    terms: {
      key: 'terms',
      navLabel: 'Koşullar',
      title: 'Kullanım Koşulları',
      description: 'Elyan ürünlerinin kullanımı için temel hukuki koşullar ve yükümlülükler.',
      eyebrow: 'Hizmet Şartları',
      intro:
        'Bu koşullar Elyan web sitesi, Elyan Mobile, Elyan Desktop ve bağlı servislerin kullanımını düzenler. Elyan\'ı kullanarak bu koşulları ve gizlilik politikasını kabul etmiş olursunuz. Yürürlük tarihi: 22 Haziran 2026.',
      sections: [],
      legal: [
        {
          title: '1. Hizmetin Kapsamı',
          body: [
            'Elyan; mobil görev kontrolü, desktop local runtime, cihaz eşleştirme, task routing, zekâ destekli yanıt üretimi, belge/görsel işleme ve güvenli görev izleme özellikleri sunar.',
            'Mobil ve web yüzeyleri kontrol yüzeyidir. Özel yerel eylemler Elyan Desktop runtime sınırında veya açıkça etkinleştirilen sistem entegrasyonları üzerinden yürütülür.',
            'Bazı özellikler beta, sınırlı erişim veya platforma bağlı olabilir. Özelliklerin kesintisiz, hatasız veya her cihazda aynı şekilde çalışacağı garanti edilmez.'
          ]
        },
        {
          title: '2. Hesap, Cihaz ve İzin Sorumluluğu',
          body: [
            'Hesabınızın, oturumlarınızın ve eşleştirdiğiniz cihazların güvenliğinden siz sorumlusunuz. Yetkisiz erişim veya şüpheli işlem fark ederseniz support@elyan.dev adresine bildirmelisiniz.',
            'Cihaz izinleri yalnızca ilgili özelliği kullanmak için istenir. Takvim, bildirim, sağlık/aktivite, cihaz durumu, dosya erişimi veya benzer izinleri işletim sistemi ayarlarından kapatabilirsiniz.',
            'Başkasına ait hesap, cihaz, dosya, bildirim, takvim veya sağlık verisini yetkisiz biçimde kullanamazsınız.'
          ]
        },
        {
          title: '3. Kabul Edilebilir Kullanım',
          body: [
            'Elyan\'ı yasa dışı faaliyet, kötüye kullanım, zararlı otomasyon, yetkisiz erişim, kimlik avı, taciz, telif hakkı ihlali veya başkalarının gizlilik haklarını ihlal etmek için kullanamazsınız.',
            'Güvenlik sınırlarını aşmaya çalışmak, gizli anahtar veya kimlik bilgisi toplamaya çalışmak, sistemleri bozmak, yoğun istekle hizmeti aksatmak veya güvenlik kontrollerini devre dışı bırakmak yasaktır.',
            'Elyan, kötüye kullanım şüphesi olduğunda görevi reddedebilir, hesabı askıya alabilir veya gerekli güvenlik önlemlerini uygulayabilir.'
          ]
        },
        {
          title: '4. Elyan Çıktıları ve Profesyonel Danışmanlık',
          body: [
            'Elyan çıktıları eksik, hatalı, eski veya bağlama uygun olmayan bilgiler içerebilir. Kritik kararlar almadan önce çıktıları kontrol etmek kullanıcının sorumluluğundadır.',
            'Elyan tıbbi tanı, tedavi, hukuki danışmanlık, finansal yatırım tavsiyesi veya acil durum hizmeti sunmaz. Sağlık, hukuk, finans veya güvenlik açısından yüksek riskli konularda yetkili profesyonellerden destek alınmalıdır.',
            'Elyan\'ın görev planlaması ve otomasyon önerileri kullanıcı onayı, platform izinleri ve güvenlik politikalarıyla sınırlıdır.'
          ]
        },
        {
          title: '5. İçerik Sahipliği',
          body: [
            'Uygulamaya yüklediğiniz dosyalar, yazdığınız komutlar ve size ait içerikler size aittir.',
            'Elyan\'a, hizmeti sağlamak, güvenli biçimde işlemek, yanıt üretmek, senkronize etmek, hata ayıklamak ve destek vermek için gerekli sınırlı kullanım hakkını vermiş olursunuz.',
            'Elyan markası, logosu, tasarım sistemi, yazılımı, dokümantasyonu ve mimarisi Elyan geliştiricilerine aittir.'
          ]
        },
        {
          title: '6. Abonelikler, İptaller ve İadeler',
          body: [
            'Ücretli planlar App Store, Google Play veya desteklenen başka bir ödeme kanalı üzerinden sunulabilir. Mağaza üzerinden satın alınan abonelikler ilgili mağazanın abonelik, iptal ve iade kurallarına tabidir.',
            'Aboneliğinizi App Store veya Google Play hesabınızdan yönetebilir ve iptal edebilirsiniz. İptal sonrası erişim, ödenmiş dönem sonuna kadar devam edebilir.',
            'Fiyatlar, deneme süreleri ve plan kapsamları bölgeye ve platforma göre değişebilir.'
          ]
        },
        {
          title: '7. Hesap Silme ve Hizmetin Sona Ermesi',
          body: [
            'Hesabınızı uygulama içinden veya /tr/data-deletion sayfasındaki talimatları izleyerek silebilirsiniz.',
            'Koşulları ihlal eden, güvenliği riske atan veya yasa dışı kullanım içeren hesaplar askıya alınabilir ya da sonlandırılabilir.',
            'Hesap silme sonrası bazı kayıtlar yasal, güvenlik, faturalandırma veya uyuşmazlık gereklilikleri nedeniyle sınırlı süre saklanabilir.'
          ]
        },
        {
          title: '8. Sorumluluk Reddi ve Sınırlama',
          body: [
            'Elyan "olduğu gibi" ve "mevcut olduğu şekilde" sunulur. Kesintisiz erişim, hatasız çalışma, belirli bir sonucun elde edilmesi veya tüm çıktılarının doğru olması garanti edilmez.',
            'Yasaların izin verdiği en geniş ölçüde Elyan, dolaylı zararlar, veri kaybı, iş kaybı, kâr kaybı veya kullanıcı tarafından doğrulanmadan uygulanan çıktılardan doğan zararlardan sorumlu tutulamaz.'
          ]
        },
        {
          title: '9. Değişiklikler ve İletişim',
          body: [
            'Bu koşulları ürün, mevzuat veya mağaza gereklilikleri değiştikçe güncelleyebiliriz. Güncel sürüm her zaman bu sayfada yayınlanır.',
            'Sorularınız için support@elyan.dev adresinden bize ulaşabilirsiniz.'
          ]
        }
      ],
      ctas: [
        { href: '/tr/privacy', label: 'Gizlilik Politikası' },
        { href: '/tr/data-deletion', label: 'Hesap ve veri silme' },
        { href: '/tr/support', label: 'Destek ve İletişim' }
      ]
    },
    'data-deletion': {
      key: 'data-deletion',
      navLabel: 'Veri Silme',
      title: 'Hesap ve Veri Silme',
      description: 'Elyan hesabınızı, sohbet geçmişinizi ve ilişkili kişisel verilerinizi silme yolları.',
      eyebrow: 'Veri Hakları',
      intro:
        'Bu sayfa App Store ve Google Play veri silme gereklilikleri için açık bir başvuru noktasıdır. Elyan hesabınızı uygulama içinden silebilir veya destek ekibinden silme talebi oluşturabilirsiniz.',
      sections: [
        {
          title: 'Uygulama içinden silme',
          body: 'Elyan Mobile içinde Ayarlar veya Hesap bölümünü açın, Hesabımı Sil adımını seçin ve ekrandaki onayı tamamlayın. Bu işlem hesabınızla ilişkili oturumları, sohbet geçmişini, cihaz eşleştirmelerini ve kullanıcıya bağlı görev kayıtlarını silme sürecini başlatır.'
        },
        {
          title: 'E-posta ile silme talebi',
          body: 'Uygulamaya erişemiyorsanız support@elyan.dev adresine hesabınızla ilişkili e-posta adresinden yazın. Talebiniz doğrulandıktan sonra hesap ve kişisel veri silme süreci başlatılır.'
        },
        {
          title: 'Silinen ve saklanabilen veriler',
          body: 'Hesap bilgileri, sohbet geçmişi, cihaz bağlantıları ve kullanıcıya bağlı görev kayıtları silinir veya anonimleştirilir. Yasal, güvenlik, ödeme, sahtekarlık önleme veya uyuşmazlık çözümü için tutulması gereken sınırlı kayıtlar gerekli süre boyunca saklanabilir.'
        },
        {
          title: 'Abonelikleri ayrıca yönetin',
          body: 'Hesap silme, App Store veya Google Play aboneliğinizi otomatik olarak her durumda sonlandırmayabilir. Aktif aboneliğiniz varsa ilgili mağazanın abonelik yönetimi ekranından iptal işlemini ayrıca kontrol edin.'
        }
      ],
      ctas: [
        { href: 'mailto:support@elyan.dev?subject=Elyan%20Hesap%20ve%20Veri%20Silme%20Talebi', label: 'Silme talebi gönder' },
        { href: '/tr/privacy', label: 'Gizlilik Politikası' },
        { href: '/tr/support', label: 'Destek' }
      ]
    },
    support: {
      key: 'support',
      heroImage: '/hero_cafe.png',
      navLabel: 'Destek',
      title: 'Destek ve İletişim',
      description: 'Hesap, veri yönetimi, sorun giderme ve hesap silme yönlendirmesi.',
      eyebrow: 'Müşteri Desteği',
      intro:
        'Elyan kullanımıyla ilgili tüm sorularınız, teknik destek talepleriniz ve hesap yönetimi işlemleriniz için buradayız. Aşağıdaki adımları takip ederek sorunlarınıza çözüm bulabilir veya bizimle doğrudan iletişime geçebilirsiniz.',
      sections: [
        {
          title: 'Bize ulaşın',
          body: 'Hesap, oturum, cihaz eşleştirme, faturalandırma, abonelik, gizlilik veya güvenlik soruları için support@elyan.dev adresine yazabilirsiniz. Destek taleplerinde mümkünse hesabınızla ilişkili e-posta adresini ve sorunun kısa açıklamasını paylaşın.'
        },
        {
          title: 'Hesap ve veri silme',
          body: 'Hesabınızı uygulama içindeki Ayarlar veya Hesap bölümünden silebilirsiniz. Uygulamaya erişemiyorsanız /tr/data-deletion sayfasındaki talimatları izleyebilir ya da support@elyan.dev adresine silme talebi gönderebilirsiniz.'
        },
        {
          title: 'Cihaz eşleştirme ve görev akışı',
          body: 'Masaüstü ve mobil aynı hesapla giriş yapmalı, masaüstü uygulaması hazır görünmeli ve internet bağlantısı açık olmalıdır. QR eşleştirme, görev gönderme, durum izleme veya sonuç görüntüleme sorunlarında ekran görüntüsü ve hata zamanını destek talebine ekleyin.'
        },
        {
          title: 'Abonelik ve mağaza işlemleri',
          body: 'App Store veya Google Play üzerinden alınan abonelikler ilgili mağazanın abonelik yönetimi ekranından iptal edilir, yenilenir veya yönetilir. Elyan destek ekibi hesap durumunu inceleyebilir; mağaza tarafından işlenen ödeme yöntemlerini veya tam kart bilgilerini göremez.'
        },
        {
          title: 'Dosya, belge ve görsel işleme',
          body: 'PDF, belge, tablo veya görsel yanıtlarında eksik okuma, yanlış tablo çıkarımı ya da hatalı özet görürseniz dosya türünü, yaklaşık boyutu ve beklenen sonucu paylaşın. Özel veri içeren örnekleri göndermeden önce gereksiz kişisel alanları çıkarmanızı öneririz.'
        },
        {
          title: 'Güvenlik bildirimi',
          body: 'Hesabınızda yetkisiz erişim, şüpheli cihaz, veri sızıntısı şüphesi veya güvenlik açığı fark ederseniz support@elyan.dev adresine "Security" başlığıyla yazın. Güvenlik bildirimleri öncelikli değerlendirilir.'
        }
      ],
      ctas: [
        { href: 'mailto:support@elyan.dev', label: 'Bize E-posta Gönder' },
        { href: '/tr/data-deletion', label: 'Hesap ve veri silme' },
        { href: '/tr/privacy', label: 'Gizlilik Politikası' }
      ]
    },
    ai: {
      key: 'ai',
      heroImage: '/cozy_night.png',
      navLabel: 'Zekâ Bildirimi',
      title: 'Elyan Zekâ Bildirimi',
      description: 'Elyan zekâ katmanının çalışma sınırları, veri işleme yöntemi ve kullanıcı kontrolü hakkında açık bilgilendirme.',
      eyebrow: 'Elyan Zekâ Katmanı',
      intro:
        'Bu bildirim, Elyan içindeki zekâ destekli özelliklerin nasıl çalıştığını, verilerinizin görev bağlamında nasıl işlendiğini ve kullanıcı kontrolünün nerede durduğunu açıklar.',
      sections: [
        {
          title: '1. Rollerin dağılımı',
          body: 'Mobil uygulama ve web yüzeyi görev kontrol katmanıdır. Bir görev başlattığınızda Elyan isteği güvenli control-plane üzerinden uygun yürütme yoluna taşır; özel yerel eylemler desktop runtime sınırında kalır.'
        },
        {
          title: '2. İşlenen bağlam',
          body: 'İstemler, görev içerikleri, sohbet devamlılığı, ek dosya özetleri ve izin verilen cihaz bağlamları yanıt üretmek için işlenebilir. Elyan mümkün olduğunda ham veri yerine sınırlı, puanlanmış ve gizlilik kontrollü bağlam paketleri kullanır.'
        },
        {
          title: '3. Yerel çalışma alanı',
          body: 'Elyan Desktop özel dosyalar, yerel uygulamalar ve cihaz içi yetenekler için local-first sınırı korur. Kullanıcı onayı veya açık görev bağlamı olmadan özel yerel dosyalar otomatik olarak buluta taşınmaz.'
        },
        {
          title: '4. Eğitim ve kişisel içerik',
          body: 'Elyan kendi zekâ katmanıyla tek ürün kimliği olarak geliştirilir. Kişisel komutlarınız, özel konuşmalarınız veya yerel dosyalarınız açık rıza olmadan model geliştirme amacıyla kullanılmaz.'
        },
        {
          title: '5. Hata payı ve kullanıcı kontrolü',
          body: 'Elyan eksik, eski veya hatalı çıktı üretebilir. Kod, belge, sağlık, finans, hukuk, güvenlik veya cihaz eylemi gibi kritik sonuçlarda son kontrol kullanıcıya aittir. Elyan tıbbi tanı, hukuki danışmanlık veya finansal yatırım tavsiyesi sunmaz.'
        },
        {
          title: '6. Güvenli otomasyon sınırı',
          body: 'Dosya yazma, tarayıcı kontrolü, cihaz eylemleri, connector işlemleri veya dış sistemlerde yan etki oluşturabilecek görevler izin, güvenlik politikası ve görev izleriyle sınırlanır. Elyan gizli veya kullanıcı fark etmeden arka plan eylemi yürütmek için tasarlanmamıştır.'
        }
      ],
      ctas: [
        { href: '/tr/privacy', label: 'Gizlilik Politikası' },
        { href: '/tr/terms', label: 'Kullanım Koşulları' }
      ]
    }
  }
};

export default content;
