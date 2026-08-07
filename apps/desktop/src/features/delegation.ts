// The delegation contract: what a Bro delegation looks like on the wire, and the fail-closed
// reader that turns backend JSON into something the chat is allowed to draw.
//
// ---- The wire this reader is now actually attached to --------------------------------
// `src-tauri/src/ai.rs` parses the CLI's `stream-json` for delegation blocks (the live capture
// in `docs/BRO_DELEGATION_EVIDENCE.md` shows the block is named `Agent`, not `Task`; both names
// are accepted there), and `commands.rs::delegation_frame` turns each one into a
// `StreamEvent::DelegationSpawned` / `DelegationSettled` on the SAME `tauri::ipc::Channel` that
// already carries `Delta` and `Done`. `Conversations.tsx` reads that channel and folds the two
// frames through `asDelegationEvent` -> `applyDelegationEventForConversation` below.
//
// What still does NOT exist is a READ-side command: nothing stores a delegation, so nothing can
// replay one after a reload. `delegationSource.ts` keeps probing for it and keeps saying so --
// a live feed is not a history, and the surface must not start looking like one.
//
// Everything here stays fail-closed regardless: a payload that cannot establish that a
// delegation genuinely happened yields no card at all, because a card drawn over data we do
// not have is a lie about what the owner authorised.
//
// ── The honesty rule this module encodes ────────────────────────────────────────────
// A grant has two halves and they are NOT equally real:
//
//   CAPABILITY (which tools)  — enforced, but only for a TIER. The app passes the three tier
//                               definitions to the CLI itself via `--agents`, and the spawn
//                               tool takes the subagent's tool list from there; Bro cannot pass
//                               an arbitrary one at spawn time, so choosing the agent IS the
//                               grant (`toolsSource: 'agent_definition'`). A pack role is
//                               weaker: `--setting-sources ""` means its
//                               `.claude/agents/<name>.md` is never loaded, so its `tools:`
//                               line is a fact about the role that bounded nothing on this run
//                               (`toolsSource: 'pack_role_file'`), and the card must not let
//                               the two read the same.
//   PATH (scope / prohibited) — NOT enforced on this path. `scope` and `prohibited_scope`
//                               travel as prose inside the task prompt. `engine`'s
//                               `bro_security.enforce_scope` is what actually contains a
//                               path, and the desktop `claude` spawn does not run through
//                               it. Until a backend states otherwise, path scope is a
//                               STATED INTENT, and this module labels it as one.
//
// Understating capability is the dangerous direction (the owner under-reads the risk of what
// he just authorised), so where sources disagree this module widens rather than narrows, and
// says that it did.

/** The three capability tiers Bro chooses between (`tools/generate_agent_definitions.py`). */
export type CapabilityTier = 'reader' | 'runner' | 'builder';

const TIERS: readonly CapabilityTier[] = ['reader', 'runner', 'builder'];

/**
 * Tools each tier's agent definition grants.
 *
 * A local MIRROR of `TIERS` in `tools/generate_agent_definitions.py` / the `tools:` frontmatter
 * of `.claude/agents/{reader,runner,builder}.md`. The renderer has no filesystem, so it cannot
 * read the real definitions at runtime — but a mirror that silently drifts would render a
 * narrower capability than the agent actually holds, which is the one error that matters here.
 * `Chat.delegationTiers.guard.test.ts` reads the real `.claude/agents/*.md` and fails on any
 * difference, so this table is a checked mirror rather than a remembered one.
 */
export const TIER_TOOLS: Readonly<Record<CapabilityTier, readonly string[]>> = {
  reader: ['Read', 'Grep', 'Glob'],
  runner: ['Read', 'Grep', 'Glob', 'Bash'],
  builder: ['Read', 'Edit', 'Write', 'Grep', 'Glob', 'Bash'],
};

/** Stable display order for a tool list, so two equal grants never read as different ones. */
const TOOL_ORDER = ['Read', 'Edit', 'Write', 'Grep', 'Glob', 'Bash', 'Task'];

export function isCapabilityTier(v: unknown): v is CapabilityTier {
  return typeof v === 'string' && (TIERS as readonly string[]).includes(v);
}

