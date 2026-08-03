import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
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

/**
 * Component tests for the Phase-4 library primitives (G1–G6). Like ui.test.tsx
 * these render WITHOUT the Tauri IPC layer or the `useApp` context — every
 * primitive is presentational and takes its labels as props.
 */

interface Row { id: string; name: string; count: number; }
const ROWS: Row[] = [
  { id: 'a', name: 'Alpha', count: 3 },
  { id: 'b', name: 'Beta', count: 7 },
  { id: 'c', name: 'Gamma', count: 1 },
];
const COLS: Column<Row>[] = [
  { key: 'name', header: 'Name' },
  { key: 'count', header: 'Count', numeric: true },
];

describe('DataTable', () => {
  it('renders a table with a caption, column headers and data cells', () => {
    render(<DataTable caption="Widgets" columns={COLS} rows={ROWS} rowKey={(r) => r.id} />);
    const table = screen.getByRole('table', { name: 'Widgets' });
    expect(within(table).getByText('Name')).toBeInTheDocument();
    expect(within(table).getByText('Alpha')).toBeInTheDocument();
    expect(within(table).getByText('7')).toBeInTheDocument();
    // one header row + three body rows
    expect(within(table).getAllByRole('row')).toHaveLength(4);
  });

  it('marks numeric columns with the dt-num class', () => {
    const { container } = render(
      <DataTable caption="W" columns={COLS} rows={ROWS} rowKey={(r) => r.id} />,
    );
    expect(container.querySelector('th.dt-num')).not.toBeNull();
    expect(container.querySelectorAll('td.dt-num').length).toBe(ROWS.length);
  });

  it('shows a skeleton (aria-busy) while loading and no data rows', () => {
    const { container } = render(
      <DataTable caption="W" columns={COLS} rows={[]} rowKey={(r) => r.id} loading />,
    );
    expect(container.querySelector('tbody[aria-busy="true"]')).not.toBeNull();
    expect(container.querySelectorAll('.skeleton').length).toBeGreaterThan(0);
  });

  it('renders the empty state when there are no rows', () => {
    render(
      <DataTable
        caption="W"
        columns={COLS}
        rows={[]}
        rowKey={(r) => r.id}
        emptyTitle="Nothing here"
      />,
    );
    expect(screen.getByText('Nothing here')).toBeInTheDocument();
  });

  it('makes rows keyboard-activatable when onActivateRow is given', () => {
    const onActivate = vi.fn();
    render(
      <DataTable
        caption="W"
        columns={COLS}
        rows={ROWS}
        rowKey={(r) => r.id}
        onActivateRow={onActivate}
      />,
    );
    const rows = screen.getAllByRole('row').slice(1); // drop the header row
    rows[0].focus();
    fireEvent.keyDown(rows[0].parentElement as HTMLElement, { key: 'Enter' });
    expect(onActivate).toHaveBeenCalledWith(ROWS[0], 0);
  });

  it('exposes exactly one row in the tab order (roving tabindex)', () => {
    render(<DataTable caption="W" columns={COLS} rows={ROWS} rowKey={(r) => r.id} />);
    const rows = screen.getAllByRole('row').slice(1);
    const tabbable = rows.filter((r) => r.getAttribute('tabindex') === '0');
    expect(tabbable).toHaveLength(1);
  });
});

