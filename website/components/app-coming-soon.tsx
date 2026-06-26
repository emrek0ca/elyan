import Link from 'next/link';

type AppComingSoonProps = {
  locale: string;
};

const copy = {
  tr: {
    eyebrow: 'Elyan App',
    title: 'Yakında',
    body: 'Web uygulama yüzeyi hazırlanıyor. Bu bölüm açılana kadar resmi bilgiler, destek ve yasal dokümanlar web sitesinde yayında kalacak.',
    home: 'Ana sayfa',
    support: 'Destek'
  },
  en: {
    eyebrow: 'Elyan App',
    title: 'Coming soon',
    body: 'The web app surface is being prepared. Until this area opens, official information, support, and legal documents remain available on the website.',
    home: 'Home',
    support: 'Support'
  }
} as const;

export function AppComingSoon({ locale }: AppComingSoonProps) {
  const language = locale === 'en' ? 'en' : 'tr';
  const text = copy[language];

  return (
    <main className="app-coming-soon" aria-labelledby="app-coming-soon-title">
      <div className="app-coming-soon__mark" aria-hidden="true">
        <img src="/brand/logo.png" alt="" />
      </div>
      <p className="app-coming-soon__eyebrow">{text.eyebrow}</p>
      <h1 id="app-coming-soon-title">{text.title}</h1>
      <p className="app-coming-soon__body">{text.body}</p>
      <div className="app-coming-soon__links">
        <Link href={`/${language}/`}>{text.home}</Link>
        <Link href={`/${language}/support/`}>{text.support}</Link>
      </div>
    </main>
  );
}
