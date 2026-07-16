export type CapabilityGroup = {
  id: string;
  title: string;
  summary: string;
  capabilities: readonly string[];
};

export type ArchitectureStep = {
  id: string;
  title: string;
  description: string;
  ownership: "mobile" | "backend" | "desktop";
};

export type InstallStep = {
  id: string;
  title: string;
  command?: string;
  description: string;
};

export const productIdentity = {
  name: "Elyan",
  positioning: "Bilgisayarını kullanan yapay zekâ",
  shortDescription:
    "Telefonundan konuş, eşleştirdiğin bilgisayar senin için işi yapsın.",
  appStoreUrl: "https://apps.apple.com/tr/app/elyan/id6779045459",
  supportEmail: "destek@elyan.dev",
} as const;

export const capabilityGroups: readonly CapabilityGroup[] = [
  {
    id: "research-docs",
    title: "Araştırma ve üretim",
    summary:
      "Web ve yerel kaynakları araştırır; belge, tablo, sunum, grafik ve görsel çıktılar üretir.",
    capabilities: [
      "Web araştırması",
      "Bağlam ve bilgi getirme",
      "Belge ve PDF okuma",
      "OCR ile metin çıkarma",
      "Görsel okuma ve görsel bulma",
      "Belge yazma",
      "Elektronik tablo yazma",
      "Sunum hazırlama",
      "Tuval çıktısı oluşturma",
      "Veri analizi ve grafik üretme",
      "Görsel üretme",
    ],
  },
  {
    id: "computer-control",
    title: "Bilgisayarda gerçek iş",
    summary:
      "İzin verilen görevleri eşleştirilmiş bilgisayarda, görev kimliği ve güvenlik politikasıyla yürütür.",
    capabilities: [
      "Uygulama açma ve kapatma",
      "Ekranı gözlemleme ve analiz etme",
      "Pencere bulma ve odaklama",
      "Fare, klavye ve kısayol eylemleri",
      "Tarayıcı kontrolü",
      "Sistem, süreç ve aktif pencere bilgisi",
      "İşletim sistemi izinlerini denetleme",
      "Görev iptali",
      "Medya oynatma",
      "İzinli komut çalıştırma",
    ],
  },
  {
    id: "developer",
    title: "Dosya ve geliştirme işleri",
    summary:
      "Çalışma alanındaki dosya ve Git işlemlerini güvenli, izlenebilir adımlarla gerçekleştirir.",
    capabilities: [
      "Dosya ve klasör arama",
      "Klasör ağacı çıkarma",
      "Dosya okuma, yazma ve yama uygulama",
      "Git durumu ve farklarını inceleme",
      "Dal oluşturma ve commit hazırlama",
    ],
  },
  {
    id: "communication",
    title: "İletişim ve günlük işler",
    summary:
      "Takvim, hatırlatıcı ve iletişim eylemlerini açık onay gerektiren sınırlar içinde yönetir.",
    capabilities: [
      "Takvim etkinliklerini görme, ekleme ve silme",
      "Hatırlatıcıları görme ve ekleme",
      "E-posta taslağı hazırlama ve onayla gönderme",
      "WhatsApp mesajı gönderme ve kişi kaydetme",
      "Hava durumu bilgisi",
      "MCP araçlarını ve Elyan becerilerini çalıştırma",
    ],
  },
  {
    id: "speech-math-quantum",
    title: "Ses, matematik ve kuantum",
    summary:
      "Konuşma giriş/çıkışı, sembolik hesaplama ve kuantum deney iş akışlarını aynı görev sisteminde birleştirir.",
    capabilities: [
      "Ses yakalama ve konuşmayı metne çevirme",
      "Metni sese çevirme",
      "Matematik çözme ve LaTeX ayrıştırma",
      "Kuantum problemi modelleme",
      "Kuantum deneyi çalıştırma",
      "Klasik yöntemle karşılaştırma ve rapor üretme",
    ],
  },
  {
    id: "memory-safety",
    title: "Hafıza, güvenlik ve kontrol",
    summary:
      "Öğrenilen bilgileri yönetir; yan etkili veya özel işlemleri varsayılan olarak sınırlar.",
    capabilities: [
      "Kullanıcı onayıyla hafıza kaydetme ve silme",
      "Riskli adımlarda onay bekleme",
      "Görev durumunu ve artefaktları canlı raporlama",
      "Bağımlılık yokluğunda güvenli biçimde düşürülmüş çalışma",
      "Zaman aşımı ve iptal desteği",
      "Özel yerel veriyi bilgisayarda tutma",
    ],
  },
] as const;

export const architectureSteps: readonly ArchitectureStep[] = [
  {
    id: "mobile-command",
    title: "Telefondan iste",
    description:
      "Elyan Mobile sohbeti, oturumları, eşleştirmeyi, görev durumunu ve gerekli onayları gösterir; tam yerel runtime çalıştırmaz.",
    ownership: "mobile",
  },
  {
    id: "control-plane",
    title: "Kontrol düzlemi yönlendirsin",
    description:
      "Backend kimlik, abonelik, cihazlar, kota, görev yönlendirme, gerçek zamanlı durum ve orkestrasyon metadatasının kaynağıdır.",
    ownership: "backend",
  },
  {
    id: "local-runtime",
    title: "Bilgisayar yerelde yürütsün",
    description:
      "Ortak Python runtime görevi capability registry, güvenlik politikası ve adapter katmanından geçirerek macOS, Windows veya Linux bilgisayarda çalıştırır.",
    ownership: "desktop",
  },
  {
    id: "structured-result",
    title: "Sonuç geri dönsün",
    description:
      "Yapılandırılmış durum, olay, güvenli hata ve artefaktlar backend üzerinden mobil sohbet yüzeyine geri raporlanır.",
    ownership: "desktop",
  },
] as const;

