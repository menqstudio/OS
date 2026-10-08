import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';

// Mock the Tauri IPC boundary with a call-tracking spy so the tests can assert
// BOTH what the page renders AND — the cardinal invariant — which backend commands
// it does (and does NOT) send. The gate is this app's OWN approval ledger (local SQLite):
// grant goes to `confirm_approval`, which the backend adjudicates behind a native dialog
// the webview cannot forge; deny goes to the fail-safe `reject_approval`. Escalate is a
// third, non-verdict action wired to a real backend command that marks the row A3 without
// granting or denying — and leaves it undecidable.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (cmd: string, args?: unknown) => invokeMock(cmd, args),
  Channel: class {},
}));

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Approvals } from './Approvals';
import { POPULATED } from './pages.fixtures';
import { parseTrigger } from './automationsGovernance';
import { parseTimestamp } from './timestamps';
import type { Approval, Automation, Conversation } from '../domain/entities';
import {
  APPROVAL_ACTIONS, DENIED_DECIDE_COMMAND, WITHHELD_MARKERS, bucketSum, classifyApproval,
  countQueue, missingGrantMarkers, readRejection, readReply,
} from './approvalsAuthority';

// One real, actionable pending approval (the shape the desktop `list_approvals`
// command returns) — deliberately the high-risk external-email action.
const PENDING = {
  id: 'ap-1',
  actionType: 'Send external email',
  target: 'vendor@example.com',
  level: 'A3',
  riskLevel: 'high',
  status: 'pending',
  requestedBy: 'A3',
  decisionNote: null,
  entityType: null,
  entityId: null,
  requestedAt: '1700000000000',
  decidedAt: null,
};

function setup(approvals: unknown[] = [PENDING]) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_approvals') return Promise.resolve(approvals);
    // The engine approval-QUEUE read is the honest Phase-2 steady state: unreachable.
    if (cmd === 'read_engine_approval_queue') return Promise.reject(new Error('broker_unavailable'));
    if (cmd === 'confirm_approval') return Promise.resolve(null);
    if (cmd === 'reject_approval') return Promise.resolve(null);
    if (cmd === 'escalate_approval') return Promise.resolve({ ...PENDING, status: 'escalated', level: 'A3' });
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Approvals />
      </ToastProvider>
    </AppProvider>,
  );
}

beforeEach(() => invokeMock.mockReset());

