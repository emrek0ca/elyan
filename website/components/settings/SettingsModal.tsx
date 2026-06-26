"use client";

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { usePreferences, ThemeMode, TextScale, InterfaceDensity } from '@/lib/preferences-context';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  user: any;
  onLogout: () => void;
  onClearChats: () => void;
}

type Tab = 'account' | 'appearance' | 'chat' | 'legal';

export function SettingsModal({ isOpen, onClose, user, onLogout, onClearChats }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<Tab>('account');
  const prefs = usePreferences();
  const [profileData, setProfileData] = useState<any>(user);
  const params = useParams();
  const locale = (params?.locale as string) || 'tr';

  useEffect(() => {
    if (isOpen) {
      setProfileData(user);
      import('@/lib/api-client').then(({ apiFetch }) => {
        apiFetch('/v1/auth/me').then(data => {
          if (data && data.user) setProfileData(data.user);
          else if (data) setProfileData(data);
        }).catch(() => null);
      });
    }
  }, [isOpen, user]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 md:p-6 bg-[var(--text)]/40 backdrop-blur-sm animate-in fade-in duration-200">
      {/* Background click area to close */}
      <div className="absolute inset-0" onClick={onClose} />

      <div className="relative flex flex-col md:flex-row w-full max-w-4xl max-h-full md:h-[600px] bg-[var(--background-deep)] rounded-2xl md:rounded-3xl overflow-hidden shadow-[0_20px_60px_rgba(0,0,0,0.1)] animate-in zoom-in-95 duration-200 border border-[var(--outline)]">
        
        {/* Mobile Header */}
        <div className="md:hidden flex items-center justify-between p-4 border-b border-[var(--outline)] bg-[var(--background)]">
          <h2 className="font-semibold text-lg">Ayarlar</h2>
          <button onClick={onClose} className="p-2 bg-[var(--text)]/5 rounded-full hover:bg-[var(--text)]/10">
            <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
        </div>

        {/* Sidebar */}
        <div className="w-full md:w-64 bg-[var(--background)] border-b md:border-b-0 md:border-r border-[var(--outline)] flex flex-row md:flex-col overflow-x-auto md:overflow-y-auto shrink-0 p-2 md:p-4 gap-1 hide-scrollbar">
          <div className="hidden md:flex items-center justify-between px-2 mb-6 mt-2">
            <h2 className="font-semibold text-xl tracking-tight">Ayarlar</h2>
          </div>
          
          <TabButton id="account" current={activeTab} onClick={() => setActiveTab('account')} icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>}>
            Hesap
          </TabButton>
          <TabButton id="appearance" current={activeTab} onClick={() => setActiveTab('appearance')} icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>}>
            Görünüm
          </TabButton>
          <TabButton id="chat" current={activeTab} onClick={() => setActiveTab('chat')} icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>}>
            Sohbet
          </TabButton>
          <TabButton id="legal" current={activeTab} onClick={() => setActiveTab('legal')} icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>}>
            Yasal
          </TabButton>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto p-4 md:p-8 bg-[var(--background-deep)] relative">
          
          <button onClick={onClose} className="hidden md:flex absolute top-6 right-6 p-2 bg-[var(--text)]/5 rounded-full hover:bg-[var(--text)]/10 transition-colors">
            <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>

          <div className="max-w-2xl">
            {activeTab === 'account' && (
              <div className="animate-in fade-in slide-in-from-right-4 duration-300">
                <h3 className="text-2xl font-semibold mb-6">Profil Bilgileri</h3>
                <div className="flex items-center gap-6 mb-8 p-6 bg-[var(--background)] rounded-2xl border border-[var(--outline)]">
                  {profileData?.photoURL ? (
                    <img src={profileData.photoURL} alt="Profil" className="w-20 h-20 rounded-full border-2 border-white shadow-sm object-cover" />
                  ) : (
                    <div className="w-20 h-20 rounded-full bg-[var(--surface-4)] flex items-center justify-center border-2 border-white shadow-sm text-2xl font-bold text-[var(--primary)]">
                      {profileData?.displayName ? profileData.displayName[0].toUpperCase() : '?'}
                    </div>
                  )}
                  <div>
                    <div className="text-xl font-semibold">{profileData?.displayName || 'Kullanıcı'}</div>
                    <div className="text-[var(--text-muted)] mt-1">{profileData?.email || 'E-posta tanımlanmamış'}</div>
                    <div className="inline-block mt-3 px-3 py-1 bg-[var(--primary)]/10 text-[var(--primary)] text-xs font-semibold rounded-full uppercase tracking-wider">
                      {profileData?.subscription?.plan || profileData?.plan || 'Standart Plan'}
                    </div>
                  </div>
                </div>

                <div className="space-y-8">
                  <SettingGroup title="Hesap Yönetimi">
                    <SettingRow icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>} title="Şifre ve Güvenlik" onClick={() => alert('Şifre ve güvenlik ayarları çok yakında eklenecek.')} />
                    <SettingRow icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><line x1="1" y1="10" x2="23" y2="10"/></svg>} title="Aboneliği Yönet" onClick={() => alert('Abonelik yönetimi portalına yönlendiriliyorsunuz...')} />
                  </SettingGroup>

                  <div className="pt-4 border-t border-[var(--outline)] space-y-3">
                    <SettingRow icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>} title="Oturumu Kapat" description="Hesabınızdan güvenli bir şekilde çıkış yapın." onClick={() => { onClose(); onLogout(); }} destructive />
                    
                    <SettingRow icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>} title="Hesabı Sil" description="Hesabınızı ve tüm verilerinizi kalıcı olarak silin." onClick={() => { 
                      if(confirm('Hesabınızı kalıcı olarak silmek istediğinize emin misiniz?')) {
                        alert('Hesap silme işlemi henüz web üzerinden desteklenmemektedir.');
                      }
                    }} destructive />
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'appearance' && (
              <div className="animate-in fade-in slide-in-from-right-4 duration-300">
                <h3 className="text-2xl font-semibold mb-6">Görünüm</h3>
                
                <div className="space-y-8">
                  <SettingGroup title="Tema">
                    <SelectField value={prefs.themeMode} onChange={(v: any) => prefs.updatePreference('themeMode', v)} options={[
                      { value: 'light', label: 'Aydınlık' },
                      { value: 'dark', label: 'Karanlık' },
                      { value: 'system', label: 'Sistem' }
                    ]} />
                  </SettingGroup>

                  <SettingGroup title="Metin Boyutu">
                    <SelectField value={prefs.textScale} onChange={(v: any) => prefs.updatePreference('textScale', v)} options={[
                      { value: 'small', label: 'Küçük' },
                      { value: 'standard', label: 'Standart' },
                      { value: 'large', label: 'Büyük' }
                    ]} />
                  </SettingGroup>

                  <SettingGroup title="Arayüz Yoğunluğu">
                    <SelectField value={prefs.interfaceDensity} onChange={(v: any) => prefs.updatePreference('interfaceDensity', v)} options={[
                      { value: 'compact', label: 'Kompakt' },
                      { value: 'standard', label: 'Standart' },
                      { value: 'comfortable', label: 'Geniş' }
                    ]} />
                  </SettingGroup>
                </div>
              </div>
            )}

            {activeTab === 'chat' && (
              <div className="animate-in fade-in slide-in-from-right-4 duration-300">
                <h3 className="text-2xl font-semibold mb-6">Sohbet</h3>
                
                <div className="space-y-8">
                  <SettingGroup title="Sohbet Temizliği">
                    <SelectField value={prefs.chatRetention} onChange={(v: any) => prefs.updatePreference('chatRetention', v)} options={[
                      { value: '7', label: '7 gün sonra sil' },
                      { value: '30', label: '30 gün sonra sil' },
                      { value: 'forever', label: 'Sonsuza kadar sakla' }
                    ]} />
                    <p className="text-xs text-[var(--text-muted)] mt-2">Bu ayar otomatik sohbet geçmişi temizliğini kontrol eder.</p>
                  </SettingGroup>

                  <div className="pt-4 border-t border-[var(--outline)]">
                    <SettingRow icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>} title="Tüm Sohbetleri Temizle" description="Geçmişteki tüm konuşmaları cihazdan ve sunucudan kalıcı olarak siler." onClick={() => { 
                      if(confirm('Tüm sohbet geçmişini silmek istediğinize emin misiniz? Bu işlem geri alınamaz.')) {
                        onClearChats();
                        onClose();
                      }
                    }} destructive />
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'legal' && (
              <div className="animate-in fade-in slide-in-from-right-4 duration-300">
                <h3 className="text-2xl font-semibold mb-6">
                  {locale === 'en' ? 'Legal & Support' : 'Yasal ve Destek'}
                </h3>
                
                <div className="space-y-3">
                  <SettingRow 
                    icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>} 
                    title={locale === 'en' ? 'Privacy Policy' : 'Gizlilik Politikası'} 
                    description={`elyan.dev/${locale}/privacy`} 
                    onClick={() => window.open(`https://elyan.dev/${locale}/privacy`, '_blank')} 
                  />
                  
                  <SettingRow 
                    icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>} 
                    title={locale === 'en' ? 'Terms of Service' : 'Kullanım Koşulları'} 
                    description={`elyan.dev/${locale}/terms`} 
                    onClick={() => window.open(`https://elyan.dev/${locale}/terms`, '_blank')} 
                  />
                  
                  <SettingRow 
                    icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>} 
                    title={locale === 'en' ? 'AI Disclosure' : 'Yapay Zeka Bildirimi'} 
                    description={`elyan.dev/${locale}/ai`} 
                    onClick={() => window.open(`https://elyan.dev/${locale}/ai`, '_blank')} 
                  />

                  <div className="pt-2">
                    <SettingRow 
                      icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>} 
                      title={locale === 'en' ? 'Help Center' : 'Destek Merkezi'} 
                      description={`elyan.dev/${locale}/support`} 
                      onClick={() => window.open(`https://elyan.dev/${locale}/support`, '_blank')} 
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// Helpers
function TabButton({ id, current, onClick, children, icon }: any) {
  const active = current === id;
  return (
    <button onClick={onClick} className={`flex items-center gap-3 px-4 py-3 rounded-xl text-left transition-colors whitespace-nowrap shrink-0 md:w-full ${active ? 'bg-[var(--background-deep)] shadow-sm font-semibold text-[var(--text)] border border-[var(--outline)]' : 'text-[var(--text-muted)] hover:bg-[var(--text)]/5 font-medium'}`}>
      <div className={`${active ? 'text-[var(--primary)]' : 'opacity-60'}`}>{icon}</div>
      {children}
    </button>
  );
}

