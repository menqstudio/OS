// The chat's delegation surface: what the owner sees when Bro hands work to a specialist.
//
// One card per spawn, and the card's whole job is the GRANT -- the tier, the tools that tier
// actually carries, the paths that were named, and, said plainly, which of those two halves is
// enforced and which is only stated. That distinction is the point of the card. A tier is a real
// boundary (the app passes the tier definitions to the CLI as `--agents`, and the spawn takes the
// tool list from there); a `scope` line is prose inside a prompt until an engine bounds the run,
// and the card never lets those two read the same.
//
// The surface has TWO sources and they are not the same kind of thing:
//
//   `live`   -- delegations reported by a turn while it ran, folded straight off the
//               `StreamEvent` channel by `Conversations.tsx`. Real, current, and gone on reload.
//   the probe -- `delegationSource.loadDelegations`, which asks for a stored ledger. There is no
//               such command yet, so this is `unavailable` and the surface SAYS so, right under
//               the live cards. A feed is not a history, and a list that quietly stood in for
//               one would be read as "Bro delegated nothing" every time the app restarts.
//
// When neither reports anything, nothing is drawn.

import { useApp } from '../app/store';
import { useAsync } from '../hooks/useAsync';
import { Badge, Button, EmptyState } from '../components/ui';
import type { Tone } from '../domain/enums';
import { STR, type ChatStringKey } from './Chat.strings';
import { loadDelegations, type DelegationFeed, type InvokeFn } from './delegationSource';
import type { Delegation, DelegationOutcome } from './delegation';

const VIEW_CSS = `
.v-deleg{margin-top:18px}
.v-deleg .dg-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.v-deleg .dg-note{margin:2px 0 0;font-size:12px;color:var(--ink-muted);line-height:1.55;max-width:78ch}
.v-deleg .dg-list{display:flex;flex-direction:column;gap:12px;margin:0;padding:0;list-style:none}
.v-deleg .dg-card{padding:14px 16px}
.v-deleg .dg-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.v-deleg .dg-who{font-family:var(--f-mono);font-size:13px;color:var(--ink)}
.v-deleg .dg-arrow{color:var(--ink-muted);font-family:var(--f-mono)}
.v-deleg .dg-time{margin-left:auto;font-size:11.5px;color:var(--ink-muted)}
.v-deleg .dg-desc{margin:8px 0 0;font-size:13.5px;line-height:1.55;color:var(--ink)}
.v-deleg .dg-grant{margin:12px 0 0;display:grid;grid-template-columns:minmax(112px,auto) minmax(0,1fr);gap:6px 14px;align-items:baseline}
.v-deleg .dg-k{font-family:var(--f-mono);font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-muted)}
.v-deleg .dg-v{min-width:0;font-size:12.5px;line-height:1.6;word-break:break-word}
.v-deleg .dg-path{display:block;font-family:var(--f-mono);font-size:12px;word-break:break-all}
.v-deleg .dg-tool{display:inline-block;font-family:var(--f-mono);font-size:11.5px;padding:1px 7px;margin:0 5px 4px 0;
  border:1px solid var(--line);border-radius:var(--r-pill);color:var(--ink)}
.v-deleg .dg-claim{margin:10px 0 0;font-size:11.5px;line-height:1.55;color:var(--ink-muted);display:flex;gap:6px;align-items:flex-start}
.v-deleg .dg-claim.warn{color:var(--warning)}
.v-deleg .dg-fold{margin:10px 0 0}
.v-deleg .dg-fold>summary{cursor:pointer;font-family:var(--f-mono);font-size:11px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink-muted)}
.v-deleg .dg-fold>summary:focus-visible{outline:2px solid rgb(var(--cyan-rgb)/.6);outline-offset:2px;border-radius:4px}
.v-deleg .dg-pre{margin:8px 0 0;padding:10px 12px;border:1px solid var(--line);border-radius:var(--r);
  background:rgb(var(--raised-rgb)/.5);font-family:var(--f-mono);font-size:12px;line-height:1.6;
  white-space:pre-wrap;word-break:break-word;max-height:280px;overflow:auto}
.v-deleg .dg-absent{padding:12px 14px;border:1px solid var(--line);border-radius:var(--r);
  background:rgb(var(--raised-rgb)/.4)}
.v-deleg .dg-absent b{display:block;font-size:13px;margin-bottom:4px}
.v-deleg .dg-absent p{margin:0;font-size:12.5px;line-height:1.6;color:var(--ink-muted);max-width:78ch}
.v-deleg .dg-said{margin-top:8px;font-family:var(--f-mono);font-size:11.5px;color:var(--ink-muted);word-break:break-word}
`;

