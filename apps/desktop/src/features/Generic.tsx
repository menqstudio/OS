import { useApp } from '../app/store';
import { PageHeader, Panel, EmptyState } from '../components/ui';
import { ALL_ITEMS, type RouteId } from '../app/nav';

// Honest placeholder for workspaces that do not yet have a backend command
// surface. No mock data: it states plainly that the workspace is not wired.
export function Generic({ route }: { route: RouteId }) {
  const { t } = useApp();
  const item = ALL_ITEMS.find((i) => i.id === route)!;
  return (
    <>
      <PageHeader title={t(item.labelKey)} subtitle={t(item.subtitleKey)} />
      <Panel>
        <EmptyState
          glyph={item.icon}
          title="Not yet connected to the backend"
          hint="This workspace has no Tauri command surface yet. It will show real data once its backend is implemented (see ROADMAP Phase 4)."
        />
      </Panel>
    </>
  );
}