function SettingGroup({ title, children }: any) {
  return (
    <div>
      <h4 className="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3 px-1">{title}</h4>
      <div className="bg-[var(--background)] rounded-2xl border border-[var(--outline)] p-1">
        {children}
      </div>
    </div>
  );
}

function SettingRow({ icon, title, description, onClick, destructive }: any) {
  return (
    <button onClick={onClick} className={`w-full flex items-center justify-between p-4 rounded-xl transition-colors ${destructive ? 'hover:bg-red-50 group' : 'hover:bg-[var(--text)]/5'}`}>
      <div className="flex items-center gap-4">
        <div className={`p-2 rounded-lg ${destructive ? 'bg-red-100 text-red-600 group-hover:bg-red-200' : 'bg-[var(--surface-4)] text-[var(--primary)]'}`}>
          {icon}
        </div>
        <div className="text-left">
          <div className={`font-semibold ${destructive ? 'text-red-600' : 'text-[var(--text)]'}`}>{title}</div>
          {description && <div className={`text-sm mt-0.5 ${destructive ? 'text-red-500/80' : 'text-[var(--text-muted)]'}`}>{description}</div>}
        </div>
      </div>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-30"><polyline points="9 18 15 12 9 6"/></svg>
    </button>
  );
}

function SelectField({ value, onChange, options }: any) {
  return (
    <div className="flex bg-[var(--text)]/5 p-1 rounded-xl">
      {options.map((opt: any) => (
        <button key={opt.value} onClick={() => onChange(opt.value)} className={`flex-1 py-2 px-3 text-sm font-medium rounded-lg transition-all ${value === opt.value ? 'bg-[var(--background-deep)] shadow-sm text-[var(--text)]' : 'text-[var(--text-muted)] hover:bg-[var(--text)]/5'}`}>
          {opt.label}
        </button>
      ))}
    </div>
  );
}
