import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useScroll, useTransform } from "framer-motion";
import Lenis from "lenis";
import {
  ArrowRight,
  Check,
  ChevronRight,
  Command,
  Download,
  FileText,
  Globe2,
  Laptop,
  Menu,
  MessageSquareText,
  MonitorCog,
  Play,
  ShieldCheck,
  Sparkles,
  Smartphone,
  Terminal,
  X,
  Zap,
} from "lucide-react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import {
  AccountDeletionPage,
  AiDisclosurePage,
  PrivacyPage,
  SupportPage as LegalSupportPage,
  TermsPage,
} from "./LegalPages";
import {
  capabilityGroups,
  desktopDistribution,
  installRequirements,
} from "./productContent";


const APP_STORE_URL = "https://apps.apple.com/tr/app/elyan/id6779045459";
const INSTALL_COMMAND = "npm install -g elyan";

function SmoothScroll() {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const lenis = new Lenis({ autoRaf: true, lerp: 0.085, smoothWheel: true });
    return () => lenis.destroy();
  }, []);
  return null;
}

function EditorialImage({ src, alt, className, eager = false }: { src: string; alt: string; className: string; eager?: boolean }) {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end start"] });
  const y = useTransform(scrollYProgress, [0, 1], [-24, 24]);
  const scale = useTransform(scrollYProgress, [0, 0.5, 1], [1.035, 1, 1.035]);
  return <motion.figure ref={ref} className={className} initial={{ opacity: 0, y: 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: 0.16 }} transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}><motion.img src={src} alt={alt} width="1600" height="1067" loading={eager ? "eager" : "lazy"} style={{ y, scale }} /></motion.figure>;
}

type Feature = { icon: typeof Zap; title: string; text: string };

const features: Feature[] = [
  {
    icon: MessageSquareText,
    title: "Türkçe düşünen asistan",
    text: "Sor, yazdır, araştır, açıkla. Elyan doğal bir sohbetin içinden işi planlar.",
  },
  {
    icon: MonitorCog,
    title: "Bilgisayarda gerçek eylem",
    text: "Dosya, tarayıcı, belge, takvim ve uygulama görevleri eşleştirilmiş bilgisayarda yürür.",
  },
  {
    icon: FileText,
    title: "Üreten çalışma alanı",
    text: "Belge, PDF, tablo, grafik ve sunumları yalnızca anlatmaz; kullanılabilir çıktı üretir.",
  },
  {
    icon: ShieldCheck,
    title: "İzin sende",
    text: "Riskli adımlar başlamadan önce onay ister. Özel yerel bağlam varsayılan olarak cihazında kalır.",
  },
  {
    icon: Globe2,
    title: "Canlı web araştırması",
    text: "Güncel bilgi toplar, kaynakları bir araya getirir ve sonucu göreve dönüştürür.",
  },
  {
    icon: Zap,
    title: "Canlı görev takibi",
    text: "Telefondan başlat, adımları anlık izle, gerektiğinde onay ver ve çıktıyı cebinden al.",
  },
];

function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <Link className="brand" to="/" aria-label="Elyan ana sayfa">
      <img src="/logo.png" alt="" width="42" height="42" />
      {!compact && <span>elyan</span>}
    </Link>
  );
}