describe('Approvals — mirror-never-decide honesty invariants', () => {
  it('renders the real pending approval seated from the engine queue', async () => {
    setup();
    // The seated gate + queue row both show the real target/action from list_approvals.
    await waitFor(() => expect(screen.getAllByText('vendor@example.com').length).toBeGreaterThan(0));
    expect(screen.getAllByText('Send external email').length).toBeGreaterThan(0);
  });

  it('ESCALATE routes to the real escalate_approval command — no verdict is sent', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('vendor@example.com').length).toBeGreaterThan(0));

    // Open the escalate confirm from the authorization bar (accessible name = aria-label).
    fireEvent.click(screen.getByRole('button', { name: 'Escalate — park at tier A3' }));

    // The dialog states what escalation does AND what it leaves behind. It used to say only
    // "It routes to A3 review and notifies the owner — it neither grants nor denies": true, and
    // silent about the fact that an escalated request can never be decided afterwards
    // (`confirm_approval` / `reject_approval` are pending-only; no A3 review surface exists).
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/neither grants nor denies/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/nothing in this app can grant or deny it/i)).toBeInTheDocument();
    expect(within(dialog).queryByText(/routes to A3 review/i)).not.toBeInTheDocument();

    // Confirm the escalate.
    fireEvent.click(within(dialog).getByRole('button', { name: 'Escalate' }));

    // It calls the real, dedicated escalate command — and NEVER a grant/deny verdict.
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith('escalate_approval', { id: 'ap-1' }));
    expect(invokeMock).not.toHaveBeenCalledWith('confirm_approval', expect.anything());
    expect(invokeMock).not.toHaveBeenCalledWith('reject_approval', expect.anything());

    // …and the outcome is announced honestly as escalated, never as a fake grant/deny.
    expect(await screen.findByText(/Escalated to A3, not decided:/i)).toBeInTheDocument();
  });

  it('GRANT is reachable by the §D `g` key, and stages a confirm rather than committing', async () => {
    // The §D keyboard contract is "↑/↓ select, g grant, d deny, e escalate, Enter confirm,
    // Esc cancel; all actions confirm before committing". `g` was the one binding missing —
    // a keyboard owner driving the queue could deny and escalate by keystroke but not grant,
    // because grant existed only as a pointer press-and-hold. Both halves are asserted here:
    // that `g` reaches the grant path AT ALL, and that it does not commit on the keypress.
    setup();
    await waitFor(() => expect(screen.getAllByText('vendor@example.com').length).toBeGreaterThan(0));

    fireEvent.keyDown(window, { key: 'g' });

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/native confirmation the app window cannot forge/i)).toBeInTheDocument();
    // The keypress alone decided nothing — this is the half that fails if `g` ever commits.
    expect(invokeMock).not.toHaveBeenCalledWith('confirm_approval', expect.anything());

    fireEvent.click(within(dialog).getByRole('button', { name: 'Grant' }));
    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith('confirm_approval', expect.objectContaining({ id: 'ap-1' })),
    );
  });

  it('a `g` on a NON-pending row stages nothing — only pending items are actionable', async () => {
    // The positive control's sign flip: without it the test above would pass against a build
    // that opened a grant dialog for anything the owner happened to have selected.
    setup([{ ...PENDING, status: 'approved' }]);
    await waitFor(() => expect(screen.getAllByText('vendor@example.com').length).toBeGreaterThan(0));

    fireEvent.keyDown(window, { key: 'g' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('a MODIFIED key is somebody else’s shortcut and stages nothing', async () => {
    // fifth audit, A-11. `e.key.toLowerCase() === 'g'` matched Ctrl+G / Cmd+G, so find-next
    // opened a grant confirm AND preventDefault swallowed the browser's own binding. The
    // deliberate confirm step meant it could not commit — but a dialog the owner did not ask
    // for, over a keystroke they aimed somewhere else, is the wrong thing to have built.
    setup();
    await waitFor(() => expect(screen.getAllByText('vendor@example.com').length).toBeGreaterThan(0));

    fireEvent.keyDown(window, { key: 'g', ctrlKey: true });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'g', metaKey: true });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'd', ctrlKey: true });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    // Positive control: the unmodified key still works, so this is a modifier guard and not a
    // test that would pass against a build where `g` stopped doing anything at all.
    //
    // The keypress is RETRIED rather than fired once. This test was flaky — twice in a full-suite
    // run, never in ten isolated runs — because a single `fireEvent` races the page's own async
    // load: the handler closes over `data` and the selected row, and under load a re-render can
    // land between the guard presses and this one. The race is the test's, not the product's, so
    // the fix is to keep asking rather than to assume the first ask arrived.
    await waitFor(() => {
      fireEvent.keyDown(window, { key: 'g' });
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
  });

  it('DENY routes through the real fail-safe reject command', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByText('vendor@example.com').length).toBeGreaterThan(0));

    // Open the deny confirm from the authorization bar.
    fireEvent.click(screen.getByRole('button', { name: 'Deny — reject this action' }));
    const dialog = await screen.findByRole('dialog');
    // Commit the deny (confirm button = shared action.reject label).
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject' }));

    // The real fail-safe engine reject command is sent for this exact approval id.
    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith('reject_approval', expect.objectContaining({ id: 'ap-1' })),
    );
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// What a row may claim. `approvalsAuthority.ts` is "the single place that decides what the page
// is allowed to claim" and was imported by nothing — not the page, not a test. The page had its
// own regex over the status string instead, with no arm for `consumed` (a status the backend
// really writes) and one shared arm for "pending" and "anything I do not recognise".
// ─────────────────────────────────────────────────────────────────────────────

/** A grant as `approve_confirmed` writes it: status plus the four observable provenance markers. */
const GRANTED = {
  ...PENDING, status: 'approved', decidedAt: '1700000001000',
  confirmedAt: '1700000001000', confirmedBy: 'native-confirmer', confirmationMethod: 'native',
};