/**
 * Copy this surface needs that `Chat.strings.ts` does not carry.
 *
 * It lives here rather than in `Chat.strings.ts` because that file was outside this task's edit
 * scope, and a card whose wording lags what the code actually does is the exact defect the rest
 * of this module exists to prevent. Same trilingual shape, same `L()` idiom, merged below — when
 * the two files can be edited together these belong beside their siblings.
 */
export const SURFACE_STR = {
  /** Replaces the old "the backend does not report delegations yet" copy, which the live
   *  channel has made false. What is missing now is STORAGE, not reporting. */
  noLedgerTitle: {
    en: 'Live only — no stored delegation ledger',
    hy: 'Միայն կենդանի — պահված պատվիրակումների մատյան չկա',
    ru: 'Только вживую — сохранённого журнала делегирований нет',
  },
  noLedgerBody: {
    en: 'A running turn reports each delegation as it happens, and those are what you see here. '
      + 'Nothing stores them: there is no read-side command, so a reload empties this list. '
      + 'This is one session, not a complete history of the conversation — an empty list means '
      + 'nothing was reported to this window, never that Bro delegated nothing.',
    hy: 'Ընթացող turn-ը հաղորդում է ամեն պատվիրակում հենց տեղի ունենալու պահին, ու հենց դրանք ես տեսնում այստեղ։ '
      + 'Ոչինչ դրանք չի պահում. read-ի կողմից command չկա, ուրեմն reload-ը դատարկում է այս ցանկը։ '
      + 'Սա մեկ session է, ոչ թե զրույցի ամբողջ պատմությունը — դատարկ ցանկը նշանակում է, որ այս պատուհանին ոչինչ '
      + 'չի հաղորդվել, ոչ երբեք՝ որ Bro-ն ոչինչ չի պատվիրակել։',
    ru: 'Идущий ход сообщает о каждом делегировании по мере того, как оно происходит, — именно это здесь и видно. '
      + 'Ничто их не сохраняет: команды на чтение нет, поэтому перезагрузка очищает этот список. '
      + 'Это одна сессия, а не полная история разговора — пустой список означает, что окну ничего не сообщили, '
      + 'а вовсе не то, что Bro ничего не поручал.',
  },
  /** `denied` / `error`: the read FAILED, which is a different fact from "there is no such
   *  command" and must not borrow its explanation. */
  unreadableLedgerBody: {
    en: 'The stored ledger could not be read, so anything listed above is only what this '
      + 'session’s turns reported as they ran. An empty list is not evidence that Bro '
      + 'delegated nothing — it means this window was told nothing.',
    hy: 'Պահված մատյանը չհաջողվեց կարդալ, ուրեմն վերևում թվարկվածը միայն այն է, ինչ այս session-ի '
      + 'turn-երը հաղորդել են ընթացքում։ Դատարկ ցանկը ապացույց չէ, որ Bro-ն ոչինչ չի պատվիրակել — '
      + 'նշանակում է՝ այս պատուհանին ոչինչ չեն ասել։',
    ru: 'Сохранённый журнал прочитать не удалось, поэтому всё перечисленное выше — только то, о чём '
      + 'сообщили ходы этой сессии. Пустой список не является доказательством того, что Bro ничего '
      + 'не поручал: он означает, что окну ничего не сообщили.',
  },
  /** The pack-role capability sentence. The list was really read; it just bounded nothing. */
  capabilityFromRoleFile: {
    en: 'Recorded from the pack role file, not enforced here — that file is not loaded for this '
      + 'run, so nothing bounded the specialist to this list.',
    hy: 'Գրանցված է pack-ի դերի ֆայլից, բայց այստեղ չի կիրառվում — այդ ֆայլը այս run-ի համար չի բեռնվում, '
      + 'ուրեմն ոչինչ մասնագետին այս ցանկում չի պահել։',
    ru: 'Записано из файла роли пакета, но здесь не обеспечено — этот файл для данного запуска не '
      + 'загружается, поэтому ничто не ограничивало специалиста этим списком.',
  },
} as const;

