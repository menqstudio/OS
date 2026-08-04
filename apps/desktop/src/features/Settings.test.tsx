import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. Settings reflects the REAL ai_status the backend
// reports — provider/model/ready/governed — and never invents a ready/governed
// posture the backend didn't return.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Settings } from './Settings';

function setup() {
  // Settings gates the provider/model card behind hasBackend() (a real desktop
  // runtime). Simulate that so the real ai_status is reflected in the card.
  (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'ai_status')
      return Promise.resolve({ provider: 'claude-cli', model: 'claude-opus-probe', ready: true, detail: 'ready', governed: false });
    return Promise.resolve(null);
  });
  return render(<AppProvider><ToastProvider><Settings /></ToastProvider></AppProvider>);
}

const called = (cmd: string) => invokeMock.mock.calls.some((c) => c[0] === cmd);

beforeEach(() => invokeMock.mockReset());

describe('Settings — reflects the real ai_status, never a fabricated posture', () => {
  it('renders the real provider/model reported by ai_status', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText(/claude-opus-probe/).length).toBeGreaterThan(0));
    expect(called('ai_status')).toBe(true);
  });
});
