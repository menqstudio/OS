import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// The governance read-path chain in the Notifications gate panel. One honesty defect
// lived here: the FIRST node (ENGINE) carried the `done` (mint/satisfied) class
// unconditionally, so a `blocked` or `unreachable` read — the Phase-2 steady state —
// still painted the engine leg of the chain as satisfied. The engine had answered
// nothing at all.
//
// The fix follows the prior art in Decisions.evidence.test.tsx: every node maps to a
// fact from the real GovernanceRead, and `done` is earned, never assumed.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Notifications } from './Notifications';

const NOTE = {
  id: 'n-1',
  kind: 'system',
  severity: 'info',
  title: 'Nightly sweep finished',
  body: 'Nothing to report.',
  entityType: null,
  entityId: null,
  readAt: null,
  createdAt: '1700000000000',
};

/** Mount with a specific `read_evidence_chain` outcome. `reject` models the transport
 *  failure the service maps to `unreachable`. */
function mountWithChain(chain: { reply?: unknown; reject?: string }) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_notifications') return Promise.resolve([NOTE]);
    if (cmd === 'read_evidence_chain') {
      return chain.reject
        ? Promise.reject(new Error(chain.reject))
        : Promise.resolve(chain.reply);
    }
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Notifications />
      </ToastProvider>
    </AppProvider>,
  );
}

/** The read-path chain nodes as [label, className]. */
function chainNodes(): [string, string][] {
  const chain = document.querySelector('.nsig-gate-chain');
  return Array.from(chain?.querySelectorAll('b') ?? []).map(
    (b) => [b.textContent ?? '', b.className] as [string, string],
  );
}

/** Wait until the gate panel has settled on a resolved read. */
async function settled() {
  await waitFor(() => expect(chainNodes()[0]?.[1]).toContain('done'));
}

// Rendering a whole feature page under jsdom can exceed the 5s default on a loaded
// machine. The assertions below are about honesty, not speed — give them room so a
// slow environment cannot be mistaken for a regression.
vi.setConfig({ testTimeout: 30000 });

beforeEach(() => invokeMock.mockReset());

describe('Notifications — an UNREACHABLE governance read never lights the engine node', () => {
  it('leaves ENGINE un-lit and says the chain is unreachable', async () => {
    mountWithChain({ reject: 'broker_unavailable' });
    await settled();

    const nodes = chainNodes();
    expect(nodes).toHaveLength(3);

    // READ is the desktop's own call — it genuinely completed.
    expect(nodes[0][0]).toBe('READ');
    expect(nodes[0][1]).toContain('done');

    // The engine answered nothing. This node used to be hard-coded `done`.
    expect(nodes[1][0]).toBe('ENGINE · unreachable');
    expect(nodes[1][1]).not.toContain('done');
    expect(nodes[1][1]).not.toContain('now');

    // Nothing was mirrored either.
    expect(nodes[2][1]).not.toContain('done');
  });
});

describe('Notifications — a BLOCKED governance read never lights the engine node', () => {
  it('leaves ENGINE un-lit and names the refusal', async () => {
    mountWithChain({
      reply: { state: 'blocked', surface: 'evidenceChain', reason: 'governed wall refused the read' },
    });
    await settled();

    const nodes = chainNodes();
    expect(nodes[1][0]).toBe('ENGINE · sealed');
    expect(nodes[1][1]).not.toContain('done');
    expect(nodes[2][1]).not.toContain('done');

    // The refusal reason is on screen, not only in the node label.
    expect(screen.getByText(/governed wall refused the read/)).toBeInTheDocument();
  });
});

describe('Notifications — an EMPTY ok read is not a mirrored stream', () => {
  it('lights ENGINE (it answered) but never the mirror node', async () => {
    mountWithChain({
      reply: { state: 'ok', surface: 'evidenceChain', records: [], authenticated: false },
    });
    await settled();

    const nodes = chainNodes();
    // The engine really did answer, so this leg is earned.
    expect(nodes[1][0]).toBe('ENGINE');
    expect(nodes[1][1]).toContain('done');

    // Zero events is the absence of a stream, not a mirrored one.
    expect(nodes[2][0]).toBe('MIRROR · no events');
    expect(nodes[2][1]).not.toContain('done');
    expect(nodes[2][1]).not.toContain('now');
  });
});

describe('Notifications — UNAUTHENTICATED mirrored records are not verified records', () => {
  it('shows the real count but leaves the mirror node un-lit and labelled unverified', async () => {
    mountWithChain({
      reply: {
        state: 'ok',
        surface: 'evidenceChain',
        records: [{ event_id: 'e-1' }, { event_id: 'e-2' }],
        authenticated: false,
      },
    });
    await settled();

    // The real count is stated...
    await waitFor(() => expect(screen.getByText(/^2 /)).toBeInTheDocument());
    // ...alongside an explicit statement that nothing here was authenticated.
    expect(screen.getByText(/carry no signature/i)).toBeInTheDocument();

    const nodes = chainNodes();
    expect(nodes[2][0]).toBe('MIRROR · unverified');
    expect(nodes[2][1]).not.toContain('done');
  });

  it('lights the mirror node ONLY when the backend reports authenticated records', async () => {
    // Not reachable today (the mirror always reports authenticated:false); this locks
    // the mapping so the UI follows the backend if a signature check ever lands.
    mountWithChain({
      reply: {
        state: 'ok',
        surface: 'evidenceChain',
        records: [{ event_id: 'e-1' }],
        authenticated: true,
      },
    });
    await settled();

    const nodes = chainNodes();
    expect(nodes[2][0]).toBe('MIRROR');
    expect(nodes[2][1]).toContain('done');
    expect(screen.queryByText(/carry no signature/i)).not.toBeInTheDocument();
  });
});

describe("Notifications — the ENGINE's reason for an empty stream reaches the owner", () => {
  it('quotes the engine sentence, attributed, without lighting the mirror node', async () => {
    mountWithChain({
      reply: {
        state: 'ok',
        surface: 'evidenceChain',
        records: [],
        authenticated: false,
        engine: {
          emptyReason: 'the orchestration runtime holds no tasks, so nothing has been recorded',
          recordCount: 0,
          sourceKind: 'signed-evidence-store',
        },
      },
    });
    await settled();

    // The honest empty wording stays...
    expect(screen.getByText(/empty stream is not a verified one/i)).toBeInTheDocument();
    // ...and the engine's own explanation now sits beside it, attributed and quoted.
    expect(screen.getByText('The engine’s own account:')).toBeInTheDocument();
    const quote = screen.getByText(
      'the orchestration runtime holds no tasks, so nothing has been recorded',
    );
    expect(quote.tagName).toBe('Q');
    expect(screen.getByText('signed-evidence-store')).toBeInTheDocument();

    // An explanation is not a stream: the mirror node stays un-lit.
    const nodes = chainNodes();
    expect(nodes[2][0]).toBe('MIRROR · no events');
    expect(nodes[2][1]).not.toContain('done');
  });

  it("shows a refusal's own reason and no explanation of emptiness", async () => {
    mountWithChain({
      reply: {
        state: 'blocked',
        surface: 'evidenceChain',
        reason: 'BROPS_GOVERNANCE_STATE_DIR is unset',
        engine: { emptyReason: 'the orchestration runtime holds no tasks' },
      },
    });
    await settled();

    expect(screen.getByText(/BROPS_GOVERNANCE_STATE_DIR is unset/)).toBeInTheDocument();
    expect(screen.queryByText('The engine’s own account:')).not.toBeInTheDocument();
    expect(screen.queryByText(/holds no tasks/)).not.toBeInTheDocument();
  });
});
