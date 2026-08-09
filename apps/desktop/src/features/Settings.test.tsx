import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

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

const UNGOVERNED = { provider: 'claude-cli', model: 'claude-opus-probe', ready: true, detail: 'ready', governed: false };

function mount(status: unknown | 'reject', backend = true) {
  // Settings gates the provider/model card behind hasBackend() (a real desktop
  // runtime). Simulate that so the real ai_status is reflected in the card.
  if (backend) {
    (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
  } else {
    delete (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
  }
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'ai_status') {
      return status === 'reject' ? Promise.reject(new Error('engine unreachable')) : Promise.resolve(status);
    }
    return Promise.resolve(null);
  });
  return render(<AppProvider><ToastProvider><Settings /></ToastProvider></AppProvider>);
}

function setup() {
  return mount(UNGOVERNED);
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

// The System panel's Governance row used to print "Fail-closed, verified-receipt-
// mandatory" unconditionally, while the shipped default resolves an ungoverned
// provider and every reply streams on the ungoverned path (commands.rs falls through
// on `Ok(false)`). The row must report the ACTUAL runtime state instead.
describe('Settings — the Governance row reports the real runtime posture', () => {
  it('says replies are NOT verified when the resolved provider is ungoverned', async () => {
    mount(UNGOVERNED);
    await waitFor(() =>
      expect(screen.getByText('Not governed — replies are not verified')).toBeInTheDocument(),
    );
    // ...and explains that the fail-closed guarantee does not apply to this session.
    expect(screen.getByText(/no lease, no signed receipt and no verification/i)).toBeInTheDocument();
    // The old unconditional claim is gone.
    expect(screen.queryByText('Fail-closed, verified-receipt-mandatory')).not.toBeInTheDocument();
  });

  it('reports the fail-closed blocking state for a governed provider that is not ready', async () => {
    mount({ provider: 'governed-engine', model: 'py sidecar', ready: false, detail: 'pending', governed: true });
    await waitFor(() =>
      expect(screen.getByText('Governed — fail-closed, currently blocking')).toBeInTheDocument(),
    );
  });

  it('claims verified-receipt governance only when the backend reports governed AND ready', async () => {
    mount({ provider: 'governed-engine', model: 'py sidecar', ready: true, detail: 'ok', governed: true });
    await waitFor(() =>
      expect(screen.getByText('Governed — verified receipt required')).toBeInTheDocument(),
    );
  });

  it('says nothing runs when no provider is resolved', async () => {
    mount({ provider: 'none', model: '', ready: false, detail: '', governed: false });
    await waitFor(() => expect(screen.getByText('No provider — no model runs')).toBeInTheDocument());
  });

  it('renders an explicit unknown when the backend status cannot be read', async () => {
    mount('reject');
    await waitFor(() => expect(screen.getByText('Unknown — not verified here')).toBeInTheDocument());
    expect(screen.getByText(/Treat it as unverified/i)).toBeInTheDocument();
  });

  it('renders an explicit unknown with no desktop backend at all', async () => {
    mount(UNGOVERNED, false);
    await waitFor(() => expect(screen.getByText('Unknown — not verified here')).toBeInTheDocument());
    expect(screen.queryByText('Fail-closed, verified-receipt-mandatory')).not.toBeInTheDocument();
  });
});

// ── The governed-provider control ────────────────────────────────────────────────────────
//
// MASTER_EXECUTION_ROADMAP Phase 1 asked for an opt-in `default / on / blocked` switch. What can
// honestly ship is a READ-ONLY status control: the provider is resolved from the backend process
// environment (`ai.rs::resolve_provider`) and Phase 1's own security gate is "Desktop never holds
// lease/key/env", so a webview-writable control would hand the renderer the choice of whether its
// own turns are governed. The roadmap was amended to say that; these tests hold the amended
// criterion — all three states reported, none settable, and reachable by keyboard.
describe('Settings — the governed-provider control reports, and cannot set', () => {
  const control = () => screen.getByRole('switch');

  it('is keyboard-reachable, and says it is not operable rather than vanishing from the tab order', async () => {
    setup();
    await waitFor(() => expect(control()).toBeInTheDocument());
    // `disabled` would drop it out of the tab order, taking the state it exists to report with
    // it. `aria-disabled` keeps it focusable and announced.
    expect(control()).not.toBeDisabled();
    expect(control()).toHaveAttribute('aria-disabled', 'true');
    control().focus();
    expect(document.activeElement).toBe(control());
  });

  it('does not change state, and calls no backend writer, when activated', async () => {
    const user = userEvent.setup();
    setup();
    await waitFor(() => expect(control()).toBeInTheDocument());
    const before = control().getAttribute('aria-checked');
    const commandsBefore = invokeMock.mock.calls.length;
    await user.click(control());
    control().focus();
    await user.keyboard('{ }');
    await user.keyboard('{Enter}');
    expect(control().getAttribute('aria-checked')).toBe(before);
    // Nothing was written: no further IPC call of any kind was made by the interaction.
    expect(invokeMock.mock.calls.length).toBe(commandsBefore);
  });

  it('reports `default` when the resolved provider is ungoverned', async () => {
    mount(UNGOVERNED);
    await waitFor(() => expect(control()).toHaveAttribute('data-state', 'default'));
    expect(control()).toHaveAttribute('aria-checked', 'false');
    expect(control().getAttribute('aria-label')).toContain('Off');
  });

  it('reports `on` when the backend resolved the governed engine and it is ready', async () => {
    mount({ provider: 'governed-engine', model: 'py sidecar', ready: true, detail: 'ok', governed: true });
    await waitFor(() => expect(control()).toHaveAttribute('data-state', 'on'));
    expect(control()).toHaveAttribute('aria-checked', 'true');
    expect(control().getAttribute('aria-label')).toContain('On');
  });

  it('reports `blocked` — not `off` — when governed but the sidecar never became ready', async () => {
    mount({ provider: 'governed-engine', model: 'py sidecar', ready: false, detail: 'pending', governed: true });
    await waitFor(() => expect(control()).toHaveAttribute('data-state', 'blocked'));
    // Still on: the governed provider IS resolved and is refusing every turn. Calling that
    // "off" would print the same word for a refusing pipeline and an absent one.
    expect(control()).toHaveAttribute('aria-checked', 'true');
    expect(control().getAttribute('aria-label')).toContain('Blocked');
    expect(control().getAttribute('aria-label')).not.toContain('Off');
  });
});
