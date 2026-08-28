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
    out.push(...decodeCharCodeRuns(value));
    value.forEach((v) => flatten(v, out));
  } else if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) { out.push(k); flatten(v, out); }
  }
  return out;
}

/**
 * The printable text a character-code array carries — ninth audit `I-03`.
 *
 * The superseded form returned `null` for the whole array the moment ONE element fell outside
 * `0x20`–`0x7e`, so a newline appended to the character-code array made it invisible again. Two
 * things are produced instead: every maximal printable RUN, so adjacency is preserved, and the
 * concatenation of all printable bytes with the non-printable ones removed, so a value interleaved
 * with separators cannot hide either. An array with no printable byte yields nothing at all, which
 * is what keeps the decode from becoming a wildcard that invents offenders.
 */
function decodeCharCodeRuns(list: readonly unknown[]): string[] {
  const out: string[] = [];
  let run = '';
  let all = '';
  for (const v of list) {
    if (typeof v === 'number' && Number.isInteger(v) && v >= 0x20 && v <= 0x7e) {
      run += String.fromCharCode(v);
      all += String.fromCharCode(v);
    } else if (run) {
      out.push(run);
      run = '';
    }
  }
  if (run) out.push(run);
  if (all && !out.includes(all)) out.push(all);
  return out;
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

  it('`I-03`: one byte outside the printable range no longer defeats the decode', () => {
    // Phase 9's DoD row cites this suite, so the escape the ninth audit found in the boundary
    // suite's decode has to be closed in this copy too: a single 0x0a made the all-or-nothing
    // form return null for the whole array, and the sweep went silent.
    const codes = Array.from('bearer-7f2a91').map((c) => c.charCodeAt(0));
    for (const bytes of [codes, [...codes, 0x0a], codes.flatMap((c) => [c, 0x0a])]) {
      expect(flatten({ smuggled: bytes })).toContain('bearer-7f2a91');
      expect(flatten({ smuggled: bytes }).filter((s) => SECRET_SHAPED.test(s)).length)
        .toBeGreaterThan(0);
    }
    // And still not a wildcard: an array with no printable byte decodes to nothing.
    expect(decodeCharCodeRuns([1, 2, 3, 999])).toEqual([]);
  });
});
