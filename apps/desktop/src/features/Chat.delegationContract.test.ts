// The fail-closed reader behind the chat's delegation surface.
//
// These are honesty tests, not shape tests. Each one pins a case where the tempting behaviour
// (fill in a gap, keep the good half, trust the field you were sent) would put a claim on
// screen about what the owner authorised that nobody can stand behind.

import { describe, it, expect } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  ABSOLUTE_PATH_PATTERN,
  REPO_PATH_PATTERN,
  TIER_TOOLS,
  applyDelegationEvent,
  isCapabilityTier,
  isWorkPath,
  parseDelegation,
  parseDelegationList,
  parseDelegationRecord,
  readGrant,
  reduceDelegationEvents,
  resolveTools,
  type Delegation,
  type DelegationEvent,
} from './delegation';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '../../../..');
const SCHEMA = resolve(REPO_ROOT, 'engine/schemas/task-contract.schema.json');

/** A well-formed spawn payload, as the proposed backend contract would send it. */
const spawn = (over: Record<string, unknown> = {}) => ({
  id: 'toolu_1',
  conversationId: 'c-1',
  parent: 'Bro',
  subagentType: 'builder',
  description: 'Render delegation in the chat surface',
  prompt: 'scope: apps/desktop/src/features …',
  tools: ['Read', 'Edit', 'Write', 'Grep', 'Glob', 'Bash'],
  toolsSource: 'agent_definition',
  grant: {
    scope: ['apps/desktop/src/features'],
    prohibitedScope: ['engine', 'apps/desktop/src-tauri'],
    source: 'task_prompt_text',
  },
  startedAt: '2026-08-07T10:00:00.000Z',
  ...over,
});

describe('path grammar — the same language the engine enforces', () => {
  // The desktop copy of a security-relevant grammar is only safe while it IS a copy. If the
  // engine tightens `workPath` and this file does not follow, the surface starts drawing scopes
  // as validated grants that the engine would refuse.
  const schemaPresent = existsSync(SCHEMA);
  it.skipIf(!schemaPresent)('is copied character-for-character from task-contract.schema.json', () => {
    const schema = JSON.parse(readFileSync(SCHEMA, 'utf8')) as {
      $defs: { repoPath: { pattern: string }; absolutePath: { pattern: string } };
    };
    expect(REPO_PATH_PATTERN).toBe(schema.$defs.repoPath.pattern);
    expect(ABSOLUTE_PATH_PATTERN).toBe(schema.$defs.absolutePath.pattern);
  });

  it('accepts a repo-relative scope and an absolute one outside the repo', () => {
    expect(isWorkPath('apps/desktop/src/features')).toBe(true);
    expect(isWorkPath('.')).toBe(true);
    expect(isWorkPath('C:/Users/Admin/Desktop/some-project')).toBe(true);
    expect(isWorkPath('/home/gev/work')).toBe(true);
  });

  it('refuses every escape the schema refuses', () => {
    expect(isWorkPath('../secrets')).toBe(false);
    expect(isWorkPath('apps/../../etc')).toBe(false);
    expect(isWorkPath('apps\\desktop')).toBe(false); // backslash smuggles a separator
    expect(isWorkPath('C:x')).toBe(false); // drive-relative
    expect(isWorkPath('apps/**/*.ts')).toBe(false); // a glob is not provably literal
    expect(isWorkPath('~/Desktop')).toBe(false); // home-relative is not repo-relative
    expect(isWorkPath('/')).toBe(false); // a filesystem root is the absence of a scope
    expect(isWorkPath('C:/')).toBe(false);
    expect(isWorkPath('//host/share')).toBe(false); // UNC bypasses normal resolution
    expect(isWorkPath('')).toBe(false);
    expect(isWorkPath(' apps/desktop')).toBe(false);
    expect(isWorkPath(42)).toBe(false);
  });
});