describe('Approvals — a row claims only what its record establishes', () => {
  const pillOf = () => document.querySelector('.gate .gh-tags .pill')?.textContent ?? '';

  it('a CONSUMED approval is not shown as "Awaiting decision"', async () => {
    setup([{ ...GRANTED, status: 'consumed' }]);
    await waitFor(() => expect(pillOf()).toBe('Consumed · grant spent'));
    expect(screen.queryByText('Awaiting decision')).not.toBeInTheDocument();
    // …and it is not actionable.
    expect(screen.getByRole('button', { name: 'Deny — reject this action' })).toBeDisabled();
  });

  it('a status this build does not know is shown as unknown, verbatim', async () => {
    setup([{ ...PENDING, status: 'cancelled' }]);
    await waitFor(() => expect(pillOf()).toBe('Unknown status · cancelled'));
    expect(screen.queryByText('Awaiting decision')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Deny — reject this action' })).toBeDisabled();
  });

  it('`approved` WITH its native-confirmation provenance opens the seal', async () => {
    setup([GRANTED]);
    await waitFor(() => expect(pillOf()).toBe('Approved'));
    expect(document.querySelector('.seal-lock .stamp')?.textContent).toBe('APPROVED');
    expect(document.querySelector('.g-stage')?.className).toContain('opened');
  });

  it('`approved` WITHOUT that provenance is not shown as granted — no green, no stamp', async () => {
    setup([{ ...PENDING, status: 'approved' }]);
    await waitFor(() => expect(pillOf()).toBe('Marked approved · no native confirmation on record'));
    expect(document.querySelector('.seal-lock .stamp')).toBeNull();
    expect(document.querySelector('.g-stage')?.className).not.toContain('opened');
    expect(document.querySelector('.gate')?.className).not.toContain('st-approved');
  });

  it('`granted` and `confirmed` are not synonyms for approved — no backend writes either', async () => {
    setup([{ ...GRANTED, status: 'granted' }]);
    await waitFor(() => expect(pillOf()).toBe('Unknown status · granted'));
    expect(document.querySelector('.seal-lock .stamp')).toBeNull();
  });

  it('the stats strip accounts for every row', async () => {
    setup([
      PENDING,
      { ...GRANTED, id: 'ap-2' },
      { ...GRANTED, id: 'ap-3', status: 'consumed' },
      { ...PENDING, id: 'ap-4', status: 'escalated' },
      { ...PENDING, id: 'ap-5', status: 'rejected' },
    ]);
    const strip = await screen.findByRole('region', { name: 'Approval statistics' });
    const tiles = Array.from(strip.querySelectorAll('.astat')).map(
      (el) => [el.querySelector('.micro')?.textContent, Number(el.querySelector('b')?.textContent)] as const,
    );
    const byLabel = Object.fromEntries(tiles);
    expect(byLabel['in queue']).toBe(5);
    expect(byLabel['consumed']).toBe(1);
    expect(byLabel['escalated · parked']).toBe(1);
    // The remainder is not silent: every tile after the total sums to it.
    const rest = tiles.filter(([label]) => label !== 'in queue').reduce((n, [, v]) => n + v, 0);
    expect(rest).toBe(5);
  });
});

describe('Approvals — the outcome announced is the one the reply carries', () => {
  const live = () => document.querySelector('.ap-sr')?.textContent ?? '';
  async function grantWith(reply: () => Promise<unknown>) {
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_approvals') return Promise.resolve([PENDING]);
      if (cmd === 'read_engine_approval_queue') return Promise.reject(new Error('broker_unavailable'));
      if (cmd === 'confirm_approval') return reply();
      return Promise.resolve(null);
    });
    render(<AppProvider><ToastProvider><Approvals /></ToastProvider></AppProvider>);
    await waitFor(() => expect(screen.getAllByText('vendor@example.com').length).toBeGreaterThan(0));
    await waitFor(() => {
      fireEvent.keyDown(window, { key: 'g' });
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Grant' }));
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith('confirm_approval', expect.anything()));
  }

  it('a grant that came back natively confirmed is announced as granted', async () => {
    await grantWith(() => Promise.resolve(GRANTED));
    await waitFor(() => expect(live()).toBe('Granted: vendor@example.com'));
  });

  it('a reply saying approved WITHOUT the provenance is not announced as granted', async () => {
    await grantWith(() => Promise.resolve({ ...PENDING, status: 'approved' }));
    await waitFor(() => expect(live()).toMatch(/The ledger now says: vendor@example.com — Marked approved/));
    expect(live()).not.toMatch(/^Granted:/);
  });

  it('a reply that is not an approval record establishes nothing', async () => {
    await grantWith(() => Promise.resolve(null));
    await waitFor(() => expect(live()).toMatch(/No readable record came back/));
    expect(live()).not.toMatch(/^Granted:/);
  });

  it('dismissing the native dialog is a non-decision, not a failure', async () => {
    await grantWith(() => Promise.reject(new Error('approval was not confirmed')));
    await waitFor(() => expect(live()).toBe('Not confirmed — nothing was decided: vendor@example.com'));
    expect(screen.queryByText(/Could not record the decision/)).not.toBeInTheDocument();
  });
});

