export const IPC_CHANNELS = {
  bootstrap: 'elyan:bootstrap',
  request: 'elyan:request',
  windowMinimize: 'elyan:window:minimize',
  windowMaximizeOrRestore: 'elyan:window:maximizeOrRestore',
  windowClose: 'elyan:window:close',
  windowGetState: 'elyan:window:getState',
  windowAckCloseAnimation: 'elyan:window:ackCloseAnimation',
  systemGetCapabilities: 'elyan:system:getCapabilities',
  providersSaveSecret: 'elyan:providers:saveSecret',
  providersRemoveSecret: 'elyan:providers:removeSecret',
  providersGetVaultStatus: 'elyan:providers:getVaultStatus',
} as const;

export const SUBSCRIPTION_CHANNELS = [
  'runtime-status',
  'runtime-event',
  'backend-truth',
  'window-lifecycle',
  'close-handshake',
] as const;

export type DesktopSubscriptionChannel = (typeof SUBSCRIPTION_CHANNELS)[number];

export function isDesktopSubscriptionChannel(value: string): value is DesktopSubscriptionChannel {
  return SUBSCRIPTION_CHANNELS.includes(value as DesktopSubscriptionChannel);
}