describe('tier — derived from the agent actually spawned, never from a field', () => {
  it('recognises exactly the three tiers', () => {
    expect(isCapabilityTier('reader')).toBe(true);
    expect(isCapabilityTier('runner')).toBe(true);
    expect(isCapabilityTier('builder')).toBe(true);
    expect(isCapabilityTier('Builder')).toBe(false);
    expect(isCapabilityTier('architecture-audit--boundary-auditor')).toBe(false);
  });

  it('ignores a `tier` field that disagrees with the spawned agent', () => {
    // The CLI obeys the agent NAME. A payload claiming a narrow tier while spawning a wide
    // agent must not be able to paint a reassuring badge.
    const d = parseDelegation(spawn({ subagentType: 'builder', tier: 'reader' }))!;
    expect(d.tier).toBe('builder');
  });

  it('leaves tier null for a pack-role agent, without guessing one', () => {
    const d = parseDelegation(spawn({
      subagentType: 'architecture-audit--boundary-auditor',
      tools: ['Read', 'Edit', 'Write', 'Grep', 'Glob', 'Bash'],
    }))!;
    expect(d.tier).toBeNull();
    expect(d.tools).toContain('Edit');
  });
});

describe('capability — widen on disagreement, never narrow', () => {
  it('takes the agent definition when it agrees with the tier table', () => {
    const r = resolveTools('reader', ['Read', 'Grep', 'Glob'], 'agent_definition');
    expect(r).toEqual({ tools: ['Read', 'Grep', 'Glob'], toolsSource: 'agent_definition', toolsConflict: false });
  });

  it('shows the UNION and flags it when the two sources disagree', () => {
    // The live definition says the "reader" can also run Bash. Rendering the tier table's
    // narrower list would tell the owner he authorised less than he did.
    const r = resolveTools('reader', ['Read', 'Grep', 'Glob', 'Bash'], 'agent_definition');
    expect(r.toolsConflict).toBe(true);
    expect(r.tools).toContain('Bash');
    expect([...TIER_TOOLS.reader]).not.toContain('Bash');
  });

  it('falls back to the checked tier table, and says that is where it came from', () => {
    const r = resolveTools('runner', undefined, undefined);
    expect(r).toEqual({ tools: ['Read', 'Grep', 'Glob', 'Bash'], toolsSource: 'tier_table', toolsConflict: false });
  });

  it('reports nothing at all rather than inventing a tool list', () => {
    const r = resolveTools(null, undefined, undefined);
    expect(r).toEqual({ tools: [], toolsSource: 'unresolved', toolsConflict: false });
  });

  it('ignores a tool list whose source is not the agent definition', () => {
    // A list the backend did not read out of `.claude/agents/*.md` is a claim, not a grant.
    const r = resolveTools('builder', ['Read'], 'the_model_said_so');
    expect(r.toolsSource).toBe('tier_table');
    expect(r.tools).toEqual([...TIER_TOOLS.builder]);
  });
});

describe('grant — all of it, or none of it', () => {
  it('accepts a grant whose every path passes the grammar', () => {
    const { grant, grantProblem } = readGrant({
      scope: ['apps/desktop/src/features', 'C:/Users/Admin/Desktop/ui-work'],
      prohibitedScope: ['engine'],
    });
    expect(grantProblem).toBeNull();
    expect(grant?.scope).toHaveLength(2);
    expect(grant?.prohibitedScope).toEqual(['engine']);
  });

  it('rejects the WHOLE grant when one entry is malformed, and hands back the raw text', () => {
    // Keeping the three good paths and dropping the fourth would render a tidy grant that is
    // not the grant that was issued — and the dropped one is the interesting one.
    const r = readGrant({ scope: ['apps/desktop/src', '../../etc'], prohibitedScope: [] });
    expect(r.grant).toBeNull();
    expect(r.grantProblem).toBe('invalid:../../etc');
    expect(r.rawGrant?.scope).toEqual(['apps/desktop/src', '../../etc']);
  });

  it('treats an empty scope as a missing grant, not a narrow one', () => {
    expect(readGrant({ scope: [], prohibitedScope: [] }).grantProblem).toBe('not_stated');
  });

  it('treats an absent or malformed grant as not stated', () => {
    expect(readGrant(undefined).grantProblem).toBe('not_stated');
    expect(readGrant(null).grantProblem).toBe('not_stated');
    expect(readGrant('apps/desktop').grantProblem).toBe('not_stated');
    expect(readGrant({ scope: 'apps/desktop' }).grantProblem).toBe('not_stated');
    expect(readGrant({ scope: [1, 2] }).grantProblem).toBe('not_stated');
  });

  it('defaults enforcement to none, and accepts only the one value that means enforced', () => {
    expect(readGrant({ scope: ['apps'] }).grant?.enforcement).toBe('none');
    expect(readGrant({ scope: ['apps'], enforcement: true }).grant?.enforcement).toBe('none');
    expect(readGrant({ scope: ['apps'], enforcement: 'enforced' }).grant?.enforcement).toBe('none');
    expect(readGrant({ scope: ['apps'], enforcement: 'engine_enforce_scope' }).grant?.enforcement)
      .toBe('engine_enforce_scope');
  });
});

