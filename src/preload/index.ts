import { contextBridge, ipcRenderer } from 'electron';
import { createDesktopApi } from './createDesktopApi';
import type { DesktopSubscriptionChannel } from '../shared/channels';

const api = createDesktopApi({
  invoke(channel, payload) {
    return ipcRenderer.invoke(channel, payload);
  },
  on(channel: DesktopSubscriptionChannel, listener) {
    const wrapped = (_event: Electron.IpcRendererEvent, payload: unknown) => {
      listener(payload);
    };
    ipcRenderer.on(channel, wrapped);
    return () => {
      ipcRenderer.removeListener(channel, wrapped);
    };
  },
});

contextBridge.exposeInMainWorld('elyanDesktop', api);