// ── Path grammar ────────────────────────────────────────────────────────────────────
// Verbatim copies of `$defs.repoPath.pattern` and `$defs.absolutePath.pattern` from
// `engine/schemas/task-contract.schema.json` — the same language `bro_contracts.safe_repo_path`
// / `safe_work_path` enforce procedurally. Copied rather than re-derived so a scope string the
// engine would refuse can never be drawn here as a clean, validated grant; the schema file is
// read back and compared character-for-character in `Chat.delegationContract.test.ts`, so a
// change on the engine side fails this side loudly instead of quietly widening what we accept.

/** `engine/schemas/task-contract.schema.json` → `$defs.repoPath.pattern`. */
export const REPO_PATH_PATTERN = String.raw`^(?:\.|(?!~)(?!\.\.?(?:/|$))[^\s\\/:*?\[\x00](?:[^\\/:*?\[\x00]*[^\s\\/:*?\[\x00])?(?:/(?!\.\.?(?:/|$))[^\s\\/:*?\[\x00](?:[^\\/:*?\[\x00]*[^\s\\/:*?\[\x00])?)*)$`;

/** `engine/schemas/task-contract.schema.json` → `$defs.absolutePath.pattern`. */
export const ABSOLUTE_PATH_PATTERN = String.raw`^(?:/|[A-Za-z]:/)(?!\.\.?(?:/|$))[^\s\\/:*?\[\x00](?:[^\\/:*?\[\x00]*[^\s\\/:*?\[\x00])?(?:/(?!\.\.?(?:/|$))[^\s\\/:*?\[\x00](?:[^\\/:*?\[\x00]*[^\s\\/:*?\[\x00])?)*$`;

const REPO_PATH = new RegExp(REPO_PATH_PATTERN);
const ABSOLUTE_PATH = new RegExp(ABSOLUTE_PATH_PATTERN);

/** A `scope` / `prohibited_scope` entry: repo-relative, or absolute when the work genuinely
 *  lives outside this checkout (a UI agent writing into a Desktop folder). */
export function isWorkPath(v: unknown): v is string {
  if (typeof v !== 'string' || v.length === 0) return false;
  return REPO_PATH.test(v) || ABSOLUTE_PATH.test(v);
}

// ── The wire contract ───────────────────────────────────────────────────────────────

/** Where a rendered tool list came from. Never invented. */
/**
 * Where the spawned agent's NAME came from — the backend's `agentOrigin`.
 *
 *  * `app_tier` — one of the three tiers this app passes to the CLI via `--agents`. The ONLY
 *    value meaning Bro's capability choice actually bounded the specialist.
 *  * `pack_role_file` — a `.claude/agents/<name>.md` we could read. Its `tools:` line is the
 *    authority the role was derived with; with `--setting-sources ""` that file is never loaded,
 *    so it bounded nothing on this run.
 *  * `cli_builtin` — a name the CLI offers and this app did not define. We do not know what it
 *    can do; we know we did not decide it. The app now denies these at argv, so a spawn is an
 *    ATTEMPT that the settlement reports as stopped — and the attempt is the part worth showing.
 *  * `unrecognized` — none of the above. Same conclusion as `cli_builtin`, stated separately only
 *    because we know strictly less.
 *  * `unstated` — the backend sent no origin at all (an older build). Not a verdict.
 */
export type AgentOrigin =
  | 'app_tier'
  | 'pack_role_file'
  | 'cli_builtin'
  | 'unrecognized'
  | 'unstated';

const AGENT_ORIGINS: readonly AgentOrigin[] = [
  'app_tier',
  'pack_role_file',
  'cli_builtin',
  'unrecognized',
];

/** Fail-closed: an unknown or absent value is `unstated`, never `app_tier`. Reading a strange
 *  value as "bounded by a tier" is the one direction that hides an unbounded agent. */
export function readAgentOrigin(raw: unknown): AgentOrigin {
  const v = str(raw);
  return v !== null && (AGENT_ORIGINS as readonly string[]).includes(v)
    ? (v as AgentOrigin)
    : 'unstated';
}

/** True when this app neither established nor bounded the agent — the card must warn, not blank. */
export function originIsUnbounded(o: AgentOrigin): boolean {
  return o === 'cli_builtin' || o === 'unrecognized';
}

