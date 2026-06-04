import type { SystemCapabilities, WindowState } from '../../shared/protocol';

interface TitlebarProps {
  appReady: boolean;
  systemCapabilities: SystemCapabilities | null;
  windowState: WindowState | null;
  onMinimize: () => void;
  onMaximize: () => void;
  onClose: () => void;
}

export function Titlebar({ appReady, systemCapabilities, windowState }: TitlebarProps) {
  const platform = systemCapabilities?.platform ?? windowState?.platform ?? 'darwin';
  return (
    <header className={`titlebar titlebar--${platform} ${appReady ? 'titlebar--ready' : ''}`} aria-label="Pencere">
      <div className="titlebar__drag" />
    </header>
  );
}