function Header() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);
  const nav = [
    ["/ozellikler", "Neler yapar"],
    ["/nasil-calisir", "Nasıl çalışır"],
    ["/indir", "İndir"],
    ["/fiyatlandirma", "Planlar"],
    ["/destek", "Destek"],
  ];
  return (
    <header className="site-header">
      <div className="nav-shell">
        <Logo />
        <nav className="desktop-nav" aria-label="Ana menü">
          {nav.map(([to, label]) => (
            <NavLink key={to} to={to}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="nav-actions">
          <a
            className="nav-store"
            href={APP_STORE_URL}
            target="_blank"
            rel="noreferrer"
          >
            iPhone için indir <ArrowRight size={15} />
          </a>
          <button
            className="menu-button"
            aria-label={open ? "Menüyü kapat" : "Menüyü aç"}
            onClick={() => setOpen(!open)}
          >
            {open ? <X /> : <Menu />}
          </button>
        </div>
      </div>
      <AnimatePresence>
        {open && (
          <motion.nav
            className="mobile-nav"
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            {nav.map(([to, label], i) => (
              <NavLink key={to} to={to}>
                <span>0{i + 1}</span>
                {label}
                <ChevronRight />
              </NavLink>
            ))}
            <a href={APP_STORE_URL} target="_blank" rel="noreferrer">
              App Store'da aç <ArrowRight />
            </a>
          </motion.nav>
        )}
      </AnimatePresence>
    </header>
  );
}

function CopyCommand({ command = INSTALL_COMMAND }: { command?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="terminal-command">
      <Terminal size={18} />
      <code>{command}</code>
      <button onClick={copy} aria-label="Komutu kopyala">
        {copied ? (
          <>
            <Check size={16} /> Kopyalandı
          </>
        ) : (
          "Kopyala"
        )}
      </button>
    </div>
  );
}

const reveal = {
  initial: { opacity: 0, y: 18 },
  whileInView: { opacity: 1, y: 0 },
  viewport: { once: true, amount: 0.2 },
  transition: {
    duration: 0.65,
    ease: [0.16, 1, 0.3, 1] as [number, number, number, number],
  },
};

function Home() {
  return (
    <main className="home-minimal">
      <section className="home-hero">
        <div className="home-hero-inner">
          <motion.div
            className="home-copy"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
          >
            <h1>
              Yapay zekâ,
              <br />
              <strong>işe dönüşsün.</strong>
            </h1>
            <p>
              Elyan araştırır, belge üretir ve izin verdiğin görevleri
              eşleştirilmiş bilgisayarında gerçekten yürütür.
            </p>
            <div className="home-actions">
              <a
                className="primary-button"
                href={APP_STORE_URL}
                target="_blank"
                rel="noreferrer"
              >
                <Smartphone size={18} /> App Store'dan indir
              </a>
              <Link className="home-secondary" to="/nasil-calisir">
                Nasıl çalışır? <ArrowRight size={17} />
              </Link>
            </div>
          </motion.div>
          <EditorialImage className="home-hero-media" src="/assets/editorial/home-flow.jpg" alt="Evinde bilgisayarını kullanırken telefonla konuşan bir kişi" eager />
        </div>
      </section>

      <section className="home-life section-shell">
        <EditorialImage className="home-life-photo" src="/assets/editorial/work-anywhere.jpg" alt="Açık havada dizüstü bilgisayar ve telefonla çalışan bir kişi" />
        <motion.div className="home-life-copy" {...reveal}>
          <h2>Sen devam et.<br />Elyan işi yürütür.</h2>
          <p>
            Araştırma, belge ve bilgisayar görevleri izin verdiğin sınırlar
            içinde ilerler. Süreci telefonundan görür, gerektiğinde onaylarsın.
          </p>
          <Link to="/ozellikler">
            Neler yapabildiğini gör <ArrowRight size={16} />
          </Link>
        </motion.div>
      </section>

      <section className="home-install section-shell">
        <motion.div {...reveal}>
          <h2>
            Tek komut.
            <br />
            Gerçek yerel eylem.
          </h2>
        </motion.div>
        <motion.div className="home-install-action" {...reveal}>
          <CopyCommand />
          <p>
            Ardından <code>elyan pair</code> ile telefonunu eşleştir.
          </p>
          <Link to="/indir">
            Tüm kurulum adımları <ArrowRight size={16} />
          </Link>
        </motion.div>
      </section>

      <section className="home-end">
        <img src="/logo.png" width="64" height="64" alt="Elyan" />
        <h2>Konuş. Onayla. Tamamlansın.</h2>
        <a
          className="primary-button"
          href={APP_STORE_URL}
          target="_blank"
          rel="noreferrer"
        >
          Elyan'ı indir <ArrowRight size={17} />
        </a>
      </section>
    </main>
  );
}

function PageHero({
  number,
  kicker,
  title,
  children,
  image,
}: {
  number: string;
  kicker: string;
  title: string;
  children: React.ReactNode;
  image?: { src: string; alt: string };
}) {
  return (
    <section className="page-hero section-shell">
      <motion.div className="page-hero-copy"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
      >
        <span className="section-number">
          {number} — {kicker}
        </span>
        <h1>{title}</h1>
        <div className="page-lead">{children}</div>
      </motion.div>
      {image && <EditorialImage className="page-hero-media" src={image.src} alt={image.alt} eager />}
    </section>
  );
}

function Features() {
  return (
    <main>
      <PageHero
        number="01"
        kicker="Neler yapar"
        title="Düşünceden çıktıya, tek konuşmada."
        image={{ src: "/assets/editorial/pages/features.jpg", alt: "Kütüphanede bilgisayarıyla çalışan bir öğrenci" }}
      >
        <p>
          Elyan’ın yetenekleri gösteri için değil; işi tamamlamak için aynı
          güvenli görev zincirinde birleşir.
        </p>
      </PageHero>
      <section className="section-shell deep-features">
        {features.map((f, i) => (
          <motion.article key={f.title} {...reveal}>
            <span>0{i + 1}</span>
            <f.icon />
            <div>
              <h2>{f.title}</h2>
              <p>{f.text}</p>
            </div>
          </motion.article>
        ))}
      </section>
      <section className="capability-catalog section-shell">
        <span className="section-number">Doğrulanmış yetenek kataloğu</span>
        {capabilityGroups.map((group, i) => (
          <article key={group.id}>
            <header>
              <span>0{i + 1}</span>
              <div>
                <h2>{group.title}</h2>
                <p>{group.summary}</p>
              </div>
            </header>
            <ul>
              {group.capabilities.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
        ))}
      </section>
      <UseCases />
      <FinalCta />
    </main>
  );
}

function HowItWorks() {
  const steps = [
    [
      "İste",
      "Mobil uygulamada Elyan’la konuş. Bir soru sorabilir veya bilgisayarında tamamlanacak bir görev verebilirsin.",
    ],
    [
      "Yönlendir",
      "Elyan kimliği, cihaz durumunu ve görev kapsamını güvenli kontrol düzleminde doğrular.",
    ],
    [
      "Onayla",
      "Dosya yazma, tarayıcı kontrolü veya dış servis eylemi gibi riskli adımlar senden açık izin ister.",
    ],
    [
      "Tamamla",
      "Yerel runtime işi bilgisayarında yürütür; adımlar ve artefaktlar mobil uygulamaya canlı döner.",
    ],
  ];
  return (
    <main>
      <PageHero
        number="02"
        kicker="Nasıl çalışır"
        title="Telefonunda başlar. Bilgisayarında biter."
        image={{ src: "/assets/editorial/pages/how-it-works.jpg", alt: "Birlikte bilgisayar başında çalışan insanlar" }}
      >
        <p>
          Özel yerel eylem buluta taşınmaz; mobil hiçbir zaman yerel motora
          doğrudan bağlanmaz.
        </p>
      </PageHero>
      <section className="section-shell timeline">
        {steps.map((s, i) => (
          <motion.article key={s[0]} {...reveal}>
            <span>0{i + 1}</span>
            <div>
              <h2>{s[0]}</h2>
              <p>{s[1]}</p>
            </div>
          </motion.article>
        ))}
      </section>
      <section className="architecture-note section-shell">
        <ShieldCheck />
        <div>
          <h2>Sınırlar güvenliğin parçası.</h2>
          <p>
            Mobil komuta ve takip yüzeyidir. Backend kimlik, abonelik,
            yönlendirme ve görev durumunu yönetir. Masaüstü runtime özel
            dosyalarla ve bilgisayar araçlarıyla yalnızca izin politikası
            üzerinden çalışır.
          </p>
        </div>
      </section>
      <FinalCta />
    </main>
  );
}

function DownloadPage() {
  return (
    <main>
      <PageHero
        number="03"
        kicker="İndir"
        title="Elyan, cebinde ve bilgisayarında."
        image={{ src: "/assets/editorial/pages/download.jpg", alt: "Telefon ve bilgisayarla çalışan bir kişi" }}
      >
        <p>
          Mobil uygulamayı iPhone’una indir; yerel CLI ve runtime motorunu
          bilgisayarına tek komutla kur.
        </p>
      </PageHero>
      <section className="section-shell download-split">
        <article className="download-mobile">
          <span>Mobil</span>
          <Smartphone />
          <h2>iPhone ve iPad</h2>
          <p>
            Sohbet et, bilgisayarını eşleştir, görevleri canlı izle ve gereken
            izinleri ver.
          </p>
          <a
            className="primary-button"
            href={APP_STORE_URL}
            target="_blank"
            rel="noreferrer"
          >
            <Download /> App Store'dan indir
          </a>
          <small>iOS ve iPadOS · Uygulama içi satın alımlar</small>
        </article>
        <article className="download-desktop">
          <span>CLI + yerel runtime</span>
          <Laptop />
          <h2>macOS · Windows · Linux</h2>
          <p>
            npm komutu native SwiftUI .app indirmez; Elyan CLI ve ortak Python
            runtime kaynaklarını kurar. Gereksinimler:{" "}
            {installRequirements
              .map((r) => `${r.name} ${r.version}`)
              .join(" · ")}
            .
          </p>
          <CopyCommand />
          <CopyCommand command="elyan pair" />
          <Link className="text-link" to="/destek">
            Kurulum rehberi <ArrowRight />
          </Link>
        </article>
      </section>
      <section className="section-shell requirements">
        <h2>Hızlı başlangıç</h2>
        <ol>
          <li>
            <b>Node.js 18+</b>
            <span>npm üzerinden Elyan CLI paketini kurmak için gerekir.</span>
          </li>
          <li>
            <b>Python 3.10+</b>
            <span>Yerel Elyan runtime motorunu çalıştırır.</span>
          </li>
          <li>
            <b>{INSTALL_COMMAND}</b>
            <span>
              Yayınlanan npm sürümü CLI ve runtime kaynaklarını kurar. Kaynak
              ağacı manifest sürümü {desktopDistribution.npm.manifestVersion}{" "}
              olabilir; registry sürümü yayın takvimine göre farklı olabilir.
            </span>
          </li>
          <li>
            <b>elyan pair</b>
            <span>
              Terminaldeki QR kodunu mobil uygulamada Eşleştir ekranıyla okut.
            </span>
          </li>
          <li>
            <b>elyan service install</b>
            <span>
              İstersen Elyan’ı bilgisayar açıldığında güvenli biçimde başlatır.
            </span>
          </li>
        </ol>
      </section>
    </main>
  );
}

function Pricing() {
  const plans = [
    ["Free", "Başlamak için", "Mobil sohbet ve temel kullanım", "Ücretsiz"],
    [
      "Solo",
      "Kişisel üretkenlik",
      "Daha yüksek kullanım ve kişisel iş akışları",
      "Uygulamada gör",
    ],
    [
      "Pro",
      "Yoğun çalışma",
      "Gelişmiş kullanım, cihaz ve üretim kapasitesi",
      "Uygulamada gör",
    ],
  ];
  return (
    <main>
      <PageHero number="04" kicker="Planlar" title="İhtiyacın kadar Elyan." image={{ src: "/assets/editorial/pages/pricing.jpg", alt: "Evde bilgisayarıyla çalışan bir kişi" }}>
        <p>
          Güncel fiyat ve mağaza teklifleri App Store’daki bölgen ve hesabına
          göre gösterilir.
        </p>
      </PageHero>
      <section className="section-shell pricing-list">
        {plans.map((p, i) => (
          <motion.article key={p[0]} {...reveal}>
            <span>0{i + 1}</span>
            <div>
              <small>{p[1]}</small>
              <h2>{p[0]}</h2>
              <p>{p[2]}</p>
            </div>
            <strong>{p[3]}</strong>
            <a
              href={APP_STORE_URL}
              target="_blank"
              rel="noreferrer"
              aria-label={`${p[0]} planını App Store'da gör`}
            >
              <ArrowRight />
            </a>
          </motion.article>
        ))}
      </section>
      <p className="pricing-note section-shell">
        Abonelik satın alma ve geri yükleme iOS’ta App Store üzerinden
        yönetilir. Website üzerinden ödeme alınmaz.
      </p>
    </main>
  );
}

function UseCases() {
  return (
    <section className="use-cases">
      <div className="section-shell">
        <span className="section-number">Kullanım örnekleri</span>
        <div className="quote-flow">
          <blockquote>
            “Bu sözleşmeyi özetle, kritik maddeleri çıkar.”
          </blockquote>
          <blockquote>
            “Bu verilerden bir grafik ve PDF rapor oluştur.”
          </blockquote>
          <blockquote>“Yarın 14.00’e toplantı ekle.”</blockquote>
          <blockquote>“Konuyu araştır ve sunum hazırla.”</blockquote>
        </div>
      </div>
    </section>
  );
}

function Support() {
  return (
    <main>
      <PageHero number="05" kicker="Destek" title="Kur, eşleştir, çalıştır." image={{ src: "/assets/editorial/pages/support.jpg", alt: "Bilgisayar başında birlikte çalışan insanlar" }}>
        <p>En kısa çözüm yolları ve Elyan desktop komutları.</p>
      </PageHero>
      <section className="section-shell support-grid">
        <div>
          <h2>Desktop komutları</h2>
          <dl>
            <dt>
              <code>elyan pair</code>
            </dt>
            <dd>Telefonla QR eşleştirmesi başlatır.</dd>
            <dt>
              <code>elyan status</code>
            </dt>
            <dd>Bağlantı, cihaz ve görev durumunu gösterir.</dd>
            <dt>
              <code>elyan doctor</code>
            </dt>
            <dd>Python ve gerekli bağımlılıkları kontrol eder.</dd>
            <dt>
              <code>elyan restart</code>
            </dt>
            <dd>Arka plan runtime’ını güvenli biçimde yeniden başlatır.</dd>
          </dl>
        </div>
        <div>
          <h2>Sık sorulanlar</h2>
          <details>
            <summary>Elyan bilgisayarımda neye erişir?</summary>
            <p>
              Yalnızca verdiğin görev ve izin politikası kapsamındaki araçlara.
              Dosya yazma, tarayıcı veya bilgisayar kontrolü gibi işlemler izin
              gerektirir.
            </p>
          </details>
          <details>
            <summary>Bilgisayarım kapalıysa ne olur?</summary>
            <p>
              Mobilde sohbet etmeye devam edebilirsin; yerel bilgisayar
              gerektiren görevler runtime hazır olduğunda yürütülür.
            </p>
          </details>
          <details>
            <summary>Kurulum çalışmazsa?</summary>
            <p>
              <code>elyan doctor</code> komutunu çalıştır. Node.js 18+ ve Python
              3.10+ kurulumunu doğrula, ardından{" "}
              <code>npm install -g elyan</code> komutunu yeniden çalıştır.
            </p>
          </details>
          <details>
            <summary>Aboneliğimi nereden yönetirim?</summary>
            <p>
              iPhone Ayarlar → Apple Hesabı → Abonelikler bölümünden veya App
              Store hesap sayfasından.
            </p>
          </details>
          <a className="primary-button" href="mailto:destek@elyan.dev">
            destek@elyan.dev
          </a>
        </div>
      </section>
    </main>
  );
}

function Legal({ type }: { type: "privacy" | "terms" }) {
  const privacy = type === "privacy";
  return (
    <main>
      <PageHero
        number="06"
        kicker={privacy ? "Gizlilik" : "Koşullar"}
        title={
          privacy
            ? "Önce yerel. Her zaman kontrollü."
            : "Açık ve güvenli kullanım."
        }
      >
        <p>Son güncelleme: 15 Temmuz 2026</p>
      </PageHero>
      <article className="legal section-shell">
        {privacy ? (
          <>
            <h2>Gizlilik yaklaşımı</h2>
            <p>
              Elyan yerel-öncelikli bir yapay zekâ ajan sistemidir. Özel
              bilgisayar eylemleri masaüstü runtime’ında yürütülür. Özel yerel
              dosyalar ve bağlam, sen açıkça izin vermedikçe kontrol düzlemine
              gönderilmez.
            </p>
            <h2>İşlenen veriler</h2>
            <p>
              Hesap ve kimlik verileri; cihaz eşleştirme bilgileri; abonelik ve
              kullanım kayıtları; görev yönlendirme ve durum metadatası;
              güvenlik ve hata teşhisi için sınırlı teknik telemetri
              işlenebilir. Özel prompt veya dosya içerikleri varsayılan olarak
              loglanmaz.
            </p>
            <h2>İzinler</h2>
            <p>
              Dosya yazma, belge dışa aktarma, tarayıcı/bilgisayar kontrolü,
              otomasyon oluşturma ve yan etkili dış servis çağrıları açık izin
              gerektirir. İzni reddettiğinde görev güvenli biçimde durur.
            </p>
            <h2>Saklama ve silme</h2>
            <p>
              Uygulama içindeki hesap ve geçmiş yönetimi araçlarını kullanabilir
              veya destek adresine ulaşabilirsin. Yasal zorunluluklar dışında
              silme talepleri uygulanır.
            </p>
            <h2>İletişim</h2>
            <p>
              Gizlilik soruları için{" "}
              <a href="mailto:destek@elyan.dev">destek@elyan.dev</a>.
            </p>
          </>
        ) : (
          <>
            <h2>Hizmetin kapsamı</h2>
            <p>
              Elyan, mobil uygulama, kontrol düzlemi ve bilgisayarındaki yerel
              runtime’dan oluşan bir yapay zekâ ajan sistemidir. Sonuçları
              kullanmadan önce özellikle hukuki, finansal, tıbbi ve kritik
              işlerde doğrulama sorumluluğu kullanıcıdadır.
            </p>
            <h2>Güvenli kullanım</h2>
            <p>
              Hizmeti yetkisiz erişim, zararlı yazılım, dolandırıcılık, hak
              ihlali veya yasadışı otomasyon için kullanamazsın. Riskli eylemler
              izin politikasına tabidir.
            </p>
            <h2>Abonelikler</h2>
            <p>
              iOS abonelikleri Apple tarafından işlenir ve App Store koşullarına
              tabidir. Fiyat, deneme ve yenileme bilgileri satın alma ekranında
              gösterilen güncel mağaza verisidir.
            </p>
            <h2>Erişilebilirlik ve değişiklikler</h2>
            <p>
              Hizmet bakım, güvenlik veya bağımlılık sorunlarında geçici olarak
              kısıtlanabilir. Önemli koşul değişiklikleri uygun kanallardan
              duyurulur.
            </p>
            <h2>İletişim</h2>
            <p>
              Koşullarla ilgili sorular için{" "}
              <a href="mailto:destek@elyan.dev">destek@elyan.dev</a>.
            </p>
          </>
        )}
      </article>
    </main>
  );
}

function FinalCta() {
  return (
    <section className="final-cta">
      <div className="section-shell">
        <motion.img
          {...reveal}
          src="/logo.png"
          width="100"
          height="100"
          alt="Elyan"
        />
        <motion.div {...reveal}>
          <span className="section-number">Başlamaya hazır</span>
          <h2>
            Telefonun cebinde.
            <br />
            Bilgisayarın iş başında.
          </h2>
          <a
            className="primary-button light"
            href={APP_STORE_URL}
            target="_blank"
            rel="noreferrer"
          >
            <Sparkles /> Elyan’ı indir
          </a>
        </motion.div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer>
      <div className="section-shell footer-grid">
        <Logo />
        <p>
          Telefonundan konuş.
          <br />
          Bilgisayarın işi yapsın.
        </p>
        <nav>
          <Link to="/ozellikler">Özellikler</Link>
          <Link to="/nasil-calisir">Nasıl çalışır</Link>
          <Link to="/indir">İndir</Link>
          <Link to="/fiyatlandirma">Planlar</Link>
        </nav>
        <nav>
          <Link to="/destek">Destek</Link>
          <Link to="/gizlilik">Gizlilik</Link>
          <Link to="/kosullar">Kullanım koşulları</Link>
          <a href={APP_STORE_URL} target="_blank" rel="noreferrer">
            App Store
          </a>
        </nav>
      </div>
      <div className="section-shell copyright">
        <span>© 2026 Elyan</span>
        <span>Yerel-öncelikli yapay zekâ ajanı</span>
      </div>
    </footer>
  );
}

function ScrollTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

function SiteMeta() {
  const { pathname } = useLocation();
  useEffect(() => {
    const titles: Record<string, string> = {
      "/": "Elyan — Bilgisayarını kullanan yapay zekâ",
      "/ozellikler": "Elyan özellikleri",
      "/nasil-calisir": "Elyan nasıl çalışır?",
      "/indir": "Elyan’ı indir",
      "/fiyatlandirma": "Elyan planları",
      "/pricing": "Elyan planları",
      "/destek": "Elyan destek",
      "/support": "Elyan destek",
      "/gizlilik": "Elyan gizlilik politikası",
      "/privacy": "Elyan gizlilik politikası",
      "/kosullar": "Elyan kullanım koşulları",
      "/terms": "Elyan kullanım koşulları",
      "/ai": "Elyan yapay zekâ bildirimi",
      "/yapay-zeka-bildirimi": "Elyan yapay zekâ bildirimi",
    };
    document.title = titles[pathname] ?? "Sayfa bulunamadı — Elyan";
  }, [pathname]);
  return null;
}

function NotFound() {
  return (
    <main>
      <PageHero number="404" kicker="Bulunamadı" title="Bu sayfa burada değil.">
        <p>Bağlantı değişmiş veya adres yanlış yazılmış olabilir.</p>
        <Link className="primary-button" to="/">
          Ana sayfaya dön
        </Link>
      </PageHero>
    </main>
  );
}

export default function App() {
  return (
    <>
      <ScrollTop />
      <SmoothScroll />
      <SiteMeta />
      <Header />
      <AnimatePresence mode="wait">
        <motion.div
          key={location.pathname}
          initial={{ opacity: 0, rotateX: 1.5 }}
          animate={{ opacity: 1, rotateX: 0 }}
          exit={{ opacity: 0, rotateX: -1.5 }}
          transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
        >
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/ozellikler" element={<Features />} />
            <Route path="/nasil-calisir" element={<HowItWorks />} />
            <Route path="/indir" element={<DownloadPage />} />
            <Route path="/fiyatlandirma" element={<Pricing />} />
            <Route path="/pricing" element={<Pricing />} />
            <Route path="/destek" element={<Support />} />
            <Route path="/support" element={<LegalSupportPage />} />
            <Route path="/gizlilik" element={<PrivacyPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
            <Route path="/kosullar" element={<TermsPage />} />
            <Route path="/terms" element={<TermsPage />} />
            <Route path="/kullanim-kosullari" element={<TermsPage />} />
            <Route path="/ai" element={<AiDisclosurePage />} />
            <Route
              path="/yapay-zeka-bildirimi"
              element={<AiDisclosurePage />}
            />
            <Route path="/account-deletion" element={<AccountDeletionPage />} />
            <Route path="/delete-account" element={<AccountDeletionPage />} />
            <Route path="/hesap-silme" element={<AccountDeletionPage />} />
            <Route path="/data-deletion" element={<AccountDeletionPage />} />
            <Route path="/veri-silme" element={<AccountDeletionPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </motion.div>
      </AnimatePresence>
      <Footer />
    </>
  );
}