// While the confirm dialog is open a window keydown committed on EVERY Enter, whatever the
// target, with preventDefault — so tabbing to Cancel and pressing Enter suppressed Cancel's own
// click and committed instead. A deny is immediate.
describe('Approvals — Enter on the dialog\'s Cancel button cancels', () => {
  async function stageDeny() {
    setup();
    await waitFor(() => expect(screen.getAllByText('vendor@example.com').length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole('button', { name: 'Deny — reject this action' }));
    return await screen.findByRole('dialog');
  }

  it('Enter on the focused Cancel button does not commit, and is left to the button', async () => {
    const dialog = await stageDeny();
    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
    cancel.focus();
    // false would mean a handler called preventDefault — i.e. Cancel's own click was suppressed.
    expect(fireEvent.keyDown(cancel, { key: 'Enter' })).toBe(true);
    await new Promise((r) => setTimeout(r, 30));
    expect(invokeMock).not.toHaveBeenCalledWith('reject_approval', expect.anything());
    // The dialog is still Cancel's to close.
    fireEvent.click(cancel);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(invokeMock).not.toHaveBeenCalledWith('reject_approval', expect.anything());
  });

  it('Enter anywhere else still commits (§D: "Enter confirm")', async () => {
    await stageDeny();
    fireEvent.keyDown(window, { key: 'Enter' });
    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith('reject_approval', expect.objectContaining({ id: 'ap-1' })));
  });
});

