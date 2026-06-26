export const IPC_CHANNELS = {
  bootstrap: 'elyan:bootstrap',
  request: 'elyan:request',
  attachmentsSaveFromBase64: 'elyan:attachments:saveFromBase64',
  windowMinimize: 'elyan:window:minimize',
  windowMaximizeOrRestore: 'elyan:window:maximizeOrRestore',
  windowClose: 'elyan:window:close',
  windowGetState: 'elyan:window:getState',
  windowAckCloseAnimation: 'elyan:window:ackCloseAnimation',
  systemGetCapabilities: 'elyan:system:getCapabilities',
  systemGetLocale: 'elyan:system:getLocale',
  systemOpenPermissionSettings: 'elyan:system:openPermissionSettings',
  providersSaveSecret: 'elyan:providers:saveSecret',
  providersRemoveSecret: 'elyan:providers:removeSecret',
  providersGetVaultStatus: 'elyan:providers:getVaultStatus',
  // Dictation
  dictationStart: 'elyan:dictation:start',
  dictationStop: 'elyan:dictation:stop',
  dictationCancel: 'elyan:dictation:cancel',
  dictationGetStatus: 'elyan:dictation:getStatus',
} as const;

export const SUBSCRIPTION_CHANNELS = [
  'runtime-status',
  'runtime-event',
  'chat-block',
  'backend-truth',
  'window-lifecycle',
  'close-handshake',
  'dictation-partial',
  'dictation-final',
  'dictation-error',
  'dictation-status',
] as const;

export type DesktopSubscriptionChannel = (typeof SUBSCRIPTION_CHANNELS)[number];

export function isDesktopSubscriptionChannel(value: string): value is DesktopSubscriptionChannel {
  return SUBSCRIPTION_CHANNELS.includes(value as DesktopSubscriptionChannel);
}
