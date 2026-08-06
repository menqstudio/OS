import { describe, it, expect, vi } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/react';
import { Beatline, StripChart, BarChart, type StripPoint, type BarDatum } from './Chart';
import { buildECG, buildLinePath, pointCoords, ringPositions, STRIP_W, STRIP_H } from './geometry';

/**
 * Geometry is pure and deterministic, so it is asserted directly; the Beatline
 * component is checked for its accessible summary, the labelled <svg role="img">,
 * and the <details> data-table fallback, plus the loading/empty states.
 */

describe('geometry', () => {
  it('buildLinePath is deterministic for the same input', () => {
    const a = buildLinePath([1, 2, 3, 4], 100, 50);
    const b = buildLinePath([1, 2, 3, 4], 100, 50);
    expect(a).toBe(b);
    expect(a.startsWith('M')).toBe(true);
  });

  it('buildLinePath returns empty string for no data and a flat mid line for one point', () => {
    expect(buildLinePath([], 100, 50)).toBe('');
    expect(buildLinePath([5], 100, 50)).toBe('M 0 25.0 L 100.0 25.0');
  });

  it('buildLinePath spaces x evenly and normalizes y into the padded band', () => {
    const path = buildLinePath([0, 10], 100, 50, 6);
    // two points: x at 0 and 100; min(0)->bottom band, max(10)->top band
    expect(path).toBe('M 0.0 44.0 L 100.0 6.0');
  });

  it('pointCoords returns one coord per value', () => {
    const pts = pointCoords([1, 2, 3], 90, 30);
    expect(pts).toHaveLength(3);
    expect(pts[0].x).toBe(0);
    expect(pts[2].x).toBe(90);
  });

  it('buildECG produces a path across the requested number of beats', () => {
    const d = buildECG(STRIP_W, STRIP_H, 4);
    expect(d.startsWith('M 0 ')).toBe(true);
    // one M plus multiple L segments per beat
    expect((d.match(/L /g) ?? []).length).toBeGreaterThan(4 * 8);
  });

  it('ringPositions returns one 0..100 coord per node, first at the top', () => {
    expect(ringPositions(0)).toEqual([]);
    // single node sits at the centre
    expect(ringPositions(1)).toEqual([{ x: 50, y: 50 }]);
    const pts = ringPositions(4);
    expect(pts).toHaveLength(4);
    // first node is at the top (−90°): x≈centre, y above centre
    expect(pts[0].x).toBeCloseTo(50, 5);
    expect(pts[0].y).toBeLessThan(50);
    // deterministic
    expect(ringPositions(4)).toEqual(pts);
  });
});

const DATA = [
  { label: 'Mon', value: 3 },
  { label: 'Tue', value: 8 },
  { label: 'Wed', value: 5 },
];

