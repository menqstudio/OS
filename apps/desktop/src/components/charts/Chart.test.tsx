import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { Beatline } from './Chart';
import { buildECG, buildLinePath, pointCoords, STRIP_W, STRIP_H } from './geometry';

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