export type ToolsSource =
  /** The definition this app handed the CLI as `--agents` for that exact agent type. It IS what
   *  bounds the run, so the card may call it enforced. (`ai.rs::ToolsSource::AgentDefinition`.) */
  | 'agent_definition'
  /** The `tools:` line of a pack role's `.claude/agents/<name>.md`. The backend really read it,
   *  so it is a fact about the role — but with `--setting-sources ""` that file is never loaded,
   *  so it bounded NOTHING on this run. Kept as its own value rather than folded into
   *  `agent_definition` (which would claim an enforcement that did not happen) or dropped
   *  (which would hide capability the owner handed out — the dangerous direction).
   *  (`ai.rs::ToolsSource::PackRoleFile`.) */
  | 'pack_role_file'
  /** Derived from `TIER_TOOLS` because the backend reported none. A checked mirror of the
   *  definitions, but not a read of the live file — the card says so. */
  | 'tier_table'
  /** Nothing trustworthy to show. The card states that capability is unknown. */
  | 'unresolved';

/** What, if anything, actually contains the specialist to its stated paths. */
export type ScopeEnforcement =
  /** Stated in the task, enforced by nobody on this path. The default, and today's truth. */
  | 'none'
  /** The engine's `bro_security.enforce_scope` (or an equivalent wall) bounded the run. Only
   *  ever set when the backend explicitly reports it. */
  | 'engine_enforce_scope';

export interface DelegationGrant {
  /** Validated work paths — every entry passed the task-contract grammar. */
  scope: readonly string[];
  prohibitedScope: readonly string[];
  /** Where the grant text was found. */
  source: 'task_prompt_text' | 'task_contract';
  enforcement: ScopeEnforcement;
}

export type DelegationOutcome = 'running' | 'ok' | 'error' | 'cancelled' | 'unknown';

export interface Delegation {
  /** Stable spawn id (the CLI's `tool_use.id`). Two events with one id are one delegation. */
  id: string;
  conversationId: string | null;
  /** Who delegated. `Bro` in every path that exists today. */
  parent: string;
  /** The `subagent_type` on the spawn block, verbatim — a tier name or a pack role. (The block
   *  itself is named `Agent` on the live wire, `Task` in the CLI's grant list; `ai.rs` accepts
   *  both. See `docs/BRO_DELEGATION_EVIDENCE.md` §3.) */
  subagentType: string;
  /** Non-null only when `subagentType` IS one of the three tiers. Derived here rather than
   *  read from the payload: a `tier` field that could disagree with the agent actually
   *  spawned is a forgery surface, and the agent name is the thing the CLI obeys. */
  tier: CapabilityTier | null;
  description: string | null;
  /** The task text Bro sent. Today this is also the only place `scope` exists at all. */
  prompt: string | null;
  tools: readonly string[];
  toolsSource: ToolsSource;
  /** Where the agent NAME came from, which is knowable for every spawn even when its tool list
   *  is not. Deliberately separate from `toolsSource`: that answers "where did this list come
   *  from" and is absent when there is none, so folding the two would make an agent this app
   *  never bounded look identical to one whose tools we merely failed to read. Anything other
   *  than `app_tier` means Bro reached outside the capability model. */
  agentOrigin: AgentOrigin;
  /** True when the backend's read of the agent definition and `TIER_TOOLS` disagreed. The
   *  union is shown (never the narrower list) and the card flags the disagreement. */
  toolsConflict: boolean;
  /** A grant whose every path passed the schema grammar. `null` means "do not draw one". */
  grant: DelegationGrant | null;
  /** The unvalidated strings, kept ONLY so a rejected grant can be shown as the raw text it
   *  was, never as a grant. Populated when `grantProblem` is set. */
  rawGrant: { scope: readonly string[]; prohibitedScope: readonly string[] } | null;
  /** Why no validated grant exists: `'not_stated'`, or `'invalid:<the offending entry>'`. */
  grantProblem: string | null;
  startedAt: string | null;
  outcome: DelegationOutcome;
  /** What came back, as the backend reported it. */
  summary: string | null;
  endedAt: string | null;
}

