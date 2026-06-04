export type ListSurfaceStatusTone = 'neutral' | 'success' | 'warning' | 'danger';

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
}

export function ListSurface({ title, subtitle, items, loading, error, onRefresh, onBack, onSelectItem }: ListSurfaceProps) {
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
          <button type="button" className="button-secondary" onClick={onBack}>
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
                </span>
              </>
            );

            return onSelectItem ? (
              <button type="button" className="plain-list__item" key={item.id} onClick={() => onSelectItem(item.id)}>
                {content}
              </button>
            ) : (
              <article className="plain-list__item" key={item.id}>
                {content}
              </article>
            );
          })}
        </section>
      ) : null}
    </main>
  );
}
