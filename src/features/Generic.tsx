import { useApp } from '../app/store';
import { PageHeader, Panel, EmptyState } from '../components/ui';
import { ALL_ITEMS, type RouteId } from '../app/nav';

export function Generic({ route }: { route: RouteId }) {
  const { t } = useApp();
  const item = ALL_ITEMS.find((i) => i.id === route)!;
  return (
    <>
      <PageHeader title={t(item.labelKey)} subtitle={t(item.subtitleKey)} />
      <Panel>
        <EmptyState
          glyph={item.icon}
          title={t(item.labelKey)}
          hint={t('state.emptyHint')}
        />
      </Panel>
    </>
  );
}