/**
 * The two events the backend emits, verified field-by-field against `commands.rs::delegation_frame`
 * and the live capture in `docs/BRO_DELEGATION_EVIDENCE.md`.
 *
 * `delegationSpawned` — one per delegation `tool_use` block on the `{"type":"assistant"}` line.
 *   `delegation` carries `id`, `subagentType`, `conversationId` (**`null`** for a one-shot ask),
 *   `parent`, `startedAt`, and OPTIONALLY `description` / `prompt` / `tools` + `toolsSource`.
 *   `tools` and `toolsSource` are **omitted together** when capability could not be established
 *   — never nulled, because `null` would read as an answer. `grant` is always present and is
 *   **`null`** when the task stated no scope; otherwise `{scope, prohibitedScope, source,
 *   enforcement}` with `enforcement` fixed at `"none"` on this route.
 * `delegationSettled` — one per `tool_result` block on the `{"type":"user"}` line.
 *   `id` = `tool_use_id`, `outcome` ∈ `ok` / `error` / `unknown`, `endedAt` always present,
 *   `summary` omitted when the stream reported no result text.
 *
 * Every field above is OPTIONAL to this reader: it reads what is there and refuses to invent
 * what is not. Nothing here may assume a field the backend does not send.
 */
export type DelegationEvent =
  | { type: 'delegationSpawned'; delegation: unknown }
  | { type: 'delegationSettled'; id: unknown; outcome: unknown; summary?: unknown; endedAt?: unknown };

// ── The fail-closed reader ──────────────────────────────────────────────────────────

const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() !== '' ? v : null);

function stringArray(v: unknown): string[] | null {
  if (!Array.isArray(v)) return null;
  return v.every((x) => typeof x === 'string') ? (v as string[]) : null;
}

/** Canonical order first, then anything unrecognised in the order it arrived. */
function orderTools(tools: readonly string[]): string[] {
  const seen = new Set(tools);
  const known = TOOL_ORDER.filter((t) => seen.has(t));
  const extra = tools.filter((t) => !TOOL_ORDER.includes(t));
  return [...known, ...Array.from(new Set(extra))];
}

/**
 * Resolve the capability half of the grant.
 *
 * Widening, never narrowing: if the backend's read of the live agent definition and the
 * checked `TIER_TOOLS` mirror disagree, one of them is stale and this code cannot know
 * which — so it shows the UNION and sets `toolsConflict`. Rendering the smaller list would
 * tell the owner he authorised less than he did, which is the failure that actually hurts.
 */
export function resolveTools(
  tier: CapabilityTier | null,
  reported: unknown,
  reportedSource: unknown,
): { tools: string[]; toolsSource: ToolsSource; toolsConflict: boolean } {
  // Two reported sources are genuine backend reads and neither may be discarded: dropping a list
  // the backend really read would draw "capability unknown" over a specialist that holds tools,
  // which is the understating failure this module exists to prevent. They are kept APART, though
  // — only `agent_definition` bounded the run — and the card says which of the two it has.
  const reportedIsRead =
    reportedSource === 'agent_definition' || reportedSource === 'pack_role_file';
  const fromBackend = reportedIsRead ? stringArray(reported) : null;
  const backendSource: ToolsSource =
    reportedSource === 'pack_role_file' ? 'pack_role_file' : 'agent_definition';
  const fromTier = tier ? [...TIER_TOOLS[tier]] : null;

  if (fromBackend && fromBackend.length > 0) {
    if (!fromTier) return { tools: orderTools(fromBackend), toolsSource: backendSource, toolsConflict: false };
    const same =
      fromBackend.length === fromTier.length && fromTier.every((t) => fromBackend.includes(t));
    if (same) return { tools: orderTools(fromBackend), toolsSource: backendSource, toolsConflict: false };
    return {
      tools: orderTools([...new Set([...fromBackend, ...fromTier])]),
      toolsSource: backendSource,
      toolsConflict: true,
    };
  }
  if (fromTier) return { tools: orderTools(fromTier), toolsSource: 'tier_table', toolsConflict: false };
  return { tools: [], toolsSource: 'unresolved', toolsConflict: false };
}

/**
 * Read the path half of the grant.
 *
 * All-or-nothing on purpose. A partially-parsed scope — three good paths kept, one malformed
 * one dropped — renders as a tidy, validated grant that is not the grant that was issued, and
 * the dropped entry is exactly the one worth looking at. So one bad entry rejects the whole
 * grant, and the raw strings are handed back to be shown as raw strings.
 */
