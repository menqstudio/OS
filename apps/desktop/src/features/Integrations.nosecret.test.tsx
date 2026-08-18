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
import { Integrations } from './Integrations';

/**
 * Phase 9's Definition of Done: *"No external secret stored on the desktop (auth handoff to
 * engine/operator)"*, and its checklist names the shape — *"contract test: no desktop secret."*
 *
 * `Integrations.honesty.test.tsx` already asserts the page **offers no credential field**. That is
 * the input half. This is the other half: **nothing the page sends carries one either.** A UI with
 * no credential input can still serialise a token it read from somewhere else, and "we never built
 * a text box for it" is not the same claim as "no secret crosses this boundary".
 *
 * It is the same shape as `agentsDispatch.nolease.test.ts` — a **whitelist** of the arguments each
 * command is allowed to carry, so the test fails when a new field appears rather than only when a
 * field someone thought to forbid appears.
 */
const ROW = {
  id: 'in-1', name: 'GitHub', provider: 'github', status: 'connected',
  createdAt: '1700000000000', updatedAt: '1700000000000',
};

/**
 * Every string that appears anywhere in a value, keys included.
 *
 * **Non-string leaves are visited too** (sixth audit `A-09` route 3, reopened by the eighth and
 * closed alongside `agentsDispatch.boundary.test.ts`). The earlier version pushed only
 * `typeof value === 'string'`, so a `number[]` of character codes decoded to text on the far side
 * while being invisible here — and this suite is the one Phase 9's DoD row cites.
 */
function flatten(value: unknown, out: string[] = []): string[] {
  if (typeof value === 'string') out.push(value);
  else if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    out.push(String(value));
  } else if (Array.isArray(value)) {
    const decoded = decodeCharCodes(value);
    if (decoded !== null) out.push(decoded);
    value.forEach((v) => flatten(v, out));
  } else if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) { out.push(k); flatten(v, out); }
  }
  return out;
}

/** `[116,111,107,101,110]` → `"token"`; `null` when the array is not all printable ASCII codes. */
function decodeCharCodes(list: readonly unknown[]): string | null {
  if (list.length === 0) return null;
  const codes: number[] = [];
  for (const v of list) {
    if (typeof v !== 'number' || !Number.isInteger(v) || v < 0x20 || v > 0x7e) return null;
    codes.push(v);
  }
  return String.fromCharCode(...codes);
}

/**
 * `api[-_ ]?key` caught one compound and missed the family (`pubkey`, `keystore`, `sessionkey`,
 * `keychain`) — the same route 2 the dispatch sweep carried. The `key` clause now takes an optional
 * prefix and suffix, so every compound is matched while `monkey` / `keyboard` / `keyword` are not.
 */
const SECRET_SHAPED =
  /secret|credential|token|password|bearer|private|(?<![a-z])(?:pub|api|access|secret|private|public|session|signing|host|ssh|gpg|master|root|enc|dec)?[-_ ]?keys?(?:tore|chain|file|pair|ring|id)?(?![a-z])/i;

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_integrations') return Promise.resolve([ROW]);
    if (cmd === 'set_integration_status') return Promise.resolve({ ...ROW, status: 'disconnected' });
    if (cmd === 'probe_integration') return Promise.reject(new Error('probe_integration not allowed'));
    return Promise.resolve(null);
  });
  return render(<AppProvider><ToastProvider><Integrations /></ToastProvider></AppProvider>);
}

/** Args of every command the page issued, by command name. */
function calls(): Array<[string, Record<string, unknown>]> {
  return invokeMock.mock.calls.map(([cmd, args]) => [String(cmd), (args ?? {}) as Record<string, unknown>]);
}

beforeEach(() => invokeMock.mockReset());

describe('Integrations — no external secret crosses this boundary', () => {
  it('sends nothing secret-shaped, on any command, at any depth', async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByText('GitHub');
    // Exercise the page's write path too, not only its read: a boundary is proven by what it
    // sends when the owner acts, not by what it sends while idle.
    const toggle = screen.queryByRole('button', { name: /disable|disconnect|անջատ|отключ/i });
    if (toggle) await user.click(toggle);
    await waitFor(() => expect(invokeMock).toHaveBeenCalled());

    for (const [cmd, args] of calls()) {
      const offenders = flatten(args).filter((s) => SECRET_SHAPED.test(s));
      expect(offenders, `command ${cmd} carried ${offenders.join(', ')}`).toEqual([]);
    }
  });

  it('each command carries only its declared arguments — a whitelist, not a blacklist', async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByText('GitHub');
    const toggle = screen.queryByRole('button', { name: /disable|disconnect|անջատ|отключ/i });
    if (toggle) await user.click(toggle);
    await waitFor(() => expect(invokeMock).toHaveBeenCalled());

    // A blacklist protects against the names we thought of. This fails the moment ANY new
    // argument appears on an integration command, which is when a reviewer should look.
    const ALLOWED: Record<string, string[]> = {
      list_integrations: [],
      set_integration_status: ['id', 'status'],
      probe_integration: ['id'],
      create_integration: ['input'],
    };
    for (const [cmd, args] of calls()) {
      if (!(cmd in ALLOWED)) continue;
      expect(Object.keys(args).sort(), `command ${cmd}`).toEqual(ALLOWED[cmd].sort());
    }
  });

  it('positive control: the page really did call the backend, so the sweep is not vacuous', async () => {
    setup();
    await screen.findByText('GitHub');
    await waitFor(() => expect(calls().some(([c]) => c === 'list_integrations')).toBe(true));
  });

  it('there is no field to type a secret into', async () => {
    // The input half, kept beside the output half so the two are read together. A boundary with
    // no way in and a boundary with no way out are different guarantees, and Phase 9 needs both.
    setup();
    await screen.findByText('GitHub');
    for (const box of screen.queryAllByRole('textbox')) {
      const name = (box.getAttribute('aria-label') ?? '') + (box.getAttribute('placeholder') ?? '');
      expect(SECRET_SHAPED.test(name), `a field named ${name}`).toBe(false);
      expect(box).not.toHaveAttribute('type', 'password');
    }
    expect(document.querySelector('input[type="password"]')).toBeNull();
  });
});
