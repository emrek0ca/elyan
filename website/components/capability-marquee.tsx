import type { SiteLocale } from '@/lib/locales';

const ITEMS: Record<SiteLocale, string[]> = {
  tr: [
    'PDF oluştur',
    'Klasör aç',
    'Toplantı ekle',
    'Web’de araştır',
    'Belge özetle',
    'Tablo & grafik',
    'E-posta yaz',
    'Sunum hazırla',
    'Dosya düzenle',
    'Takvimi yönet'
  ],
  en: [
    'Create PDFs',
    'Open folders',
    'Add meetings',
    'Research the web',
    'Summarize docs',
    'Tables & charts',
    'Write emails',
    'Build decks',
    'Organize files',
    'Manage calendar'
  ]
};

export function CapabilityMarquee({ locale }: { locale: SiteLocale }) {
  const items = ITEMS[locale] ?? ITEMS.tr;
  const rowA = [...items, ...items];
  const rowB = [...items.slice().reverse(), ...items.slice().reverse()];

  return (
    <div className="marquee" aria-hidden="true">
      <div className="marquee__track marquee__track--a">
        {rowA.map((label, index) => (
          <span className="marquee__pill" key={`a-${index}`}>
            <i className="marquee__dot" />
            {label}
          </span>
        ))}
      </div>
      <div className="marquee__track marquee__track--b">
        {rowB.map((label, index) => (
          <span className="marquee__pill" key={`b-${index}`}>
            <i className="marquee__dot" />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}
