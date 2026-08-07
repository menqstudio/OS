// The delegation contract: what a Bro `Task` spawn must look like on the wire, and the
// fail-closed reader that turns backend JSON into something the chat is allowed to draw.
//
// ── Why this file is a reader for a contract that does not exist yet ─────────────────
// Bro can delegate: `tool_args(true)` in `src-tauri/src/ai.rs` grants him `Task`, and
// `.claude/agents/` holds the three capability tiers plus the pack roles he picks between.
// What he CANNOT do today is be seen doing it. `claude_cli_stream` parses exactly two line
// shapes out of the CLI's `stream-json`: `stream_event → content_block_delta → delta.text`,
// and the final `result`. Every other line falls into `_ => {}`. A `Task` spawn arrives on a
// `{"type":"assistant"}` line as a `tool_use` content block, and its return on a
// `{"type":"user"}` line as a `tool_result` block — both are dropped on the floor. Nothing
// reaches `StreamEvent` (commands.rs), so nothing reaches the renderer.
//
// So: this module parses a contract the backend must still emit (the exact shape is
// documented on `DelegationEvent` below and repeated in the report), and every consumer of
// it renders "not reported" rather than a plausible card, because a delegation card drawn
// over data we do not have is a lie about what the owner authorised.
//
// ── The honesty rule this module encodes ────────────────────────────────────────────
// A grant has two halves and they are NOT equally real:
//
//   CAPABILITY (which tools)  — enforced. The `Task` tool takes the subagent's tool list
//                               from its `.claude/agents/<name>.md` frontmatter; Bro cannot
//                               pass an arbitrary one at spawn time. Choosing the agent IS
//                               the grant.
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
export type ToolsSource =
  /** The backend read the spawned agent's `.claude/agents/<name>.md` frontmatter. */
  | 'agent_definition'
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
  /** The `subagent_type` handed to the `Task` tool, verbatim — a tier name or a pack role. */
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
 * The two events the backend must emit. Proposed names; the shape is what matters.
 *
 * `delegationSpawned` — on the `{"type":"assistant"}` line, for each `tool_use` block whose
 *   `name` is `Task`. `id` = the block's `id`; `subagentType`/`description`/`prompt` = its
 *   `input`. `tools` = the `tools:` frontmatter of `.claude/agents/<subagentType>.md`, read
 *   by the backend at spawn time (omit the field rather than guess if the file is absent).
 * `delegationSettled` — on the `{"type":"user"}` line, for each `tool_result` block;
 *   `id` = `tool_use_id`, `outcome` from `is_error`, `summary` = the result content.
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
  const fromBackend = reportedSource === 'agent_definition' ? stringArray(reported) : null;
  const fromTier = tier ? [...TIER_TOOLS[tier]] : null;

  if (fromBackend && fromBackend.length > 0) {
    if (!fromTier) return { tools: orderTools(fromBackend), toolsSource: 'agent_definition', toolsConflict: false };
    const same =
      fromBackend.length === fromTier.length && fromTier.every((t) => fromBackend.includes(t));
    if (same) return { tools: orderTools(fromBackend), toolsSource: 'agent_definition', toolsConflict: false };
    return {
      tools: orderTools([...new Set([...fromBackend, ...fromTier])]),
      toolsSource: 'agent_definition',
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