describe('Beatline', () => {
  it('renders an accessible summary and a labelled image', () => {
    render(<Beatline data={DATA} caption="Weekly beats" />);
    const img = screen.getByRole('img', { name: /Weekly beats/ });
    expect(img).toBeInTheDocument();
    // auto summary names the range + latest value
    expect(screen.getByText(/3 points/)).toBeInTheDocument();
    expect(screen.getByText(/Latest 5/)).toBeInTheDocument();
  });

  it('provides a data-table fallback with a row per point', () => {
    render(<Beatline data={DATA} caption="Weekly" />);
    const table = screen.getByRole('table', { name: 'Weekly' });
    expect(within(table).getByText('Mon')).toBeInTheDocument();
    expect(within(table).getByText('Tue')).toBeInTheDocument();
    // 1 header row + 3 data rows
    expect(within(table).getAllByRole('row')).toHaveLength(4);
  });

  it('renders an honest empty state with no data', () => {
    render(<Beatline data={[]} caption="Empty" emptyTitle="No beats yet" />);
    expect(screen.getByText('No beats yet')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('marks the figure busy while loading', () => {
    const { container } = render(<Beatline data={[]} caption="Loading" loading />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it('honours a custom summary override', () => {
    render(<Beatline data={DATA} caption="C" summary="my custom summary" />);
    expect(screen.getByText('my custom summary')).toBeInTheDocument();
  });
});

const STRIP: StripPoint[] = [
  { id: 'a', label: 'Beat 1' },
  { id: 'b', label: 'Beat 2' },
  { id: 'c', label: 'Beat 3' },
];

function stripProps() {
  return {
    onSelect: vi.fn(),
    onOpen: vi.fn(),
    onToggleFreeze: vi.fn(),
    onCloseOpened: vi.fn(),
  };
}

describe('StripChart (interactive beatline)', () => {
  it('exposes a focusable group labelled by ariaLabel and one blip per point', () => {
    const p = stripProps();
    render(<StripChart points={STRIP} selected={0} ariaLabel="Activity strip" {...p} />);
    const group = screen.getByRole('group', { name: 'Activity strip' });
    expect(group).toHaveAttribute('tabindex', '0');
    // one button per point, each with its text label
    expect(screen.getByRole('button', { name: 'Beat 1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Beat 3' })).toBeInTheDocument();
  });

  it('keeps a single blip in the tab order (roving tabindex on the selected point)', () => {
    const p = stripProps();
    render(<StripChart points={STRIP} selected={1} ariaLabel="S" {...p} />);
    const blips = screen.getAllByRole('button');
    const tabbable = blips.filter((b) => b.getAttribute('tabindex') === '0');
    expect(tabbable).toHaveLength(1);
    expect(tabbable[0]).toHaveAccessibleName('Beat 2');
  });

  it('scrubs selection with the arrow keys (clamped, no wrap)', () => {
    const p = stripProps();
    const { rerender } = render(<StripChart points={STRIP} selected={1} ariaLabel="S" {...p} />);
    const group = screen.getByRole('group', { name: 'S' });
    fireEvent.keyDown(group, { key: 'ArrowRight' });
    expect(p.onSelect).toHaveBeenLastCalledWith(2);
    fireEvent.keyDown(group, { key: 'ArrowLeft' });
    expect(p.onSelect).toHaveBeenLastCalledWith(0);
    // clamp at the top edge
    rerender(<StripChart points={STRIP} selected={2} ariaLabel="S" {...p} />);
    fireEvent.keyDown(group, { key: 'ArrowRight' });
    expect(p.onSelect).toHaveBeenLastCalledWith(2);
  });

  it('Home/End jump to the first and last points', () => {
    const p = stripProps();
    render(<StripChart points={STRIP} selected={1} ariaLabel="S" {...p} />);
    const group = screen.getByRole('group', { name: 'S' });
    fireEvent.keyDown(group, { key: 'Home' });
    expect(p.onSelect).toHaveBeenLastCalledWith(0);
    fireEvent.keyDown(group, { key: 'End' });
    expect(p.onSelect).toHaveBeenLastCalledWith(2);
  });

  it('Space freezes, Enter opens the selected point, Esc closes an open detail', () => {
    const p = stripProps();
    const { rerender } = render(<StripChart points={STRIP} selected={1} ariaLabel="S" {...p} />);
    const group = screen.getByRole('group', { name: 'S' });
    fireEvent.keyDown(group, { key: ' ' });
    expect(p.onToggleFreeze).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(group, { key: 'Enter' });
    expect(p.onOpen).toHaveBeenLastCalledWith(1);
    // Esc only closes when something is open
    fireEvent.keyDown(group, { key: 'Escape' });
    expect(p.onCloseOpened).not.toHaveBeenCalled();
    rerender(<StripChart points={STRIP} selected={1} opened={1} ariaLabel="S" {...p} />);
    fireEvent.keyDown(group, { key: 'Escape' });
    expect(p.onCloseOpened).toHaveBeenCalledTimes(1);
  });

  it('marks the opened point with aria-pressed and selects/opens on click', () => {
    const p = stripProps();
    render(<StripChart points={STRIP} selected={0} opened={2} ariaLabel="S" {...p} />);
    expect(screen.getByRole('button', { name: 'Beat 3' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Beat 1' })).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'Beat 2' }));
    expect(p.onSelect).toHaveBeenLastCalledWith(1);
    expect(p.onOpen).toHaveBeenLastCalledWith(1);
  });
});

const BARS: BarDatum[] = [
  { key: 'x', label: 'North', value: 8 },
  { key: 'y', label: 'South', value: 2 },
];

describe('BarChart', () => {
  it('renders an auto summary, a labelled figure and a bar per visible datum', () => {
    render(<BarChart data={BARS} caption="Regions" />);
    const fig = screen.getByRole('img', { name: /2 series, total 10/ });
    expect(fig).toBeInTheDocument();
    // the bar label lives inside the figure (the table has its own copy)
    expect(within(fig).getByText('North')).toBeInTheDocument();
    // highest is named in the summary
    expect(screen.getByText(/Highest: North \(8\)/)).toBeInTheDocument();
  });

  it('shows each bar value with its share of the visible total', () => {
    const { container } = render(<BarChart data={BARS} caption="R" />);
    const shares = Array.from(container.querySelectorAll('.bar-share')).map((s) => s.textContent);
    expect(shares).toContain(' · 80%');
    expect(shares).toContain(' · 20%');
  });

  it('renders a focusable legend that toggles a series when onToggle is set', () => {
    const onToggle = vi.fn();
    render(<BarChart data={BARS} caption="R" hidden={new Set()} onToggle={onToggle} legendLabel="Toggle" />);
    const legend = screen.getByRole('group', { name: 'Toggle' });
    const north = within(legend).getByRole('button', { name: /North/ });
    expect(north).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(north);
    expect(onToggle).toHaveBeenCalledWith('x');
  });

  it('reflects a hidden series (pressed=false, all-hidden note when empty)', () => {
    const onToggle = vi.fn();
    const { rerender, container } = render(
      <BarChart data={BARS} caption="R" hidden={new Set(['x'])} onToggle={onToggle} allHiddenNote="none" />,
    );
    // hidden series is not drawn as a bar, but stays in the legend as un-pressed
    expect(container.querySelectorAll('.bar-row')).toHaveLength(1);
    rerender(<BarChart data={BARS} caption="R" hidden={new Set(['x', 'y'])} onToggle={onToggle} allHiddenNote="none" />);
    expect(screen.getByText('none')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('provides a <details> data-table fallback with a row per datum', () => {
    render(<BarChart data={BARS} caption="Regions" nodeHeader="Region" tableToggle="Table" />);
    const table = screen.getByRole('table', { name: 'Regions' });
    expect(within(table).getByText('North')).toBeInTheDocument();
    expect(within(table).getByText('South')).toBeInTheDocument();
    // 1 header row + 2 data rows
    expect(within(table).getAllByRole('row')).toHaveLength(3);
  });

  it('honours a custom summary override', () => {
    render(<BarChart data={BARS} caption="R" summary="custom bar summary" />);
    expect(screen.getByText('custom bar summary')).toBeInTheDocument();
  });
});
