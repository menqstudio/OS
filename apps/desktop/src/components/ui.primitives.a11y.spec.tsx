import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { axe } from '../test/axe';
import {
  DataTable,
  Drawer,
  Rail,
  RailSection,
  TileGroup,
  StatTile,
  Mark,
  LiveMark,
  InlineAlert,
  type Column,
} from './ui';
import { Beatline, StripChart, BarChart } from './charts/Chart';

/**
 * Accessibility (axe) smoke tests for the Phase-4 library primitives (G1–G7).
 * Same pattern as ui.a11y.spec.tsx: render each primitive in a <main> landmark,
 * run axe, assert zero WCAG violations. No backend / useApp dependency.
 */

interface Row { id: string; name: string; count: number; }
const ROWS: Row[] = [{ id: 'a', name: 'Alpha', count: 3 }, { id: 'b', name: 'Beta', count: 7 }];
const COLS: Column<Row>[] = [
  { key: 'name', header: 'Name' },
  { key: 'count', header: 'Count', numeric: true },
];

describe('accessibility (axe) — Phase-4 primitives', () => {
  it('DataTable (populated) has no violations', async () => {
    const { container } = render(
      <main><DataTable caption="Widgets" columns={COLS} rows={ROWS} rowKey={(r) => r.id} /></main>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('Drawer dialog has no violations', async () => {
    const { container } = render(
      <main><Drawer title="Details" onClose={() => {}}>panel body</Drawer></main>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('Rail + RailSection has no violations', async () => {
    const { container } = render(
      <main><Rail label="Context"><RailSection title="Filters">body</RailSection></Rail></main>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('TileGroup of StatTiles has no violations', async () => {
    const { container } = render(
      <main>
        <TileGroup label="Overview">
          <StatTile glyph="◆" value={3} label="Runs" onActivate={() => {}} />
          <StatTile glyph="◈" value={7} label="Tasks" onActivate={() => {}} />
        </TileGroup>
      </main>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('Mark + LiveMark have no violations', async () => {
    const { container } = render(
      <main><Mark sub="cockpit" /><LiveMark state="live" /></main>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('InlineAlert (each tone) has no violations', async () => {
    const { container } = render(
      <main>
        <InlineAlert tone="info" title="Info">note</InlineAlert>
        <InlineAlert tone="warning">warn</InlineAlert>
        <InlineAlert tone="danger">boom</InlineAlert>
      </main>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('Beatline chart has no violations', async () => {
    const { container } = render(
      <main>
        <Beatline
          caption="Weekly beats"
          data={[{ label: 'Mon', value: 3 }, { label: 'Tue', value: 8 }, { label: 'Wed', value: 5 }]}
        />
      </main>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('StripChart (interactive beatline) has no violations', async () => {
    const { container } = render(
      <main>
        <StripChart
          ariaLabel="Activity strip — arrow keys scrub, Enter opens, Space freezes"
          points={[{ id: 'a', label: 'Beat 1' }, { id: 'b', label: 'Beat 2' }, { id: 'c', label: 'Beat 3' }]}
          selected={1}
          opened={2}
          onSelect={() => {}}
          onOpen={() => {}}
          onToggleFreeze={() => {}}
          onCloseOpened={() => {}}
        />
      </main>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('BarChart (with legend + table fallback) has no violations', async () => {
    const { container } = render(
      <main>
        <BarChart
          caption="Regions"
          data={[{ key: 'x', label: 'North', value: 8 }, { key: 'y', label: 'South', value: 2 }]}
          hidden={new Set(['y'])}
          onToggle={() => {}}
          legendLabel="Toggle regions"
        />
      </main>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
