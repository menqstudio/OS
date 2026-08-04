import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

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
