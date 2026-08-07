import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// The engine evidence-chain read ANSWERS here (state: 'ok') — the case the
// unreachable-path spec (Decisions.governance.test.tsx) does not cover. Two honesty
// defects lived in this branch:
//
//   * `records: []` was rendered with the "mirrored read-only" copy and painted the
//     evidence node with class `done` (mint/satisfied). Zero evidence read as
//     satisfied evidence.
//   * records are schema-shape-checked only, from whatever process the governed-
//     sidecar setting names, with no signature to verify — yet nothing on screen said
//     the mirror was unauthenticated.
//
// The reply shape is what the Rust mirror serializes, including `authenticated`.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { Decisions } from './Decisions';

const DECISION = {
  id: 'd-1',
  title: 'Ship the mirror',
  status: 'accepted',
  owner: 'gev',
  rationale: 'because',
  createdAt: '1000',
  updatedAt: '1000',
};

function mountWithChain(reply: unknown) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_decisions') return Promise.resolve([DECISION]);
    if (cmd === 'read_evidence_chain') return Promise.resolve(reply);
    return Promise.resolve(null);
  });
  return render(<AppProvider><Decisions /></AppProvider>);
}

/** The three lifecycle nodes of the evidence-chain strip, as [label, className]. */
function chainNodes(): [string, string][] {
  const chain = document.querySelector('.dec-chain-strip .chain');
  return Array.from(chain?.querySelectorAll('b') ?? []).map(
    (b) => [b.textContent ?? '', b.className] as [string, string],
  );
}

async function openEvidence() {
  await waitFor(() => expect(screen.getAllByText('Ship the mirror').length).toBeGreaterThan(0));
  fireEvent.click(screen.getByText('Open evidence'));
}

beforeEach(() => invokeMock.mockReset());

describe('Decisions — an EMPTY engine evidence chain is not satisfied evidence', () => {
  it('renders "no evidence" and never marks the evidence node done', async () => {
    mountWithChain({ state: 'ok', surface: 'evidenceChain', records: [], authenticated: false });
    await openEvidence();

    await waitFor(() => expect(screen.getByText('No evidence')).toBeInTheDocument());
    // The honest wording, not the "mirrored read-only" copy that implies evidence arrived.
    expect(screen.getByText(/empty chain is not a verified chain/i)).toBeInTheDocument();
    expect(screen.queryByText(/Mirrored read-only from the engine chain/i)).not.toBeInTheDocument();

    // The lifecycle node reads "no evidence" and carries NO `done` (mint/satisfied) class.
    const nodes = chainNodes();
    expect(nodes).toHaveLength(3);
    const [label, cls] = nodes[2];
    expect(label).toBe('no evidence');
    expect(cls).not.toContain('done');
    expect(cls).not.toContain('now');
  });
});

describe('Decisions — mirrored records are labelled unauthenticated', () => {
  it('shows the records but states the mirror is unauthenticated, and keeps the node un-lit', async () => {
    mountWithChain({
      state: 'ok',
      surface: 'evidenceChain',
      records: [{ event_id: 'ev-1' }, { event_id: 'ev-2' }],
      authenticated: false,
    });
    await openEvidence();

    // The real count is shown...
    await waitFor(() => expect(screen.getByText(/ENGINE EVIDENCE · 2/)).toBeInTheDocument());
    // ...alongside an explicit statement that nothing here was authenticated.
    expect(screen.getByText('UNAUTHENTICATED MIRROR')).toBeInTheDocument();
    expect(screen.getByText(/carry no signature/i)).toBeInTheDocument();

    // A green/satisfied node must not rest on an unauthenticated source.
    const [label, cls] = chainNodes()[2];
    expect(label).toBe('evidence · unverified');
    expect(cls).not.toContain('done');
  });

  it('lights the evidence node only when the backend reports authenticated records', async () => {
    // Not reachable today (the mirror always reports authenticated:false); this locks
    // the mapping so the UI follows the backend if a signature check ever lands.
    mountWithChain({
      state: 'ok',
      surface: 'evidenceChain',
      records: [{ event_id: 'ev-1' }],
      authenticated: true,
    });
    await openEvidence();

    await waitFor(() => expect(screen.getByText(/ENGINE EVIDENCE · 1/)).toBeInTheDocument());
    expect(screen.queryByText('UNAUTHENTICATED MIRROR')).not.toBeInTheDocument();
    const [label, cls] = chainNodes()[2];
    expect(label).toBe('evidence');
    expect(cls).toContain('done');
  });
});

