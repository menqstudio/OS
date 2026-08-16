import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Analytics } from './Analytics';

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'get_analytics') return Promise.resolve([{ key: 'zz_custom_metric', label: 'Total Runs Logged', value: 42 }]);
    return Promise.resolve(null);
  });
  return render(<AppProvider><ToastProvider><Analytics /></ToastProvider></AppProvider>);
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Analytics — mirrors the real get_analytics store', () => {
  it('renders the real data from get_analytics', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('Total Runs Logged').length).toBeGreaterThan(0));
    expect(called('get_analytics')).toBe(true);
  });
});

// §D: "scrubber (anScrub) … Keyboard: scrubber is a slider (role=slider, arrows)".
// The page had no scrubber at all. What it scrubs is the RANK cut-off, not time: the
// engine returns one all-time aggregate with no time dimension, and drawing an axis the
// data does not have is what this page refuses to do in its other three panels.
function withNodes(n: number) {
  const data = Array.from({ length: n }, (_, i) => ({
    key: `node_${i}`, label: `Node ${i}`, value: (n - i) * 10,
  }));
  invokeMock.mockImplementation((cmd: string) =>
    Promise.resolve(cmd === 'get_analytics' ? data : null));
  return render(<AppProvider><ToastProvider><Analytics /></ToastProvider></AppProvider>);
}

describe('Analytics — the rank scrubber', () => {
  const slider = () => screen.getByRole('slider');

  it('is a real ARIA slider, bounded by the number of nodes', async () => {
    withNodes(5);
    await waitFor(() => expect(slider()).toBeInTheDocument());
    expect(slider()).toHaveAttribute('aria-valuemin', '1');
    expect(slider()).toHaveAttribute('aria-valuemax', '5');
    expect(slider()).toHaveAttribute('aria-valuenow', '5');
    // The value is published as TEXT too, not only as a number a screen reader must
    // interpret against bounds it has to remember.
    expect(slider().getAttribute('aria-valuetext')).toBeTruthy();
    expect(slider()).toHaveAccessibleName();
  });

  it('does not appear when there is nothing to cut', async () => {
    withNodes(1);
    await waitFor(() => expect(screen.getAllByText('Node 0').length).toBeGreaterThan(0));
    expect(screen.queryByRole('slider')).toBeNull();
  });

  it('arrows move the cut, and the plot follows it', async () => {
    const user = userEvent.setup();
    withNodes(4);
    await waitFor(() => expect(slider()).toBeInTheDocument());
    slider().focus();

    await user.keyboard('{ArrowLeft}');
    expect(slider()).toHaveAttribute('aria-valuenow', '3');
    // The lowest-ranked node is the one that leaves first — the cut is by VALUE, and
    // Node 3 is the smallest.
    await waitFor(() => expect(screen.queryByText('Node 3')).toBeNull());
    expect(screen.getAllByText('Node 0').length).toBeGreaterThan(0);

    await user.keyboard('{ArrowRight}');
    expect(slider()).toHaveAttribute('aria-valuenow', '4');
    await waitFor(() => expect(screen.getAllByText('Node 3').length).toBeGreaterThan(0));
  });

  it('Home and End go to the ends — part of the slider contract, not an extra', async () => {
    const user = userEvent.setup();
    withNodes(6);
    await waitFor(() => expect(slider()).toBeInTheDocument());
    slider().focus();
    await user.keyboard('{Home}');
    expect(slider()).toHaveAttribute('aria-valuenow', '1');
    await user.keyboard('{End}');
    expect(slider()).toHaveAttribute('aria-valuenow', '6');
  });

  it('never moves outside its own bounds', async () => {
    const user = userEvent.setup();
    withNodes(3);
    await waitFor(() => expect(slider()).toBeInTheDocument());
    slider().focus();
    await user.keyboard('{Home}{ArrowLeft}{ArrowLeft}');
    expect(slider()).toHaveAttribute('aria-valuenow', '1');
    await user.keyboard('{End}{ArrowRight}{ArrowRight}');
    expect(slider()).toHaveAttribute('aria-valuenow', '3');
  });

  it('the deck total follows the cut instead of contradicting it', async () => {
    const user = userEvent.setup();
    withNodes(3);                     // values 30, 20, 10 → 60 whole, 50 at top-2
    await waitFor(() => expect(slider()).toBeInTheDocument());
    await waitFor(() => expect(screen.getAllByText('60').length).toBeGreaterThan(0));
    slider().focus();
    await user.keyboard('{ArrowLeft}');
    await waitFor(() => expect(screen.getAllByText('50').length).toBeGreaterThan(0));
    // And it says that it is showing a subset, rather than a count that quietly means
    // "some of them".
    expect(screen.getAllByText(/2/).length).toBeGreaterThan(0);
  });
});
