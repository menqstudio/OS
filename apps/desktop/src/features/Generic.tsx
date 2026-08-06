import { useApp } from '../app/store';
import { PageHeader, Panel, EmptyState } from '../components/ui';
import { ALL_ITEMS, type RouteId } from '../app/nav';

// Honest placeholder for workspaces that do not yet have a backend command
// surface. No mock data: it states plainly that the workspace is not wired.
export function Generic({ route }: { route: RouteId }) {
  const { t } = useApp();
  // Guard: an unknown route (e.g. a stale URL hash) must not crash — fall back to the
  // raw id rather than dereferencing a missing nav item.
  const item = ALL_ITEMS.find((i) => i.id === route);
  return (
    <>
      <PageHeader title={item ? t(item.labelKey) : String(route)} subtitle={item ? t(item.subtitleKey) : ''} />
      <Panel>
        <EmptyState glyph={item?.icon ?? '◍'} title={t('generic.title')} hint={t('generic.hint')} />
      </Panel>
    </>
  );
}
