import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// The header rendered a hard-coded "STREAM · LIVE" pill with a green `live` power mark
// in EVERY state — while the read was in flight, after it failed, and when the governed
// wall refused it. There is no stream at all: `get_analytics` is a single read of an
// all-time aggregate. A live indicator that is always on is decoration pretending to be
// telemetry, so the pill now reports the real state of that one read.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Analytics } from './Analytics';

function setup(outcome: 'ok' | 'error' | 'denied') {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd !== 'get_analytics') return Promise.resolve(null);
    if (outcome === 'error') return Promise.reject(new Error('engine socket closed'));
    if (outcome === 'denied') return Promise.reject(new Error('get_analytics not allowed: permission denied'));
    return Promise.resolve([{ key: 'runs', label: 'Runs', value: 12 }]);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Analytics />
      </ToastProvider>
    </AppProvider>,
  );
}

/** The header power mark's state classes. */
const headerMarkClass = () => document.querySelector('.pageHead .mark')?.className ?? '';

// Rendering a whole feature page under jsdom can exceed the 5s default on a loaded
// machine. The assertions below are about honesty, not speed — give them room so a
// slow environment cannot be mistaken for a regression.
vi.setConfig({ testTimeout: 30000 });

beforeEach(() => invokeMock.mockReset());

describe('Analytics — no page ever claims a live stream', () => {
  it('never renders "STREAM · LIVE" on a successful read', async () => {
    setup('ok');
    await waitFor(() => expect(screen.getAllByText(/SNAPSHOT/).length).toBeGreaterThan(0));

    expect(screen.queryByText('STREAM · LIVE')).not.toBeInTheDocument();
    // The honest claim: one all-time snapshot, not a feed.
    expect(screen.getAllByText('SNAPSHOT · all-time aggregate').length).toBeGreaterThan(0);
    // A settled, successful read is `idle` — never the green `live` mark.
    expect(headerMarkClass()).not.toMatch(/\blive\b/);
    expect(headerMarkClass()).toMatch(/\bidle\b/);

    // The travelling `wire.live` pulse is gone too: there is nothing streaming to pulse.
    expect(document.querySelector('.an-deck .wire.live')).toBeNull();
    expect(document.querySelector('.an-deck .wire')).not.toBeNull();
  });

  it('reports a FAILED read as unavailable, with no live indicator anywhere', async () => {
    setup('error');
    await waitFor(() => expect(screen.getByText('READ · unavailable')).toBeInTheDocument());

    expect(screen.queryByText('STREAM · LIVE')).not.toBeInTheDocument();
    expect(screen.queryByText(/SNAPSHOT/)).not.toBeInTheDocument();
    expect(headerMarkClass()).not.toMatch(/\blive\b/);
    expect(headerMarkClass()).toMatch(/\balert\b/);
    expect(document.querySelector('.wire.live')).toBeNull();
  });

  it('reports a read REFUSED at the governed wall as blocked, not as a live stream', async () => {
    setup('denied');
    await waitFor(() => expect(screen.getByText('READ · blocked at the wall')).toBeInTheDocument());

    expect(screen.queryByText('STREAM · LIVE')).not.toBeInTheDocument();
    expect(headerMarkClass()).not.toMatch(/\blive\b/);
    // The body states the refusal too, not just the header.
    expect(screen.getByText(/blocked at the wall; nothing was read/i)).toBeInTheDocument();
  });
});
