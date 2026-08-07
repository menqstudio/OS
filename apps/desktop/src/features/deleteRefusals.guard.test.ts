/// <reference types="vite/client" />
import { describe, it, expect } from 'vitest';

/**
 * Regression guard for the "optimistic delete, swallowed refusal" class of defect.
 *
 * Six hard-delete commands are DENIED in the window capability set
 * (`src-tauri/capabilities/default.json`): delete_conversation, delete_knowledge,
 * delete_library_item, delete_research_item, delete_memory, delete_event. A refusal is
 * therefore the ORDINARY outcome, not an edge case.
 *
 * Several pages ended their delete chain in `.catch(() => s.reload())` — or had no
 * `.catch` at all — so the rejection was discarded, the row came straight back on the
 * reload, and the user was never told the store had refused. This test fails on any
 * delete call whose rejection handler discards the error, so the pattern cannot return.
 */
const sources = import.meta.glob('../{features,components}/*.tsx', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

/** A `desktop.deleteX(...)` promise chain whose `.catch` takes no error argument. */
const SWALLOWED = /\.delete[A-Z][A-Za-z]*\([^;]*?\.catch\(\s*(?:\(\s*\)|_)\s*=>/gs;

/** Every `desktop.deleteX(` call site, so each can be checked for a rejection handler. */
const DELETE_CALL = /\.delete[A-Z][A-Za-z]*\(/g;
/** How far past the call the handler may appear — comfortably longer than any chain here. */
const CHAIN_WINDOW = 900;

const basename = (p: string) => p.slice(p.lastIndexOf('/') + 1);

describe('a refused delete is always surfaced, never swallowed', () => {
  it('discovers the view sources', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(20);
  });

  it('no delete chain discards its rejection', () => {
    const offenders: string[] = [];
    for (const [path, src] of Object.entries(sources)) {
      SWALLOWED.lastIndex = 0;
      if (SWALLOWED.test(src)) offenders.push(`${basename(path)}: .catch() ignores the refusal`);
    }
    expect(
      offenders,
      'Inspect the rejection and render it — the user must be able to read why nothing was deleted',
    ).toEqual([]);
  });

  it('every delete chain has a rejection handler at all', () => {
    const offenders: string[] = [];
    for (const [path, src] of Object.entries(sources)) {
      DELETE_CALL.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = DELETE_CALL.exec(src)) !== null) {
        const chain = src.slice(m.index, m.index + CHAIN_WINDOW);
        if (!chain.includes('.catch(')) {
          offenders.push(`${basename(path)}: ${chain.split('\n')[0].trim()} has no .catch`);
        }
      }
    }
    expect(
      offenders,
      'A delete with no .catch leaves an unhandled rejection and a row that silently reappears',
    ).toEqual([]);
  });
});
