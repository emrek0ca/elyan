import Link from 'next/link';

type AppComingSoonProps = {
  locale: string;
  type?: 'login' | 'dashboard';
};

const copy = {
  tr: {
    loginEyebrow: 'Hesap Bağlantısı',
    loginTitle: 'Güvenli Giriş',
    loginBody: 'Elyan hesabın, cihazlarını ve görev akışlarını güvenli şekilde bağlamak için kullanılır.',
    
    dashEyebrow: 'Çalışma Alanı',
    dashTitle: 'Sisteme Hoş Geldin',
    dashBody: 'Desktop runtime bağlandığında Elyan cihaz görevlerini güvenli şekilde yürütebilir.',
    dashTasks: [
      'Bir belgeyi özetle',
      'Bugünkü çalışma planımı çıkar',
      'Desktop runtime ile cihaz görevi başlat'
    ],

    defaultEyebrow: 'Elyan App',
    defaultTitle: 'Yakında',
    defaultBody: 'Web uygulama yüzeyi hazırlanıyor. Bu bölüm açılana kadar resmi bilgiler, destek ve yasal dokümanlar web sitesinde yayında kalacak.',
    
    home: 'Ana sayfa',
    support: 'Destek'
  },
  en: {
    loginEyebrow: 'Account Linking',
    loginTitle: 'Secure Login',
    loginBody: 'Your Elyan account is used to securely connect your devices and task workflows.',
    
    dashEyebrow: 'Workspace',
    dashTitle: 'Welcome to the System',
    dashBody: 'When the desktop runtime is connected, Elyan can safely execute device tasks.',
    dashTasks: [
      'Summarize a document',
      'Create my work plan for today',
      'Start a device task with desktop runtime'
    ],

    defaultEyebrow: 'Elyan App',
    defaultTitle: 'Coming soon',
    defaultBody: 'The web app surface is being prepared. Until this area opens, official information, support, and legal documents remain available on the website.',
    
    home: 'Home',
    support: 'Support'
  }
} as const;

export function AppComingSoon({ locale, type }: AppComingSoonProps) {
  const language = locale === 'en' ? 'en' : 'tr';
  const text = copy[language];

  let eyebrow: string = text.defaultEyebrow;
  let title: string = text.defaultTitle;
  let body: string = text.defaultBody;

  if (type === 'login') {
    eyebrow = text.loginEyebrow;
    title = text.loginTitle;
    body = text.loginBody;
  } else if (type === 'dashboard') {
    eyebrow = text.dashEyebrow;
    title = text.dashTitle;
    body = text.dashBody;
  }

  return (
    <main className="app-coming-soon" aria-labelledby="app-coming-soon-title">
      <div className="app-coming-soon__mark" aria-hidden="true">
        <img src="/brand/logo.png" alt="" />
      </div>
      <p className="app-coming-soon__eyebrow">{eyebrow}</p>
      <h1 id="app-coming-soon-title" className="mb-4">{title}</h1>
      <p className="app-coming-soon__body text-center">{body}</p>
      
      {type === 'dashboard' && (
        <div className="mt-8 flex flex-col gap-3 w-full max-w-md text-left">
          {text.dashTasks.map((task, i) => (
            <div key={i} className="surface-card !p-5 !rounded-xl !bg-[var(--surface-1)] text-[15px] font-medium text-[var(--text-muted)] hover:text-[var(--text)] transition-colors cursor-pointer border border-[var(--outline)] shadow-sm">
              <span className="opacity-50 mr-3">{i + 1}.</span> {task}
            </div>
          ))}
        </div>
      )}

      {type !== 'dashboard' && (
        <div className="app-coming-soon__links mt-8">
          <Link href={`/${language}/`}>{text.home}</Link>
          <Link href={`/${language}/support/`}>{text.support}</Link>
        </div>
      )}
      
      {type === 'dashboard' && (
        <div className="app-coming-soon__links mt-6">
          <Link href={`/${language}/`}>{text.home}</Link>
        </div>
      )}
    </main>
  );
}