describe("Decisions — the ENGINE's reason for an empty chain reaches the owner", () => {
  it('quotes the engine sentence, attributed, beside the honest empty state', async () => {
    // The mirror used to drop `empty_reason` / `known_task` / `source`, so an empty
    // chain rendered as a blank panel and the owner could not tell "there is nothing to
    // show" from "there is nothing to show BECAUSE the runtime has no such task".
    mountWithChain({
      state: 'ok',
      surface: 'evidenceChain',
      records: [],
      authenticated: false,
      engine: {
        emptyReason: "the orchestration runtime has no task 'd-1'",
        recordCount: 0,
        knownTask: false,
        sourceKind: 'signed-evidence-store',
      },
    });
    await openEvidence();

    // The honest empty state is still exactly what it was...
    await waitFor(() => expect(screen.getByText('No evidence')).toBeInTheDocument());
    expect(screen.getByText(/empty chain is not a verified chain/i)).toBeInTheDocument();

    // ...and now the engine's own words sit BESIDE it, attributed to the engine and
    // quoted verbatim rather than restated in the page's voice.
    expect(screen.getByText('The engine’s own account:')).toBeInTheDocument();
    const quote = screen.getByText("the orchestration runtime has no task 'd-1'");
    expect(quote.tagName).toBe('Q');
    expect(screen.getByText(/never heard of this decision id/i)).toBeInTheDocument();
    expect(screen.getByText('signed-evidence-store')).toBeInTheDocument();

    // Explaining the emptiness must not light anything up.
    const [label, cls] = chainNodes()[2];
    expect(label).toBe('no evidence');
    expect(cls).not.toContain('done');
  });

  it('never prints an explanation of emptiness beside actual records', async () => {
    // A reply that contradicts itself (records AND "it is empty because...") shows the
    // records; the sentence about emptiness is dropped, not displayed under them.
    mountWithChain({
      state: 'ok',
      surface: 'evidenceChain',
      records: [{ event_id: 'ev-1' }],
      authenticated: false,
      engine: {
        emptyReason: 'no evidence event has been recorded in this store yet',
        recordCount: 1,
        sourceKind: 'signed-evidence-store',
      },
    });
    await openEvidence();

    await waitFor(() => expect(screen.getByText(/ENGINE EVIDENCE · 1/)).toBeInTheDocument());
    expect(screen.queryByText(/no evidence event has been recorded/i)).not.toBeInTheDocument();
    expect(screen.queryByText('The engine’s own account:')).not.toBeInTheDocument();
    // Provenance still travels, and the unauthenticated notice still governs it.
    expect(screen.getByText('signed-evidence-store')).toBeInTheDocument();
    expect(screen.getByText('UNAUTHENTICATED MIRROR')).toBeInTheDocument();
  });

  it("keeps a refusal's own reason and grows no explanation of emptiness", async () => {
    mountWithChain({
      state: 'blocked',
      surface: 'evidenceChain',
      reason: 'this runtime is not bound to an evidence store',
      engine: { emptyReason: 'the orchestration runtime holds no tasks' },
    });
    await openEvidence();

    await waitFor(() => expect(screen.getByText('Evidence sealed')).toBeInTheDocument());
    expect(screen.getByText(/not bound to an evidence store/)).toBeInTheDocument();
    // "I could not look" must never be dressed as "I looked and found nothing".
    expect(screen.queryByText('The engine’s own account:')).not.toBeInTheDocument();
    expect(screen.queryByText(/holds no tasks/)).not.toBeInTheDocument();
  });
});