describe('parseDelegation — a card is a claim that this happened', () => {
  it('reads a well-formed spawn', () => {
    const d = parseDelegation(spawn())!;
    expect(d.id).toBe('toolu_1');
    expect(d.subagentType).toBe('builder');
    expect(d.tier).toBe('builder');
    expect(d.outcome).toBe('running');
    expect(d.grant?.scope).toEqual(['apps/desktop/src/features']);
  });

  it('refuses a payload with no id or no named subagent', () => {
    expect(parseDelegation(spawn({ id: '' }))).toBeNull();
    expect(parseDelegation(spawn({ id: undefined }))).toBeNull();
    expect(parseDelegation(spawn({ subagentType: null }))).toBeNull();
    expect(parseDelegation(null)).toBeNull();
    expect(parseDelegation('builder')).toBeNull();
    expect(parseDelegation(7)).toBeNull();
  });
});

describe('the event fold', () => {
  const spawned: DelegationEvent = { type: 'delegationSpawned', delegation: spawn() };

  it('settles a known delegation', () => {
    const list = applyDelegationEvent([], spawned);
    const done = applyDelegationEvent(list, {
      type: 'delegationSettled', id: 'toolu_1', outcome: 'ok', summary: 'done', endedAt: 'x',
    });
    expect(done[0].outcome).toBe('ok');
    expect(done[0].summary).toBe('done');
  });

  it('never materialises a delegation from its ending alone', () => {
    // A card built from a settle event carries no grant at all — "an agent ran and we cannot
    // say what it was allowed to do", drawn as if it were a record.
    const out = applyDelegationEvent([], {
      type: 'delegationSettled', id: 'toolu_ghost', outcome: 'ok',
    });
    expect(out).toEqual([]);
  });

  it('never doubles a delegation on a replayed spawn', () => {
    expect(applyDelegationEvent(applyDelegationEvent([], spawned), spawned)).toHaveLength(1);
  });

  it('calls an unreadable outcome unknown, never ok', () => {
    const out = reduceDelegationEvents([
      spawned,
      { type: 'delegationSettled', id: 'toolu_1', outcome: 'sort_of_worked' },
    ]);
    expect(out[0].outcome).toBe('unknown');
  });

  it('drops a spawn event whose payload the reader refuses', () => {
    expect(applyDelegationEvent([], { type: 'delegationSpawned', delegation: { id: 'x' } })).toEqual([]);
  });
});

describe('parseDelegationList — a persisted read', () => {
  it('keeps records it can read and drops the ones it cannot', () => {
    const out = parseDelegationList([spawn(), { id: 'no-agent' }, spawn({ id: 'toolu_2', outcome: 'error' })])!;
    expect(out.map((d: Delegation) => d.id)).toEqual(['toolu_1', 'toolu_2']);
    expect(out[1].outcome).toBe('error');
  });

  it('returns null for a reply that is not a list', () => {
    expect(parseDelegationList({ delegations: [] })).toBeNull();
    expect(parseDelegationList(null)).toBeNull();
  });

  it('leaves a record with no ending as running', () => {
    expect(parseDelegationRecord(spawn())!.outcome).toBe('running');
  });
});