type SurfaceStringKey = keyof typeof SURFACE_STR;
type AnyStringKey = ChatStringKey | SurfaceStringKey;

/** Trilingual lookup, the same `L()` idiom the sibling views use. */
function useL(): (k: AnyStringKey) => string {
  const { lang } = useApp();
  return (k) => {
    const row = (k in SURFACE_STR ? SURFACE_STR[k as SurfaceStringKey] : STR[k as ChatStringKey]) as
      Record<string, string>;
    return row[lang] ?? row.en;
  };
}

function fmtTime(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/**
 * Outcome → badge. `running` and `unknown` deliberately never take a success tone: a
 * delegation still in flight has not succeeded, and one whose ending we could not read has
 * not been shown to.
 */
export function outcomeBadge(outcome: DelegationOutcome): { tone: Tone; key: ChatStringKey } {
  switch (outcome) {
    case 'ok':
      return { tone: 'success', key: 'outcomeOk' };
    case 'error':
      return { tone: 'danger', key: 'outcomeError' };
    case 'cancelled':
      return { tone: 'warning', key: 'outcomeCancelled' };
    case 'running':
      return { tone: 'info', key: 'outcomeRunning' };
    default:
      return { tone: 'warning', key: 'outcomeUnknown' };
  }
}

function PathList({ paths }: { paths: readonly string[] }) {
  return (
    <span className="dg-v">
      {paths.map((p) => (
        <code className="dg-path" key={p}>{p}</code>
      ))}
    </span>
  );
}

export function DelegationCard({ delegation: d }: { delegation: Delegation }) {
  const L = useL();
  const badge = outcomeBadge(d.outcome);
  const kindKey: ChatStringKey = d.tier ? 'tierLabel' : 'packRoleLabel';

  // Which sentence sits under the tool row. Capability is the enforced half — but ONLY for
  // `agent_definition`, the tier list this app actually handed the CLI. Each weaker source gets
  // its own weaker sentence, and none of them may borrow the enforced one.
  const capabilityClaim: AnyStringKey =
    d.toolsSource === 'agent_definition' ? 'capabilityEnforced'
    : d.toolsSource === 'pack_role_file' ? 'capabilityFromRoleFile'
    : d.toolsSource === 'tier_table' ? 'capabilityFromTierTable'
    : 'capabilityUnknown';
  // The lock is reserved for the one source that bounded the run. A role file was genuinely
  // read but enforced nothing, so it warns exactly like an unresolved capability does.
  const capabilityEnforced = d.toolsSource === 'agent_definition';
  const capabilityWarns = d.toolsSource === 'unresolved' || d.toolsSource === 'pack_role_file';

  return (
    <li>
      <article
        className="surface soft dg-card"
        aria-label={`${d.parent} ${L('delegatedTo')} ${d.subagentType}`}
      >
        <div className="dg-top">
          <span className="dg-who">{d.parent}</span>
          <span className="dg-arrow" aria-hidden="true">→</span>
          <span className="dg-who"><b>{d.subagentType}</b></span>
          <span className="micro">{L(kindKey)}</span>
          <Badge tone={badge.tone}>{L(badge.key)}</Badge>
          {fmtTime(d.startedAt) && <span className="dg-time mono">{fmtTime(d.startedAt)}</span>}
        </div>

        {d.description && <p className="dg-desc">{d.description}</p>}

        <div className="dg-grant">
          <span className="dg-k">{L('canDo')}</span>
          <span className="dg-v">
            {d.tools.length > 0
              ? d.tools.map((t) => <span className="dg-tool" key={t}>{t}</span>)
              : <span className="muted">—</span>}
          </span>

          {/* The path half. Only a grant every entry of which passed the task-contract
              grammar is drawn as a grant; anything else falls through to the notes below. */}
          {d.grant && (
            <>
              <span className="dg-k">{L('mayTouch')}</span>
              <PathList paths={d.grant.scope} />
              {d.grant.prohibitedScope.length > 0 && (
                <>
                  <span className="dg-k">{L('mustNotTouch')}</span>
                  <PathList paths={d.grant.prohibitedScope} />
                </>
              )}
            </>
          )}
        </div>

        <p className={`dg-claim${capabilityWarns ? ' warn' : ''}`}>
          <span aria-hidden="true">{capabilityEnforced ? '🔒' : '⚠'}</span>
          <span>{L(capabilityClaim)}</span>
        </p>
        {d.toolsConflict && (
          <p className="dg-claim warn"><span aria-hidden="true">⚠</span><span>{L('capabilityConflict')}</span></p>
        )}

        {d.grant && (
          <p className={`dg-claim${d.grant.enforcement === 'engine_enforce_scope' ? '' : ' warn'}`}>
            <span aria-hidden="true">{d.grant.enforcement === 'engine_enforce_scope' ? '🔒' : '⚠'}</span>
            <span>{L(d.grant.enforcement === 'engine_enforce_scope' ? 'scopeEnforcedByEngine' : 'scopeUnenforced')}</span>
          </p>
        )}

        {/* A grant that was stated but is not a valid work path: shown as the raw text it is,
            never laid out as if it had been accepted. */}
        {!d.grant && d.grantProblem?.startsWith('invalid:') && (
          <>
            <p className="dg-claim warn"><span aria-hidden="true">⚠</span><span>{L('grantInvalid')}</span></p>
            <p className="dg-said">
              {L('offendingEntry')}: <code>{d.grantProblem.slice('invalid:'.length)}</code>
            </p>
            {d.rawGrant && (
              <pre className="dg-pre">{[...d.rawGrant.scope, ...d.rawGrant.prohibitedScope].join('\n')}</pre>
            )}
          </>
        )}
        {!d.grant && d.grantProblem === 'not_stated' && (
          <p className="dg-claim warn"><span aria-hidden="true">⚠</span><span>{L('grantNotStated')}</span></p>
        )}

        {d.prompt && (
          <details className="dg-fold">
            <summary>{L('whatWasAsked')}</summary>
            <pre className="dg-pre">{d.prompt}</pre>
          </details>
        )}
        <details className="dg-fold">
          <summary>{L('whatCameBack')}</summary>
          <pre className="dg-pre">
            {d.summary ?? (d.outcome === 'running' ? L('noResultYet') : L('noSummary'))}
          </pre>
        </details>
      </article>
    </li>
  );
}

/**
 * Why there is no STORED ledger — a headline, the consequence, and the backend's own words.
 *
 * Rendered whether or not live cards are on screen, and that is the point: when the read
 * command is missing, the list above is one session and saying so is the only thing keeping it
 * from being read as a complete record. The `not_emitted` copy therefore no longer says "the
 * backend does not report delegations" — it does report them, live — it says nothing stores
 * them. `denied`, `error` and `no_backend` keep their own wording, which is still exactly true.
 */
function Absent({ feed }: { feed: Extract<DelegationFeed, { state: 'unavailable' }> }) {
  const L = useL();
  const title: AnyStringKey =
    feed.reason === 'not_emitted' ? 'noLedgerTitle'
    : feed.reason === 'denied' ? 'deniedTitle'
    : feed.reason === 'no_backend' ? 'noBackendTitle'
    : 'errorTitle';
  const body: AnyStringKey =
    feed.reason === 'no_backend' ? 'noBackendBody'
    : feed.reason === 'not_emitted' ? 'noLedgerBody'
    // A refusal and a fault are NOT "there is no such command", and neither may be explained as
    // one — that is how a real broken backend ends up reading as an unbuilt feature.
    : 'unreadableLedgerBody';
  return (
    <div className="dg-absent" role="status">
      <b>{L(title)}</b>
      <p>{L(body)}</p>
      <p className="dg-said">{L('backendSaid')}: {feed.detail}</p>
    </div>
  );
}

/**
 * The two sources, in one list, without either one erasing the other.
 *
 * Keyed by delegation id, `live` last: when a turn is running, its own report of a delegation is
 * newer than whatever a stored read said about the same id, and preferring the stale copy would
 * freeze a card at `running` after it had already come back. Order is stable — stored records
 * first, in the order the backend gave them, then the live ones in the order they were spawned.
 */
export function mergeDelegations(
  stored: readonly Delegation[],
  live: readonly Delegation[],
): Delegation[] {
  const byId = new Map<string, Delegation>();
  for (const d of stored) byId.set(d.id, d);
  for (const d of live) byId.set(d.id, d);
  return [...byId.values()];
}

/**
 * The delegation section of the Chat screen.
 *
 * `Conversations.tsx` renders this beneath the workspace and supplies both halves: the thread it
 * is actually showing (`conversationId`) and the delegations that thread's own stream reported
 * (`live`). The live list arrives ALREADY bound to that conversation — the fold in
 * `applyDelegationEventForConversation` admits a spawn only when the payload's own
 * `conversationId` matches — so nothing here has to trust the channel it came off.
 */
export function DelegationSurface({
  conversationId,
  live,
  invokeFn,
  backend,
  label,
}: {
  conversationId?: string;
  /** Delegations this conversation's running turn reported, folded by the caller. Live truth,
   *  not persisted: whatever is here vanishes on reload, and the note below says so. */
  live?: readonly Delegation[];
  /** Test seams. Production passes neither and goes through the real Tauri `invoke`. */
  invokeFn?: InvokeFn;
  backend?: () => boolean;
  /** Overrides the section's accessible name. Two surfaces can appear on one page — the room's
   *  chat turns and, in a group room, the consensus deck's own asks — and they cover DIFFERENT
   *  streams. Sharing one name made them indistinguishable to a screen reader and to a test, and
   *  a panel that cannot say which turns it saw is one that reads as the whole room's record. */
  label?: string;
}) {
  const L = useL();
  // Only `conversationId` is a dependency: `invokeFn`/`backend` are test seams, and putting a
  // caller-supplied function identity in this list would re-run the load on every render.
  const feed = useAsync<DelegationFeed>(
    () => loadDelegations(conversationId, { invokeFn, backend }),
    [conversationId],
  );
  const state = feed.data;
  const stored = state?.state === 'ready' ? state.delegations : [];
  const shown = mergeDelegations(stored, live ?? []);
  const count = shown.length;

  return (
    <section className="v-deleg" aria-label={label ?? L('sectionTitle')}>
      <style>{VIEW_CSS}</style>
      <div className="dg-head">
        <div>
          <span className="eyebrow">{L('eyebrow')}</span>
          <p className="dg-note">{L('sectionNote')}</p>
        </div>
        <div className="th-actions">
          {(state?.state === 'ready' || count > 0) && (
            <span className="micro"><b className="mono">{count}</b>&nbsp;{L('countUnit')}</span>
          )}
          <Button variant="ghost" small onClick={feed.reload} disabled={feed.loading}>
            {L('reload')}
          </Button>
        </div>
      </div>

      {feed.loading && state === null && count === 0 && <p className="dg-note">{L('loading')}</p>}

      {/* The cards first — live ones included, whatever the stored read had to say. */}
      {count > 0 && (
        <ul className="dg-list">
          {shown.map((d) => <DelegationCard key={d.id} delegation={d} />)}
        </ul>
      )}

      {/* …then, under them, why this is not a history. Rendered even with cards above it: that
          is the whole reason the honest read is kept once a live path exists. */}
      {state?.state === 'unavailable' && <Absent feed={state} />}

      {/* Nothing from either source. Not the same claim as "no delegation happened" — the note
          above states which of the two it is. */}
      {state?.state === 'ready' && count === 0 && <EmptyState glyph="⚑" title={L('noneYet')} />}
    </section>
  );
}