export const installRequirements = [
  {
    name: "Node.js",
    version: "18 veya üzeri",
    reason: "npm üzerinden Elyan CLI paketini kurmak için gerekir.",
  },
  {
    name: "Python",
    version: "3.10 veya üzeri",
    reason: "Elyan masaüstü runtime motorunu çalıştırmak için gerekir.",
  },
  {
    name: "Elyan Mobile",
    version: "iOS uygulaması",
    reason:
      "QR eşleştirme, görev gönderme, canlı takip ve onaylar için gerekir.",
  },
] as const;

export const npmInstallSteps: readonly InstallStep[] = [
  {
    id: "install",
    title: "CLI ve runtime paketini kur",
    command: "npm install -g elyan",
    description:
      "Global Elyan komutunu ve paketlenmiş Python runtime kaynaklarını kurar.",
  },
  {
    id: "launch",
    title: "Elyan’ı başlat",
    command: "elyan",
    description:
      "Kurulum ve bağımlılık durumunu denetleyen CLI giriş noktasını çalıştırır.",
  },
  {
    id: "pair",
    title: "Telefonunu eşleştir",
    command: "elyan pair",
    description:
      "Terminaldeki QR kodunu Elyan Mobile’ın eşleştirme ekranıyla okutursun.",
  },
  {
    id: "service",
    title: "Arka planda başlat",
    command: "elyan service install",
    description:
      "İsteğe bağlı olarak runtime’ı sistem açılışında başlatacak hizmeti kurar.",
  },
] as const;

export const alternateInstall = {
  command: "curl -fsSL https://elyan.dev/install.sh | bash",
  platforms: ["macOS", "Linux"],
  description:
    "Kaynak tabanlı kurulum betiği Python 3.10+ kontrolü yapar, sanal ortamı hazırlar, bağımlılıkları kurar ve elyan komutunu ~/.local/bin altında bağlar.",
} as const;

export const desktopDistribution = {
  npm: {
    kind: "CLI + Python runtime",
    packageName: "elyan",
    manifestVersion: "1.6.0",
    command: "npm install -g elyan",
    note: "1.6.0 sürümü bu kaynak ağacındaki package.json manifest değeridir; bu içerik npm registry yayın durumunu ayrıca doğrulanmış saymaz.",
  },
  nativeMacApp: {
    kind: "Native macOS application",
    stack: "SwiftUI + RuntimeBridgeSwift + PythonRuntimeSupervisor",
    note: "Native macOS uygulaması npm paketinden farklı bir dağıtım yüzeyidir. npm komutu native .app paketi indirdiği iddiasında bulunmaz.",
  },
  sharedRuntime: {
    kind: "Common local engine",
    stack: "Python runtime",
    platforms: ["macOS", "Windows", "Linux"],
  },
} as const;

export const mobileRoutes = [
  { path: "/splash", purpose: "Açılış ve oturum çözümleme" },
  { path: "/login", purpose: "Giriş" },
  { path: "/register", purpose: "Kayıt" },
  { path: "/pair", purpose: "Bilgisayar eşleştirme" },
  { path: "/task", purpose: "Ana sohbet ve görev yüzeyi" },
  { path: "/settings", purpose: "Ayarlar, hesap ve cihaz yönetimi" },
  { path: "/settings/billing", purpose: "Plan ve abonelik yönetimi" },
] as const;

export const websitePages = [
  { path: "/", title: "Ana sayfa", purpose: "Ürün vaadi ve temel yönlendirme" },
  {
    path: "/ozellikler",
    title: "Özellikler",
    purpose: "Doğrulanmış yetenekler",
  },
  {
    path: "/nasil-calisir",
    title: "Nasıl çalışır",
    purpose: "Mobil, backend ve desktop akışı",
  },
  {
    path: "/indir",
    title: "İndir",
    purpose: "App Store ve masaüstü runtime kurulumu",
  },
  {
    path: "/fiyatlandirma",
    title: "Planlar",
    purpose: "Planları mağazadaki güncel tekliflere yönlendirme",
  },
  {
    path: "/destek",
    title: "Destek",
    purpose: "Kurulum, eşleştirme ve CLI komutları",
  },
  {
    path: "/gizlilik",
    title: "Gizlilik",
    purpose: "Yerel-öncelikli veri ve izin yaklaşımı",
  },
  {
    path: "/kosullar",
    title: "Kullanım koşulları",
    purpose: "Hizmet ve güvenli kullanım kapsamı",
  },
] as const;

export const cliCommands = [
  { command: "elyan pair", description: "QR ile mobil uygulamaya bağlar." },
  { command: "elyan login", description: "E-posta ve şifreyle giriş yapar." },
  { command: "elyan start", description: "Arka plan runtime’ını başlatır." },
  { command: "elyan stop", description: "Arka plan runtime’ını durdurur." },
  {
    command: "elyan restart",
    description: "Arka plan runtime’ını yeniden başlatır.",
  },
  {
    command: "elyan status",
    description: "Bağlantı, eşleştirme ve görev durumunu gösterir.",
  },
  { command: "elyan tasks", description: "Son görevleri listeler." },
  {
    command: "elyan doctor",
    description: "Kurulum ve bağımlılık sağlığını denetler.",
  },
  {
    command: "elyan service install",
    description: "Sistem açılışında çalışacak hizmeti kurar.",
  },
  {
    command: "elyan run",
    description: "Runtime’ı hata ayıklama için ön planda çalıştırır.",
  },
] as const;
