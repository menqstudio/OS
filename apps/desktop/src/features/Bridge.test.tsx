// The bridge panel's honesty contract, at the screen.
//
// Every assertion here is about a thing the panel must NOT say: it must not call an empty mirror
// satisfied, must not present unauthenticated records as proof, must not render "the broker was never
// reached" with the words used for "the broker refused", and must not reach a Verified affordance
// without a real broker committed frame.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { BridgePanel } from './Bridge';
import { STR as BR_STR } from './Bridge.strings';
import { RESULT_PROTOCOL, TRUSTED_VERIFIED } from '../services/governedTurn';

const CONVERSATION = {
  id: 'conv-1', kind: 'direct', title: 'A real conversation',
  messageCount: 1, lastMessageAt: null, createdAt: '1', updatedAt: '1',
};

// The outcome only appears after the click's async round-trip settles. The default 1s window is enough
// on an idle machine and NOT enough on a loaded one, which makes these assertions flaky for a reason
// that has nothing to do with what they test. Wait longer instead.
const SETTLE = { timeout: 5000 } as const;

/** Wait for a click-driven outcome to appear, tolerant of a loaded machine. */
const outcome = (text: string) =>
  waitFor(() => expect(screen.getByText(text)).toBeInTheDocument(), SETTLE);

/** Route each command to a canned reply; anything unrouted resolves null (fail-closed by default). */
function mount(routes: Record<string, unknown>, opts: { taskId?: string } = {}) {
  invokeMock.mockImplementation((cmd: string, args?: { request?: { client_request_id?: string } }) => {
    if (cmd in routes) {
      const v = routes[cmd];
      if (v instanceof Error) return Promise.reject(v);
      // A real broker ECHOES the request's `client_request_id`, and the renderer now refuses a
      // reply that names another one. The fixtures below write `'x'` where the echo goes; it is
      // filled in here, from the request actually sent, so they stay about what they test.
      if (cmd === 'governed_turn_execute' && v && typeof v === 'object'
        && (v as { client_request_id?: unknown }).client_request_id === 'x') {
        return Promise.resolve({ ...v, client_request_id: args?.request?.client_request_id });
      }
      return Promise.resolve(v);
    }
    return Promise.resolve(null);
  });
  return render(<AppProvider><BridgePanel taskId={opts.taskId} /></AppProvider>);
}

beforeEach(() => {
  invokeMock.mockReset();
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
});

describe('BridgePanel — the previously unreachable governance mirrors', () => {
  it('reads BOTH the engine decision ledger and the verifier verdicts (the two dead commands)', async () => {
    mount({ list_conversations: [CONVERSATION] }, { taskId: 'd-7' });
    await waitFor(() => {
      const cmds = invokeMock.mock.calls.map((c) => c[0]);
      expect(cmds).toContain('read_decision_ledger');
      expect(cmds).toContain('read_verifier_verdicts');
    });
    // The verdict mirror is scoped to the decision the page has selected.
    const verdictCall = invokeMock.mock.calls.find((c) => c[0] === 'read_verifier_verdicts');
    expect(verdictCall?.[1]).toEqual({ taskId: 'd-7' });
  });

  it('an `ok` mirror carrying zero records reads as an absence, not a satisfied surface', async () => {
    mount({
      list_conversations: [CONVERSATION],
      read_decision_ledger: { state: 'ok', surface: 'decisionLedger', records: [], authenticated: false },
    });
    await waitFor(() => expect(screen.getByText('answered · nothing to mirror')).toBeInTheDocument());
    // Nothing on screen labels this mirror as unauthenticated-but-present, because nothing is present.
    expect(screen.queryByText('ORIGIN NOT AUTHENTICATED')).not.toBeInTheDocument();
  });

  it('records that arrived are counted AND labelled as an unauthenticated origin', async () => {
    mount({
      list_conversations: [CONVERSATION],
      read_decision_ledger: {
        state: 'ok', surface: 'decisionLedger',
        records: [{ id: 'a' }, { id: 'b' }, { id: 'c' }], authenticated: false,
      },
    });
    await waitFor(() => expect(screen.getByText('records · 3')).toBeInTheDocument());
    expect(screen.getByText('ORIGIN NOT AUTHENTICATED')).toBeInTheDocument();
    expect(screen.getByText(/mirror data, not proof/i)).toBeInTheDocument();
  });

  it('an unreachable mirror says it was not reached and surfaces the machine reason', async () => {
    mount({
      list_conversations: [CONVERSATION],
      read_decision_ledger: new Error('broker_unavailable: no socket'),
    });
    await waitFor(() => expect(screen.getAllByText('not reached').length).toBeGreaterThan(0));
    expect(screen.getByText(/broker_unavailable: no socket/)).toBeInTheDocument();
  });
});

