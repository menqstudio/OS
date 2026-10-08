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

// The running build's own name and version come through the Tauri app plugin. Mocked here so a
// test can make the build answer, or not; the default is "did not answer".
const appMock = { name: vi.fn<() => Promise<unknown>>(), version: vi.fn<() => Promise<unknown>>() };
vi.mock('@tauri-apps/api/app', () => ({
  getName: () => appMock.name(),
  getVersion: () => appMock.version(),
}));

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
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

beforeEach(() => {
  invokeMock.mockReset();
  appMock.name.mockReset().mockRejectedValue(new Error('app.name not allowed'));
  appMock.version.mockReset().mockRejectedValue(new Error('app.version not allowed'));
});

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

// ── The System panel's identity, readiness and persistence ───────────────────────────────
//
// The probe (`settingsIdentity.ts`), the strings and three comments all said the literals had
// been replaced. The JSX still rendered a fixed product name and a fixed version — for a build
// that reports `BroPS` / `0.1.0` — and `reported`, `identityReason`, `prefsPersisted` and
// `sysPill` were computed and used by nothing. The logic half had landed; the JSX half had not.
describe('Settings — the System panel shows what the running build reports', () => {
  const sysRow = (label: string) =>
    Array.from(document.querySelectorAll('.set-sys .sys-row'))
      .find((r) => r.querySelector('.sys-k')?.textContent === label)
      ?.querySelector('b')?.textContent ?? '';

  it('renders the name and version the build reported', async () => {
    appMock.name.mockResolvedValue('BroPS');
    appMock.version.mockResolvedValue('0.1.0');
    setup();
    await waitFor(() => expect(sysRow('Product')).toBe('BroPS'));
    expect(sysRow('Version')).toBe('0.1.0');
    expect(screen.getByText(/read from the running application build/i)).toBeInTheDocument();
    expect(document.querySelector('.set-sys')?.textContent).not.toMatch(/MENQ OS|v0\.9/);
  });

  it('says the build did not report, with the reason, rather than printing a fixed label', async () => {
    setup();
    await waitFor(() => expect(sysRow('Product')).toBe('Not reported by this build'));
    expect(sysRow('Version')).toBe('Not reported by this build');
    expect(screen.getByText(/could not read the application name and version/i)).toBeInTheDocument();
    expect(document.querySelector('.set-sys')?.textContent).toMatch(/Reason: .*not allowed/);
    expect(document.querySelector('.set-sys')?.textContent).not.toMatch(/MENQ OS|v0\.9/);
  });

  it('half an identity is no identity', async () => {
    appMock.name.mockResolvedValue('BroPS');
    appMock.version.mockResolvedValue('');
    setup();
    await waitFor(() => expect(sysRow('Version')).toBe('Not reported by this build'));
    expect(sysRow('Product')).toBe('Not reported by this build');
  });

  it('the source carries no product-name or version literal', () => {
    const src = readFileSync(resolve(process.cwd(), 'src/features/Settings.tsx'), 'utf8')
      // Comments may describe the old defect; rendered JSX and code may not contain it.
      .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
      .replace(/^\s*\/\/.*$/gm, '');
    expect(src).not.toMatch(/MENQ OS/);
    expect(src).not.toMatch(/v0\.9/);
  });
});

describe('Settings — unknown readiness is not "Not ready"', () => {
  const sysPillText = () => document.querySelector('.set-sys .sec-head .pill')?.textContent ?? '';

  it('a failed status read reads Unknown', async () => {
    mount('reject');
    await waitFor(() => expect(sysPillText()).toBe('Unknown'));
  });

  it('no backend at all reads Unknown', async () => {
    mount(UNGOVERNED, false);
    await waitFor(() => expect(sysPillText()).toBe('Unknown'));
  });

  it('a backend that says ready reads Ready, and one that says not ready reads Not ready', async () => {
    const { unmount } = mount(UNGOVERNED);
    await waitFor(() => expect(sysPillText()).toBe('Ready'));
    unmount();
    mount({ ...UNGOVERNED, ready: false });
    await waitFor(() => expect(sysPillText()).toBe('Not ready'));
  });
});

describe('Settings — says whether the preferences it offers are actually kept', () => {
  it('states that they are stored on this device when the probe round-trips', async () => {
    setup();
    await waitFor(() => expect(screen.getByText(/Checked just now: this window can write to local storage/)).toBeInTheDocument());
    expect(screen.queryByText(/NOT SAVED/)).not.toBeInTheDocument();
  });

  it('says NOT SAVED, as an alert and with the reason, when storage is unwritable', async () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    try {
      setup();
      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent(/NOT SAVED: local storage is not writable/);
      expect(screen.getByText('QuotaExceededError')).toBeInTheDocument();
      expect(screen.queryByText(/Checked just now/)).not.toBeInTheDocument();
    } finally {
      spy.mockRestore();
    }
  });
});

// The governed provider's `ready` is a hard-coded `false` in `ai_status` — nothing probes a
// sidecar. The blocked panel nonetheless said the sidecar "did not become ready", called it
// "misconfigured", gave three steps to "restore" it and a Re-check button that re-read a constant.
describe('Settings — the blocked governed provider is described as what it is', () => {
  const GOVERNED_UNPROVISIONED = {
    provider: 'governed-engine', model: 'm', ready: false, governed: true,
    detail: 'governed_verification_unconfigured — missing provisioning, not a check that ran and failed.',
  };

  it('shows the backend\'s own reason and claims no probe, no misconfiguration and no re-check', async () => {
    mount(GOVERNED_UNPROVISIONED);
    await waitFor(() => expect(document.querySelector('.set-blocked')).not.toBeNull());
    const panel = document.querySelector('.set-blocked')!;
    const text = panel.textContent ?? '';
    expect(text).toContain(GOVERNED_UNPROVISIONED.detail);
    expect(text).not.toMatch(/misconfigured/i);
    expect(text).not.toMatch(/did not become ready/i);
    expect(text).toMatch(/not provisioned/i);
    // A button that re-reads a value the backend hard-codes measures nothing.
    expect(screen.queryByRole('button', { name: 'Re-check' })).toBeNull();
  });
});
