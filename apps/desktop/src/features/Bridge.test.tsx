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
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd in routes) {
      const v = routes[cmd];
      return v instanceof Error ? Promise.reject(v) : Promise.resolve(v);
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

    await outcome('No verdict exists');
    expect(screen.queryByText('Verified by the broker')).not.toBeInTheDocument();
    // The forged body is never rendered — an illegal frame is refused, not displayed as an answer.
    expect(screen.queryByText('trust me')).not.toBeInTheDocument();
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