export function readGrant(raw: unknown): {
  grant: DelegationGrant | null;
  rawGrant: { scope: string[]; prohibitedScope: string[] } | null;
  grantProblem: string | null;
} {
  if (raw === null || raw === undefined || typeof raw !== 'object') {
    return { grant: null, rawGrant: null, grantProblem: 'not_stated' };
  }
  const g = raw as Record<string, unknown>;
  const scopeRaw = stringArray(g.scope);
  const prohibitedRaw = g.prohibitedScope === undefined ? [] : stringArray(g.prohibitedScope);
  if (scopeRaw === null || prohibitedRaw === null) {
    return { grant: null, rawGrant: null, grantProblem: 'not_stated' };
  }
  if (scopeRaw.length === 0) {
    // `scope` has minItems 1 in the schema: an empty grant is not a narrow grant, it is a
    // missing one, and must not render as "may touch: nothing".
    return { grant: null, rawGrant: null, grantProblem: 'not_stated' };
  }
  const bad = [...scopeRaw, ...prohibitedRaw].find((p) => !isWorkPath(p));
  if (bad !== undefined) {
    return {
      grant: null,
      rawGrant: { scope: scopeRaw, prohibitedScope: prohibitedRaw },
      grantProblem: `invalid:${bad}`,
    };
  }
  const source = g.source === 'task_contract' ? 'task_contract' : 'task_prompt_text';
  // Enforcement is an allow-list of one. Anything else — absent, misspelt, or a hopeful
  // `"enforced": true` — reads as unenforced, because unenforced is what it is.
  const enforcement: ScopeEnforcement =
    g.enforcement === 'engine_enforce_scope' ? 'engine_enforce_scope' : 'none';
  return {
    grant: { scope: scopeRaw, prohibitedScope: prohibitedRaw, source, enforcement },
    rawGrant: null,
    grantProblem: null,
  };
}

/**
 * Parse one spawn payload. Returns `null` when the payload cannot establish that a delegation
 * genuinely happened — no id, or no named subagent. A card is a claim that Bro handed work to
 * a specific specialist; without those two facts there is no such claim to make.
 */
export function parseDelegation(raw: unknown): Delegation | null {
  if (raw === null || typeof raw !== 'object') return null;
  const d = raw as Record<string, unknown>;
  const id = str(d.id);
  const subagentType = str(d.subagentType);
  if (!id || !subagentType) return null;

  const tier = isCapabilityTier(subagentType) ? subagentType : null;
  const { tools, toolsSource, toolsConflict } = resolveTools(tier, d.tools, d.toolsSource);
  const { grant, rawGrant, grantProblem } = readGrant(d.grant);

  return {
    id,
    conversationId: str(d.conversationId),
    parent: str(d.parent) ?? 'Bro',
    subagentType,
    tier,
    description: str(d.description),
    prompt: str(d.prompt),
    tools,
    toolsSource,
    agentOrigin: readAgentOrigin(d.agentOrigin),
    toolsConflict,
    grant,
    rawGrant,
    grantProblem,
    startedAt: str(d.startedAt),
    outcome: 'running',
    summary: null,
    endedAt: null,
  };
}

const OUTCOMES: readonly DelegationOutcome[] = ['ok', 'error', 'cancelled'];

/**
 * Fold one event into the list.
 *
 * Two refusals worth naming:
 *  - a second `spawned` for a known id is ignored, so a replayed event cannot double a
 *    delegation on screen;
 *  - a `settled` for an UNKNOWN id is dropped entirely. Materialising a delegation from its
 *    ending would put a card on screen carrying no grant at all — the exact shape of "an
 *    agent ran and we cannot say what it was allowed to do", drawn as if it were a record.
 */
export function applyDelegationEvent(list: readonly Delegation[], ev: DelegationEvent): Delegation[] {
  if (ev.type === 'delegationSpawned') {
    const parsed = parseDelegation(ev.delegation);
    if (!parsed) return [...list];
    if (list.some((d) => d.id === parsed.id)) return [...list];
    return [...list, parsed];
  }
  const id = str(ev.id);
  if (!id) return [...list];
  const known = list.some((d) => d.id === id);
  if (!known) return [...list];
  // A settled delegation whose outcome we cannot read is `unknown`, not `ok`. It finished;
  // that is all we may say.
  const outcome: DelegationOutcome = OUTCOMES.includes(ev.outcome as DelegationOutcome)
    ? (ev.outcome as DelegationOutcome)
    : 'unknown';
  return list.map((d) =>
    d.id === id ? { ...d, outcome, summary: str(ev.summary), endedAt: str(ev.endedAt) } : d,
  );
}

