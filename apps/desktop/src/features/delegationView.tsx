// The chat's delegation surface: what the owner sees when Bro hands work to a specialist.
//
// One card per spawn, and the card's whole job is the GRANT — the tier, the tools that tier
// actually carries, the paths that were named, and, said plainly, which of those two halves is
// enforced and which is only stated. That distinction is the point of the card. A tier is a
// real boundary (the `Task` tool reads the tool list out of `.claude/agents/<name>.md`); a
// `scope` line is prose inside a prompt until an engine bounds the run, and the card never
// lets those two read the same.
//
// When nothing is reported, nothing is drawn. See `delegationSource.ts` for why that is the
// state today and what the backend has to emit to change it.

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

/** Trilingual lookup, the same `L()` idiom the sibling views use. */
function useL(): (k: ChatStringKey) => string {
  const { lang } = useApp();
  return (k) => STR[k][lang] ?? STR[k].en;
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

  // Which sentence sits under the tool row. Capability is the enforced half — but only when it
  // was genuinely read from the agent definition; the mirrored tier table and "nothing reported"
  // each get their own, weaker sentence.
  const capabilityClaim: ChatStringKey =
    d.toolsSource === 'agent_definition' ? 'capabilityEnforced'
    : d.toolsSource === 'tier_table' ? 'capabilityFromTierTable'
    : 'capabilityUnknown';

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

        <p className={`dg-claim${d.toolsSource === 'unresolved' ? ' warn' : ''}`}>
          <span aria-hidden="true">{d.toolsSource === 'agent_definition' ? '🔒' : '⚠'}</span>
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

/** The honest absent state: a headline, why, and the backend's own words underneath. */
function Absent({ feed }: { feed: Extract<DelegationFeed, { state: 'unavailable' }> }) {
  const L = useL();
  const title: ChatStringKey =
    feed.reason === 'not_emitted' ? 'notEmittedTitle'
    : feed.reason === 'denied' ? 'deniedTitle'
    : feed.reason === 'no_backend' ? 'noBackendTitle'
    : 'errorTitle';
  const body: ChatStringKey = feed.reason === 'no_backend' ? 'noBackendBody' : 'notEmittedBody';
  return (
    <div className="dg-absent" role="status">
      <b>{L(title)}</b>
      <p>{L(body)}</p>
      <p className="dg-said">{L('backendSaid')}: {feed.detail}</p>
    </div>
  );
}

/**
 * The delegation section of the Chat screen.
 *
 * `conversationId` is optional and unset today — `Conversations.tsx` owns its selection and
 * exposes no way to read it, and that file is read-only for this task. The backend contract
 * carries `conversationId` per record so this can be narrowed without changing anything here.
 */
export function DelegationSurface({
  conversationId,
  invokeFn,
  backend,
}: {
  conversationId?: string;
  /** Test seams. Production passes neither and goes through the real Tauri `invoke`. */
  invokeFn?: InvokeFn;
  backend?: () => boolean;
}) {
  const L = useL();
  // Only `conversationId` is a dependency: `invokeFn`/`backend` are test seams, and putting a
  // caller-supplied function identity in this list would re-run the load on every render.
  const feed = useAsync<DelegationFeed>(
    () => loadDelegations(conversationId, { invokeFn, backend }),
    [conversationId],
  );
  const state = feed.data;
  const count = state?.state === 'ready' ? state.delegations.length : 0;

  return (
    <section className="v-deleg" aria-label={L('sectionTitle')}>
      <style>{VIEW_CSS}</style>
      <div className="dg-head">
        <div>
          <span className="eyebrow">{L('eyebrow')}</span>
          <p className="dg-note">{L('sectionNote')}</p>
        </div>
        <div className="th-actions">
          {state?.state === 'ready' && (
            <span className="micro"><b className="mono">{count}</b>&nbsp;{L('countUnit')}</span>
          )}
          <Button variant="ghost" small onClick={feed.reload} disabled={feed.loading}>
            {L('reload')}
          </Button>
        </div>
      </div>

      {feed.loading && state === null && <p className="dg-note">{L('loading')}</p>}
      {state?.state === 'unavailable' && <Absent feed={state} />}
      {state?.state === 'ready' && count === 0 && <EmptyState glyph="⚑" title={L('noneYet')} />}
      {state?.state === 'ready' && count > 0 && (
        <ul className="dg-list">
          {state.delegations.map((d) => <DelegationCard key={d.id} delegation={d} />)}
        </ul>
      )}
    </section>
  );
}