// The list is `list_approvals` on local SQLite. A failed read was labelled "Engine unreachable.",
// and any error mentioning `owner` or `denied` became "Owner not authenticated … until the owner
// authenticates with the engine". And both early returns sat ABOVE the engine queue notice and
// the engine REQUEST section, which do not depend on the local list at all.
describe('Approvals — the local ledger is not the engine, and the engine sections do not hide behind it', () => {
  function mountWith(list: () => Promise<unknown>) {
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'list_approvals') return list();
      if (cmd === 'read_engine_approval_queue') return Promise.reject(new Error('broker_unavailable'));
      return Promise.resolve(null);
    });
    return render(<AppProvider><ToastProvider><Approvals /></ToastProvider></AppProvider>);
  }
  const cleanup = () => { delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__; };

  it('an EMPTY ledger still shows the engine queue notice and the ask section', async () => {
    try {
      mountWith(() => Promise.resolve([]));
      await waitFor(() => expect(screen.getByText('Gate clear — no pending approvals')).toBeInTheDocument());
      expect(screen.getByRole('region', { name: 'Ask the engine to record a request' })).toBeInTheDocument();
      await waitFor(() =>
        expect(screen.getByText(/engine approval queue could not be reached/i)).toBeInTheDocument());
      // The empty hint no longer calls local requests "engine requests".
      expect(screen.queryByText(/New engine requests/)).not.toBeInTheDocument();
    } finally { cleanup(); }
  });

  it('a FAILED read names the local ledger, invents no owner authentication, and keeps both sections', async () => {
    try {
      mountWith(() => Promise.reject(new Error('owner table is locked')));
      await waitFor(() =>
        expect(screen.getByText(/The local approval ledger could not be read\. owner table is locked/)).toBeInTheDocument());
      expect(screen.queryByText('Owner not authenticated')).not.toBeInTheDocument();
      expect(screen.queryByText(/authenticates with the engine/)).not.toBeInTheDocument();
      expect(screen.queryByText(/Engine unreachable/)).not.toBeInTheDocument();
      expect(screen.getByRole('region', { name: 'Ask the engine to record a request' })).toBeInTheDocument();
      await waitFor(() =>
        expect(screen.getByText(/engine approval queue could not be reached/i)).toBeInTheDocument());
    } finally { cleanup(); }
  });

  it('a FAILED read does not report "0 pending" in green — nothing was counted', async () => {
    // The header pill was `live` (green) with a bold 0 while the ledger was loading or could not
    // be read: `items = data ?? []`, so the count of nothing-read looked like a count of zero.
    try {
      mountWith(() => Promise.reject(new Error('owner table is locked')));
      await waitFor(() =>
        expect(screen.getByText(/The local approval ledger could not be read/)).toBeInTheDocument());
      const pill = document.querySelector('.pageHead .right .pill')!;
      expect(pill).not.toBeNull();
      expect(pill.className).not.toMatch(/\blive\b/);
      expect(pill.textContent).not.toMatch(/^\s*0/);
    } finally { cleanup(); }
  });

  it('a READ ledger with nothing pending does say 0, in green', async () => {
    try {
      mountWith(() => Promise.resolve([]));
      await waitFor(() => expect(screen.getByText('Gate clear — no pending approvals')).toBeInTheDocument());
      const pill = document.querySelector('.pageHead .right .pill')!;
      expect(pill.className).toMatch(/\blive\b/);
      expect(pill.textContent).toMatch(/^\s*0/);
    } finally { cleanup(); }
  });

  it('the queue notice does not call the local list a mirror of the engine queue', async () => {
    setup();
    await waitFor(() =>
      expect(screen.getByText(/engine approval queue could not be reached/i)).toBeInTheDocument());
    expect(screen.queryByText(/local mirror/i)).not.toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// approvalsAuthority — the module itself, which had no test at all.
// ─────────────────────────────────────────────────────────────────────────────
describe('approvalsAuthority — what counts as a grant', () => {
  it('`approved` is a grant only with every observable native-confirmation marker', () => {
    expect(classifyApproval(GRANTED)).toMatchObject({ state: 'granted', authorized: true, actionable: false });
    for (const drop of ['decidedAt', 'confirmedAt', 'confirmedBy'] as const) {
      const c = classifyApproval({ ...GRANTED, [drop]: null });
      expect(c, `without ${drop}`).toMatchObject({ state: 'unconfirmed', authorized: false });
      expect(c.missing).toContain(drop);
    }
    // The method must be exactly `native` — `native-dialog` is not what the backend writes.
    expect(classifyApproval({ ...GRANTED, confirmationMethod: 'native-dialog' }))
      .toMatchObject({ state: 'unconfirmed', authorized: false });
    expect(missingGrantMarkers({ ...GRANTED, confirmationMethod: 'native-dialog' })).toEqual(['nativeConfirmation']);
  });

  it('only a pending row is actionable, and nothing but `granted` is authorized', () => {
    for (const status of ['pending', 'approved', 'rejected', 'escalated', 'consumed', 'expired', 'cancelled', '']) {
      const c = classifyApproval({ ...PENDING, status });
      expect(c.actionable, status).toBe(status === 'pending');
      expect(c.authorized, status).toBe(false);
    }
    expect(classifyApproval({ ...PENDING, status: 'cancelled' }).state).toBe('unknown');
    expect(classifyApproval({ ...GRANTED, status: 'consumed' }).state).toBe('consumed');
  });

  it('the queue buckets always sum to the total', () => {
    const rows = ['pending', 'approved', 'consumed', 'escalated', 'rejected', 'expired', 'weird', 'reviewing']
      .map((status, i) => ({ ...PENDING, id: `ap-${i}`, status }));
    const counts = countQueue([...rows, { ...GRANTED, id: 'ap-g' }]);
    expect(counts.total).toBe(9);
    expect(bucketSum(counts)).toBe(counts.total);
    expect(counts).toMatchObject({ pending: 1, granted: 1, unconfirmed: 1, consumed: 1, escalated: 1, denied: 1, other: 3 });
  });

  it('a reply is read for what it carries, and a dismissed dialog is not a refusal', () => {
    expect(readReply(GRANTED)).toEqual({ kind: 'recorded', state: 'granted' });
    expect(readReply({ ...PENDING, status: 'approved' })).toEqual({ kind: 'recorded', state: 'unconfirmed' });
    expect(readReply(null)).toEqual({ kind: 'unreadable' });
    expect(readReply('approved')).toEqual({ kind: 'unreadable' });
    expect(readRejection(new Error('approval was not confirmed')).kind).toBe('cancelled');
    expect(readRejection(new Error('approval is not pending')).kind).toBe('refused');
  });

  it('names the enforcement tokens the renderer never receives', () => {
    expect([...WITHHELD_MARKERS]).toEqual(['confirmation_digest', 'nonce']);
    // …and the Approval type really does not carry them.
    expect(Object.keys(GRANTED)).not.toEqual(expect.arrayContaining([...WITHHELD_MARKERS]));
  });
});

describe('approvalsAuthority — the page is wired to the commands it names, and only those', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/features/Approvals.tsx'), 'utf8');
  const service = readFileSync(resolve(process.cwd(), 'src/services/desktop.ts'), 'utf8');
  const capabilities = readFileSync(resolve(process.cwd(), 'src-tauri/capabilities/default.json'), 'utf8');
  const camel = (cmd: string) => cmd.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());
  const kebab = (cmd: string) => cmd.replace(/_/g, '-');

  it('each action the module declares is a real, granted command that the page calls', () => {
    for (const action of Object.values(APPROVAL_ACTIONS)) {
      expect(service, action.command).toContain(`'${action.command}'`);
      expect(capabilities, action.command).toContain(`"allow-${kebab(action.command)}"`);
      expect(page, action.command).toContain(`desktop.${camel(action.command)}(`);
      expect(action.granted).toBe(true);
    }
    // Privilege moves towards the agent on exactly one path, and that path is natively confirmed.
    const granting = Object.values(APPROVAL_ACTIONS).filter((a) => a.grantsPrivilege);
    expect(granting.map((a) => a.command)).toEqual(['confirm_approval']);
    expect(granting[0].nativeConfirmed).toBe(true);
  });

  it('the page renders no control for the generic approve verb, which is denied to this window', () => {
    // `reachability-declarations.json` says this constant "exists so the page can assert it never
    // renders a control" — and until now nothing asserted it.
    expect(DENIED_DECIDE_COMMAND).toBe('decide_approval');
    expect(capabilities).toContain(`"deny-${kebab(DENIED_DECIDE_COMMAND)}"`);
    expect(page).not.toContain(DENIED_DECIDE_COMMAND);
    expect(page).not.toMatch(new RegExp(`\\.${camel(DENIED_DECIDE_COMMAND)}\\s*\\(`));
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// The shared page fixtures (`pages.fixtures.tsx`) are typed against the domain entities, and a
// type cannot hold a VALUE to the backend's vocabulary: `confirmationMethod` is a string, so
// `'native-dialog'` compiled — and the one approved fixture classified as `unconfirmed`, so the
// populated sweeps never mounted a granted approval. These hold the values to what the backend
// writes, from the same classifiers the pages use.
// ─────────────────────────────────────────────────────────────────────────────
describe('the populated page fixtures carry values the backend really emits', () => {
  it('the approved fixture is a grant the page would show as granted', () => {
    const approvals = POPULATED.list_approvals as Approval[];
    const states = approvals.map((a) => classifyApproval(a).state);
    expect(states).toContain('granted');
    expect(states).not.toContain('unconfirmed');
    expect(states).not.toContain('unknown');
  });

  it('conversation kinds are the store\'s: direct, group or ask', () => {
    for (const c of POPULATED.list_conversations as Conversation[]) {
      expect(['direct', 'group', 'ask'], c.id).toContain(c.kind);
    }
  });

  it('automation triggers are ones the scheduler parses', () => {
    for (const a of POPULATED.list_automations as Automation[]) {
      expect(parseTrigger(a.trigger).kind, a.trigger).not.toBe('unrecognised');
      expect(a.action, a.id).toMatch(/^(notify|task|note):/);
    }
  });

  it('row timestamps are epoch-milliseconds as text, the shape core `now()` writes', () => {
    const stamped: Array<[string, string]> = [];
    for (const [cmd, rows] of Object.entries(POPULATED)) {
      if (!Array.isArray(rows)) continue;
      for (const row of rows as Array<Record<string, unknown>>) {
        for (const field of ['createdAt', 'updatedAt', 'requestedAt', 'ranAt']) {
          if (typeof row[field] === 'string') stamped.push([`${cmd}.${field}`, row[field] as string]);
        }
      }
    }
    expect(stamped.length).toBeGreaterThan(20);
    for (const [where, value] of stamped) {
      expect(value, where).toMatch(/^\d{13}$/);
      expect(parseTimestamp(value), where).not.toBeNull();
    }
  });
});