/**
 * Narrow one raw frame off the `StreamEvent` channel to a delegation event, or `null`.
 *
 * The channel is shared: `delta`, `done`, `error`, `blocked`, `ready` and anything a future
 * backend adds ride the same wire. An unrecognised `type` must be IGNORED — never crashed on,
 * and above all never coerced into a delegation. So this matches the two known tags exactly and
 * returns `null` for everything else, including a frame with no `type` at all.
 *
 * The payload fields are passed through as `unknown` on purpose: this function decides only
 * WHICH event arrived. Whether it establishes anything is `parseDelegation`'s job, and it is the
 * one place allowed to say yes.
 */
export function asDelegationEvent(ev: unknown): DelegationEvent | null {
  if (ev === null || typeof ev !== 'object') return null;
  const e = ev as Record<string, unknown>;
  if (e.type === 'delegationSpawned') {
    return { type: 'delegationSpawned', delegation: e.delegation };
  }
  if (e.type === 'delegationSettled') {
    return {
      type: 'delegationSettled',
      id: e.id,
      outcome: e.outcome,
      summary: e.summary,
      endedAt: e.endedAt,
    };
  }
  return null;
}

/**
 * Fold one live event into a list that belongs to ONE conversation.
 *
 * A delegation filed under the wrong conversation is worse than one not shown: it tells the
 * owner that a specialist was given tools inside a thread where that never happened. So a spawn
 * is admitted only when the payload's own `conversationId` matches the conversation this list
 * belongs to — exact equality, which also rejects the one-shot-ask frame (`conversationId:
 * null`, emitted by `stream_ask`) rather than adopting it into whichever chat happened to be
 * open. The channel carrying the frame is NOT accepted as proof of provenance; the payload is.
 *
 * Settlements need no filter of their own: `applyDelegationEvent` drops any id this list never
 * saw spawned, which is also what keeps a nested specialist's own `Read`/`Bash` results — the
 * backend emits a settlement for every tool return — off the delegation surface.
 */
export function applyDelegationEventForConversation(
  list: readonly Delegation[],
  ev: DelegationEvent,
  conversationId: string,
): Delegation[] {
  if (ev.type === 'delegationSpawned') {
    const parsed = parseDelegation(ev.delegation);
    if (!parsed || parsed.conversationId !== conversationId) return [...list];
  }
  return applyDelegationEvent(list, ev);
}

/** Fold a whole batch (a reload of persisted delegations, or a replayed turn). */
export function reduceDelegationEvents(events: readonly DelegationEvent[]): Delegation[] {
  return events.reduce<Delegation[]>((acc, ev) => applyDelegationEvent(acc, ev), []);
}

/**
 * Parse one already-finished record, as a `list_delegations` read would return it: the spawn
 * fields plus however it ended. Same refusals as `parseDelegation`, plus the same rule about
 * an unreadable outcome — a record that ended in a way we cannot classify is `unknown`, never
 * `ok`. A record with no ending at all is still `running`, which is the truth after a reload
 * interrupted a live turn.
 */
export function parseDelegationRecord(raw: unknown): Delegation | null {
  const base = parseDelegation(raw);
  if (!base) return null;
  const d = raw as Record<string, unknown>;
  if (d.outcome === undefined || d.outcome === null) return base;
  const outcome: DelegationOutcome = OUTCOMES.includes(d.outcome as DelegationOutcome)
    ? (d.outcome as DelegationOutcome)
    : 'unknown';
  return { ...base, outcome, summary: str(d.summary), endedAt: str(d.endedAt) };
}

/** Parse a `list_delegations` reply. A non-array reply yields `null` (the caller reports the
 *  backend as unreadable); individual records that fail the reader are dropped rather than
 *  patched into shape. */
export function parseDelegationList(raw: unknown): Delegation[] | null {
  if (!Array.isArray(raw)) return null;
  return raw
    .map((r) => parseDelegationRecord(r))
    .filter((d): d is Delegation => d !== null);
}