describe('BridgePanel — the governed turn, previously called by nothing', () => {
  it('sends nothing on mount; the governed turn is only ever user-initiated', async () => {
    mount({ list_conversations: [CONVERSATION] });
    await waitFor(() => expect(screen.getByText('A real conversation')).toBeInTheDocument());
    expect(invokeMock.mock.calls.map((c) => c[0])).not.toContain('governed_turn_execute');
    // And it says so, rather than implying a broker state it has not observed.
    expect(screen.getByText(/Nothing has been sent yet/)).toBeInTheDocument();
  });

  it('is never offered before it works — the send button is live the moment a conversation shows', async () => {
    // Regression: the selected conversation used to be copied into state by an effect, which left one
    // committed frame where the list was on screen and nothing was selected. In that frame the button
    // was disabled and a click did nothing at all — a control that looks ready and silently isn't.
    mount({ list_conversations: [CONVERSATION] });
    await waitFor(() => expect(screen.getByText('A real conversation')).toBeInTheDocument());
    expect(screen.getByText('Send one governed turn').closest('button')).not.toBeDisabled();
  });

  it('a transport failure renders "no verdict exists" — NOT the refusal wording', async () => {
    mount({
      list_conversations: [CONVERSATION],
      governed_turn_execute: new Error(
        'broker_unsupported_platform: no governed-broker IPC transport is implemented for this host (os=win32).',
      ),
    });
    await waitFor(() => expect(screen.getByText('A real conversation')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Send one governed turn'));

    await outcome('No verdict exists');
    // The two things this must never claim:
    expect(screen.queryByText('The broker refused this turn')).not.toBeInTheDocument();
    expect(screen.queryByText('Verified by the broker')).not.toBeInTheDocument();
    // It names the non-decision and explains it in plain language.
    expect(screen.getByText('broker_unsupported_platform')).toBeInTheDocument();
    expect(screen.getByText(/no governed-broker transport compiled in/i)).toBeInTheDocument();
    expect(screen.getByText(/absence of an answer/i)).toBeInTheDocument();
  });

  it('a real broker refusal renders as a refusal, with its closed reason', async () => {
    mount({
      list_conversations: [CONVERSATION],
      governed_turn_execute: {
        protocol: RESULT_PROTOCOL, status: 'blocked', client_request_id: 'x',
        broker_turn_id: 'bt-3', conversation_id: 'conv-1', reason: 'upstream_blocked',
      },
    });
    await waitFor(() => expect(screen.getByText('A real conversation')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Send one governed turn'));

    await outcome('The broker refused this turn');
    expect(screen.getByText('upstream_blocked')).toBeInTheDocument();
    // A refusal is a decision, so it must NOT be reported as the absence of one.
    expect(screen.queryByText('No verdict exists')).not.toBeInTheDocument();
    expect(screen.queryByText('Verified by the broker')).not.toBeInTheDocument();
  });

  it('a reply that merely CLAIMS trusted_verified never reaches the Verified affordance', async () => {
    mount({
      list_conversations: [CONVERSATION],
      governed_turn_execute: {
        // Wrong protocol: not a broker result frame, however verified it says it is.
        protocol: 'brops.forged.v1', status: 'committed', client_request_id: 'x',
        broker_turn_id: 'bt-3', conversation_id: 'conv-1',
        message: {
          message_id: 'm', role: 'assistant', author: 'Bro', body: 'trust me',
          created_at_ms: 1, trust_state: TRUSTED_VERIFIED,
        },
      },
    });
    await waitFor(() => expect(screen.getByText('A real conversation')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Send one governed turn'));

    await outcome('Reply not accepted by this app');
    expect(screen.queryByText('Verified by the broker')).not.toBeInTheDocument();
    // The forged body is never rendered — an illegal frame is refused, not displayed as an answer.
    expect(screen.queryByText('trust me')).not.toBeInTheDocument();
  });

  it('a broker commit under demonstration_custody is never Verified, and is said to be what it is', async () => {
    // What a configured deployment commits today: a real broker frame, durably committed, whose label
    // is not `trusted_verified`. The renderer rejects it by design. It used to render "No verdict
    // exists / No broker allowed or refused this turn" — false for a turn the broker DID commit —
    // and then "Reply not accepted by this app … does not establish that nothing was committed",
    // which hedged about a thing the frame states outright.
    mount({
      list_conversations: [CONVERSATION],
      governed_turn_execute: {
        protocol: RESULT_PROTOCOL, status: 'committed', client_request_id: 'x',
        broker_turn_id: 'bt-5', conversation_id: 'conv-1',
        message: {
          message_id: 'm', role: 'assistant', author: 'Bro', body: 'a demonstration answer',
          created_at_ms: 1, trust_state: 'demonstration_custody',
        },
      },
    });
    await waitFor(() => expect(screen.getByText('A real conversation')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Send one governed turn'));

    await outcome('Committed by the broker — not accepted here');
    // The page says the broker committed, under which custody, and that this app declines it.
    expect(screen.getByText(/it committed this turn, under demonstration custody/)).toBeInTheDocument();
    expect(screen.getByText(/That is a real broker verdict/)).toBeInTheDocument();
    expect(screen.getByText(/This app accepts only a turn marked trusted_verified, so the reply is not displayed/))
      .toBeInTheDocument();
    expect(screen.getByText('demonstration_custody')).toBeInTheDocument();
    expect(screen.getByText('bt-5')).toBeInTheDocument();
    // Still no Verified affordance and no body: the rejection itself is unchanged.
    expect(screen.queryByText('Verified by the broker')).not.toBeInTheDocument();
    expect(screen.queryByText('a demonstration answer')).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain('a demonstration answer');
    // And none of the three sentences that would be false about it.
    expect(screen.queryByText('No verdict exists')).not.toBeInTheDocument();
    expect(screen.queryByText(/No broker allowed or refused/)).not.toBeInTheDocument();
    expect(screen.queryByText('Reply not accepted by this app')).not.toBeInTheDocument();
    expect(screen.queryByText('The broker refused this turn')).not.toBeInTheDocument();
  });

  it('says the same in Armenian and in Russian — neither language denies the commit or shows the reply', async () => {
    const { STR } = await import('./Bridge.strings');
    for (const lang of ['hy', 'ru'] as const) {
      expect(STR.outcomeCommitNotAccepted[lang]).not.toBe(STR.outcomeCommitNotAccepted.en);
      expect(STR.outcomeCommitNotAcceptedBody[lang]).toContain('demonstration custody');
      expect(STR.outcomeCommitNotAcceptedBody[lang]).toContain('trusted_verified');
      expect(STR.outcomeCommitNotAcceptedBody[lang]).not.toBe(STR.outcomeUnavailableBody[lang]);
    }
  });

  it('a genuine broker committed frame IS shown as verified (the mapping the gate protects)', async () => {
    // Not reachable on this build — the platform gate is false and the broker keeps the fail-closed
    // executor. This locks the mapping so the ONLY thing that can light "Verified" is a real frame.
    mount({
      list_conversations: [CONVERSATION],
      governed_turn_execute: {
        protocol: RESULT_PROTOCOL, status: 'committed', client_request_id: 'x',
        broker_turn_id: 'bt-4', conversation_id: 'conv-1',
        message: {
          message_id: 'm', role: 'assistant', author: 'Bro', body: 'a governed answer',
          created_at_ms: 1, trust_state: TRUSTED_VERIFIED,
        },
      },
    });
    await waitFor(() => expect(screen.getByText('A real conversation')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Send one governed turn'));

    await outcome('Verified by the broker');
    expect(screen.getByText('a governed answer')).toBeInTheDocument();
  });

  it('with no conversation to address it offers no send action at all', async () => {
    mount({ list_conversations: [] });
    await waitFor(() => expect(screen.getByText(/nothing to send/i)).toBeInTheDocument());
    expect(screen.queryByText('Send one governed turn')).not.toBeInTheDocument();
  });
});

describe('BridgePanel — outside a Tauri runtime', () => {
  it('says the backend is absent rather than blaming the broker', async () => {
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
    mount({ list_conversations: [CONVERSATION] });
    await waitFor(() => expect(screen.getByText('A real conversation')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Send one governed turn'));

    await outcome('No verdict exists');
    expect(screen.getByText('no_desktop_backend')).toBeInTheDocument();
    // The proxy command does not exist here, so it must not have been called.
    expect(invokeMock.mock.calls.map((c) => c[0])).not.toContain('governed_turn_execute');
  });
});

// The panel is embedded under the Decisions table AND mounted alone on the `bridge` route. On the
// second there is no table above it, and the note said "the local decision table shown above".
describe('the ledger note does not point at something that may not be on the page', () => {
  it.each(['en', 'hy', 'ru'] as const)('names the table instead of a position (%s)', (lang) => {
    expect(BR_STR.surfaceLedgerNote[lang]).not.toMatch(/shown above|վերևի լոկալ|таблица выше/);
    expect(BR_STR.surfaceLedgerNote[lang]).toMatch(/Decisions page|«Որոշումներ» էջի|странице «Решения»/);
  });
});

// The panel's accessible name was `STR.panelTitle.en` whatever the language.
describe('the panel is named in the language of the page', () => {
  it('uses the Armenian title when the page is Armenian', async () => {
    localStorage.setItem('brops.lang', JSON.stringify('hy'));
    try {
      const { container } = mount({});
      const section = container.querySelector('section.v-bridge')!;
      expect(section.getAttribute('aria-label')).toBe(BR_STR.panelTitle.hy);
      expect(BR_STR.panelTitle.hy).not.toBe(BR_STR.panelTitle.en);
    } finally {
      localStorage.removeItem('brops.lang');
    }
  });
});

// `broker_transport_failed` is "connected to the broker, but the framed exchange failed". The
// request may already have been written when it did, and this panel cannot know what the broker
// did with it. It was told the same thing as a broker that was never reached: "No verdict exists
// — no broker allowed or refused this turn".
describe('a failure AFTER the broker was connected to is not "nobody decided"', () => {
  it.each([
    'broker_transport_failed: connected to the broker, but the framed exchange failed',
    'socket hang up',
  ])('%s', async (message) => {
    mount({ list_conversations: [CONVERSATION], governed_turn_execute: new Error(message) });
    await waitFor(() => expect(screen.getByText('A real conversation')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Send one governed turn'));
    await waitFor(() => expect(screen.getByText(/No verdict was received/)).toBeInTheDocument());
    expect(screen.queryByText(/No broker allowed or refused/)).not.toBeInTheDocument();
    expect(screen.getByText(/does not establish that the broker decided nothing/)).toBeInTheDocument();
  });

  it('a broker that was never reached still says nobody decided', async () => {
    mount({ list_conversations: [CONVERSATION], governed_turn_execute: new Error('broker_unavailable: no socket') });
    await waitFor(() => expect(screen.getByText('A real conversation')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Send one governed turn'));
    await waitFor(() => expect(screen.getByText(/No broker allowed or refused/)).toBeInTheDocument());
    expect(screen.queryByText(/No verdict was received/)).not.toBeInTheDocument();
  });
});

// The verdict mirror is read per decision. `useAsync` keeps the previous answer while the next
// read is in flight, and the row printed it: under the newly selected decision stood the record
// count of the one before.
describe('the verdict mirror does not show the previous decision\'s count', () => {
  it('says it is reading while the read for the new decision is in flight', async () => {
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    const twoRecords = {
      protocol: 'brops.governance-read.v1', surface: 'verifier_verdicts', state: 'ok',
      records: [{ verdict: 'GREEN', task_id: 'd-1' }, { verdict: 'GREEN', task_id: 'd-1' }],
      authenticated: false,
    };
    invokeMock.mockImplementation((cmd: string, args?: { taskId?: string }) => {
      if (cmd === 'read_verifier_verdicts') {
        return args?.taskId === 'd-1' ? Promise.resolve(twoRecords) : new Promise(() => { /* in flight */ });
      }
      return Promise.resolve(null);
    });
    const { rerender, container } = render(<AppProvider><BridgePanel taskId="d-1" /></AppProvider>);
    const row = () => Array.from(container.querySelectorAll('.br-row'))
      .find((r) => /verdict/i.test(r.textContent ?? ''))!;
    await waitFor(() => expect(row().textContent).toMatch(/records · 2/));

    rerender(<AppProvider><BridgePanel taskId="d-2" /></AppProvider>);
    await waitFor(() => expect(invokeMock.mock.calls.some(
      (c) => c[0] === 'read_verifier_verdicts' && (c[1] as { taskId?: string })?.taskId === 'd-2')).toBe(true));
    expect(row().textContent).not.toMatch(/records · 2/);
    expect(row().textContent).toMatch(/reading…/);
  });
});