describe('Drawer', () => {
  it('renders a labelled modal dialog with its title and children', () => {
    render(<Drawer title="Details" onClose={() => {}}>panel body</Drawer>);
    const dialog = screen.getByRole('dialog', { name: 'Details' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(within(dialog).getByText('panel body')).toBeInTheDocument();
  });

  it('closes on Escape', () => {
    const onClose = vi.fn();
    render(<Drawer title="Details" onClose={onClose}>body</Drawer>);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes on a scrim click but not on an inner click', () => {
    const onClose = vi.fn();
    const { container } = render(<Drawer title="D" onClose={onClose}><span>inner</span></Drawer>);
    fireEvent.click(screen.getByText('inner'));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(container.querySelector('.drawer-scrim') as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('applies the requested side class', () => {
    const { container } = render(<Drawer title="D" side="left" onClose={() => {}}>x</Drawer>);
    expect(container.querySelector('.drawer--left')).not.toBeNull();
  });
});

describe('Rail', () => {
  it('renders a labelled complementary landmark with its title and sections', () => {
    render(
      <Rail label="Context">
        <RailSection title="Filters">filter body</RailSection>
      </Rail>,
    );
    const region = screen.getByRole('complementary', { name: 'Context' });
    expect(within(region).getByText('Filters')).toBeInTheDocument();
    expect(within(region).getByText('filter body')).toBeInTheDocument();
  });

  it('panel variant renders a plain panel with NO complementary landmark', () => {
    const { container } = render(
      <Rail variant="panel" label="Conversations">
        <div>list body</div>
      </Rail>,
    );
    // no landmark is added — this is the whole point of the panel variant
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
    // renders the Panel markup: a .card > .panel with the label as .panel-title
    expect(container.querySelector('.card .panel .panel-title')?.textContent).toBe('Conversations');
    expect(screen.getByText('list body')).toBeInTheDocument();
    // and does NOT use the aside rail chrome
    expect(container.querySelector('.rail')).toBeNull();
  });
});

describe('StatTile / TileGroup', () => {
  it('renders glyph, value and label', () => {
    render(<StatTile glyph="◆" value={42} label="Runs" />);
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('Runs')).toBeInTheDocument();
    expect(screen.getByText('◆')).toBeInTheDocument();
  });

  it('renders a button with an arrow when onActivate is set and fires it', () => {
    const onActivate = vi.fn();
    render(<StatTile glyph="◆" value={1} label="Tasks" onActivate={onActivate} />);
    const btn = screen.getByRole('button', { name: /Tasks/ });
    fireEvent.click(btn);
    expect(onActivate).toHaveBeenCalledTimes(1);
  });

  it('keeps a single tab stop across a TileGroup (roving tabindex)', () => {
    render(
      <TileGroup label="Overview">
        <StatTile glyph="a" value={1} label="One" onActivate={() => {}} />
        <StatTile glyph="b" value={2} label="Two" onActivate={() => {}} />
      </TileGroup>,
    );
    const tiles = screen.getAllByRole('button');
    const tabbable = tiles.filter((el) => el.getAttribute('tabindex') === '0');
    expect(tabbable).toHaveLength(1);
  });

  it('moves focus with the arrow keys inside a TileGroup', () => {
    const { container } = render(
      <TileGroup label="Overview">
        <StatTile glyph="a" value={1} label="One" onActivate={() => {}} />
        <StatTile glyph="b" value={2} label="Two" onActivate={() => {}} />
      </TileGroup>,
    );
    const tiles = screen.getAllByRole('button');
    tiles[0].focus();
    fireEvent.keyDown(container.querySelector('.tile-group') as HTMLElement, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(tiles[1]);
  });

  it('shows the raw numeric value immediately when count-up is off', () => {
    render(<StatTile glyph="x" value={99} label="Count" />);
    expect(screen.getByText('99')).toBeInTheDocument();
  });
});

describe('Mark / LiveMark', () => {
  it('renders the Br·PS wordmark and an optional sub', () => {
    render(<Mark sub="cockpit" />);
    expect(screen.getByText('Br·PS')).toBeInTheDocument();
    expect(screen.getByText('cockpit')).toBeInTheDocument();
  });

  it('shows the state word for each LiveMark state', () => {
    const { rerender, container } = render(<LiveMark state="live" />);
    expect(screen.getByText('Live')).toBeInTheDocument();
    expect(container.querySelector('.livemark--live')).not.toBeNull();
    rerender(<LiveMark state="offline" />);
    expect(screen.getByText('Offline')).toBeInTheDocument();
    expect(container.querySelector('.livemark--offline')).not.toBeNull();
  });

  it('honours a custom label', () => {
    render(<LiveMark state="connecting" label="Linking…" />);
    expect(screen.getByText('Linking…')).toBeInTheDocument();
  });

  it('responsive Mark adds the collapse class and titles the glyph for the narrow layout', () => {
    const { container } = render(<Mark responsive word="BroPS" sub="space" />);
    expect(container.querySelector('.mark--responsive')).not.toBeNull();
    // the glyph keeps a title so the collapsed (text-hidden) mark stays identifiable
    expect(container.querySelector('.mark-glyph')?.getAttribute('title')).toBe('BroPS');
  });

  it('non-responsive Mark carries no collapse class or glyph title', () => {
    const { container } = render(<Mark word="BroPS" />);
    expect(container.querySelector('.mark--responsive')).toBeNull();
    expect(container.querySelector('.mark-glyph')?.getAttribute('title')).toBeNull();
  });
});

describe('InlineAlert', () => {
  it('uses role="status" for calm tones', () => {
    render(<InlineAlert tone="info" title="Heads up">details</InlineAlert>);
    const alert = screen.getByRole('status');
    expect(within(alert).getByText('Heads up')).toBeInTheDocument();
    expect(within(alert).getByText('details')).toBeInTheDocument();
  });

  it('uses role="alert" for the danger tone', () => {
    const { container } = render(<InlineAlert tone="danger">boom</InlineAlert>);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(container.querySelector('.inline-alert--danger')).not.toBeNull();
  });

  it('carries a non-color glyph signal', () => {
    const { container } = render(<InlineAlert tone="success">ok</InlineAlert>);
    expect(container.querySelector('.inline-alert-glyph')?.textContent).toBe('✓');
  });
});
