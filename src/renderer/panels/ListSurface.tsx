export type ListSurfaceStatusTone = 'neutral' | 'success' | 'warning' | 'danger';

import { useEffect, useState, type MouseEvent } from 'react';

export interface ListSurfaceItem {
  id: string;
  title: string;
  subtitle: string;
  meta: string;
  details?: string;
  status?: string;
  statusTone?: ListSurfaceStatusTone;
  badges?: string[];
}

interface ListSurfaceProps {
  title: string;
  subtitle: string;
  items: ListSurfaceItem[];
  loading: boolean;
  error: string;
  onRefresh: () => void;
  onBack: () => void;
  onSelectItem?: (id: string) => void;
  onRenameItem?: (id: string, title: string) => void;
  onSecondaryAction?: (id: string) => void;
  onDeleteItem?: (id: string) => void;
  secondaryActionLabel?: string;
}

export function ListSurface({
  title,
  subtitle,
  items,
  loading,
  error,
  onRefresh,
  onBack,
  onSelectItem,
  onRenameItem,
  onSecondaryAction,
  onDeleteItem,
  secondaryActionLabel = 'İşlem',
}: ListSurfaceProps) {
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; item: ListSurfaceItem } | null>(null);

  useEffect(() => {
    const handleClick = () => setContextMenu(null);
    document.addEventListener('click', handleClick);
    return () => document.removeEventListener('click', handleClick);
  }, []);

  function openContextMenu(event: MouseEvent<HTMLElement>, item: ListSurfaceItem) {
    if (!onRenameItem && !onSecondaryAction && !onDeleteItem) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const menuWidth = 188;
    const menuHeight = 150;
    const margin = 12;
    const x = Math.max(margin, Math.min(event.clientX, window.innerWidth - menuWidth - margin));
    const y = Math.max(margin, Math.min(event.clientY, window.innerHeight - menuHeight - margin));
    setContextMenu({ x, y, item });
  }

  return (
    <main className="list-surface" aria-label={title}>
      <header className="list-top">
        <div>
          <strong>{title}</strong>
          <small>{subtitle}</small>
        </div>
        <span>
          <button type="button" onClick={onRefresh}>
            Yenile
          </button>
          <button type="button" onClick={onBack}>
            Sohbet
          </button>
        </span>
      </header>

      {error ? <div className="safe-error safe-error--inline">{error}</div> : null}
      {loading ? <div className="list-empty">Yükleniyor</div> : null}
      {!loading && items.length === 0 ? <div className="list-empty">Kayıt yok</div> : null}
      {!loading && items.length > 0 ? (
        <section className="plain-list">
          {items.map((item) => {
            const content = (
              <>
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.subtitle}</small>
                  {item.details ? <small>{item.details}</small> : null}
                  {item.badges?.length ? <small>{item.badges.join(' · ')}</small> : null}
                </span>
                <span>
                  {item.status ? <i data-tone={item.statusTone ?? 'neutral'}>{item.status}</i> : null}
                  {item.meta ? <i>{item.meta}</i> : null}
                  {onSecondaryAction && item.badges?.includes('archive') ? (
                    <button
                      type="button"
                      className="plain-list__secondary"
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        onSecondaryAction(item.id);
                      }}
                    >
                      {secondaryActionLabel}
                    </button>
                  ) : null}
                </span>
              </>
            );

            return onSelectItem ? (
              <button
                type="button"
                className="plain-list__item"
                key={item.id}
                onClick={() => onSelectItem(item.id)}
                onContextMenu={(event) => openContextMenu(event, item)}
              >
                {content}
              </button>
            ) : (
              <article className="plain-list__item" key={item.id} onContextMenu={(event) => openContextMenu(event, item)}>
                {content}
              </article>
            );
          })}
        </section>
      ) : null}
      {contextMenu ? (
        <div className="context-menu" style={{ left: contextMenu.x, top: contextMenu.y }} onClick={(event) => event.stopPropagation()}>
          {onSelectItem ? (
            <button
              type="button"
              className="context-menu__item"
              onClick={() => {
                onSelectItem(contextMenu.item.id);
                setContextMenu(null);
              }}
            >
              Aç
            </button>
          ) : null}
          {onRenameItem ? (
            <button
              type="button"
              className="context-menu__item"
              onClick={() => {
                onRenameItem(contextMenu.item.id, contextMenu.item.title);
                setContextMenu(null);
              }}
            >
              Yeniden adlandır
            </button>
          ) : null}
          {onSecondaryAction ? (
            <button
              type="button"
              className="context-menu__item"
              onClick={() => {
                onSecondaryAction(contextMenu.item.id);
                setContextMenu(null);
              }}
            >
              {secondaryActionLabel}
            </button>
          ) : null}
          {onDeleteItem ? (
            <button
              type="button"
              className="context-menu__item context-menu__item--danger"
              onClick={() => {
                onDeleteItem(contextMenu.item.id);
                setContextMenu(null);
              }}
            >
              Sil
            </button>
          ) : null}
        </div>
      ) : null}
    </main>
  );
}
