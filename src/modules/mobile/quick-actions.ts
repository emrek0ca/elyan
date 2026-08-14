export const MOBILE_QUICK_ACTION_ICONS = [
  "tray.full",
  "doc.text",
  "photo",
  "calendar",
  "magnifyingglass",
  "folder",
  "chart.bar",
  "envelope",
  "desktopcomputer",
  "sparkles",
  "checklist",
  "globe",
] as const;

export type MobileQuickActionIcon = (typeof MOBILE_QUICK_ACTION_ICONS)[number];
export type MobileQuickActionRoute = "auto" | "server" | "desktop";

export type MobileQuickAction = {
  id: string;
  label: string;
  hint: string;
  icon: MobileQuickActionIcon;
  prompt: string;
  route: MobileQuickActionRoute;
};

type QuickActionDevice = {
  type: string;
  canReceiveTasks: boolean;
  targetStatus: string;
  runtime: {
    isConnected: boolean;
  };
};

const SAFE_QUICK_ACTIONS: readonly MobileQuickAction[] = [
  {
    id: "summarize_content",
    label: "Bir şeyi özetle",
    hint: "Metin veya belge içeriğini kısalt",
    icon: "doc.text",
    prompt: "Bu içeriği özetle",
    route: "auto",
  },
  {
    id: "create_image",
    label: "Görsel üret",
    hint: "Bir fikir için yeni görsel oluştur",
    icon: "photo",
    prompt: "Yeni bir görsel üret",
    route: "auto",
  },
  {
    id: "make_a_plan",
    label: "Bir plan oluştur",
    hint: "Hedefin için uygulanabilir adımlar çıkar",
    icon: "checklist",
    prompt: "Bu hedef için bir plan oluştur",
    route: "server",
  },
  {
    id: "research_topic",
    label: "Bir konu araştır",
    hint: "Güncel ve güvenilir kaynakları bul",
    icon: "globe",
    prompt: "Bu konuyu araştır",
    route: "server",
  },
];

const DESKTOP_QUICK_ACTION: MobileQuickAction = {
  id: "search_local_files",
  label: "Bilgisayarımda ara",
  hint: "Yerel dosyalarında güvenli arama yap",
  icon: "desktopcomputer",
  prompt: "Bilgisayarımda arama yap",
  route: "desktop",
};

function hasReadyDesktop(devices: readonly QuickActionDevice[]): boolean {
  return devices.some((device) =>
    device.type === "desktop" &&
    device.canReceiveTasks &&
    device.targetStatus === "ready" &&
    device.runtime.isConnected,
  );
}

export function buildMobileQuickActions(
  devices: readonly QuickActionDevice[],
): MobileQuickAction[] {
  // Bu katalog kullanıcı verisi içermez; kilit ekranında görünebileceği için
  // kişisel mail, dosya veya bağlayıcı adlarını sunucu tarafında üretmiyoruz.
  const actions = hasReadyDesktop(devices)
    ? [...SAFE_QUICK_ACTIONS, DESKTOP_QUICK_ACTION]
    : [...SAFE_QUICK_ACTIONS];

  // Mobil sözleşmesi gereği gelecekte katalog büyüse bile istemciye altıdan
  // fazla kart göndermiyoruz. Spread ile her çağrıda yeni nesneler döner.
  return actions.slice(0, 6).map((action) => ({ ...action }));
}
