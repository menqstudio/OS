import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { useApp } from '../app/store';
import {
  Button, Skeleton, ErrorState, EmptyState,
  Modal, FormRow, Input, Textarea, Select, ConfirmDialog,
} from '../components/ui';
import { Mark } from '../components/Ambient';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { MEMORY_KINDS } from '../domain/enums';
import type { MemoryEntry } from '../domain/entities';

// ---------------------------------------------------------------------------
// §D `memory` page — re-skinned to the brops-aios «Ժամանակի հիշողություն /
// Temporal Field» mockup. Every value shown is REAL: the desktop memory store
// (`list_memory` / `create_memory` / `set_memory_pinned` / `delete_memory`).
// Fields the store records: scope, kind, content, pinned, createdAt, updatedAt.
// The mockup's fabricated instruments — the plotted temporal field (per-memory
// `t`/`y`/salience coordinates), the consolidation beam + scan telemetry, the
// consolidation ledger, per-memory confidence/recall/retention %, and the fixed
// "14 memories · 86% retention" counters — have NO backing in the `MemoryEntry`
// entity and are therefore OMITTED, never faked. Two §D concepts (the `[[name]]`
// link graph and sealed evidence) are derived honestly from real content, and
// where the store records nothing (an update/edit command) we render the honest
// "not wired / sealed" affordance the spec requires. Motion honours
// prefers-reduced-motion via the global aios.css.
// ---------------------------------------------------------------------------

// Bilingual inline strings for copy that has no shared i18n key yet (the thin
// pages inline the same way). `t()` is still used for every existing key. New
// Armenian labels are taken verbatim from the mockup's vocabulary.
type Lang = 'hy' | 'en' | 'ru';
function pick(lang: Lang, en: string, hy: string): string {
  return lang === 'hy' ? hy : en; // ru falls back to en, matching the shell
}

// Visual tone per memory kind → aios `.pill` modifier (presentation only — no
// data invented; the kind text itself is always rendered for non-visual convey).
const kindPill: Record<string, string> = {
  fact: 'info',
  preference: 'mint',
  note: 'off',
  reference: 'warn',
};

// `[[name]]` wiki-links parsed out of real memory content.
const LINK_RE = /\[\[([^\]\n]+)\]\]/g;
function extractLinks(text: string): string[] {
  const out: string[] = [];
  let m: RegExpExecArray | null;
  LINK_RE.lastIndex = 0;
  while ((m = LINK_RE.exec(text)) !== null) {
    const name = m[1].trim();
    if (name && !out.some((n) => n.toLowerCase() === name.toLowerCase())) out.push(name);
  }
  return out;
}

interface ResolvedLink {
  name: string;
  targetId: string | null; // a memory this reference resolves to, else null
  sealed: boolean; // true → references sealed / unavailable evidence
}

// Resolve one `[[name]]` against the loaded memories. A reference is honoured
// when another memory's scope matches it or its content mentions it. An
// explicit `sealed:` prefix, or a reference that resolves to nothing local, is
// treated as pointing at sealed / unavailable evidence.
function resolveLink(name: string, selfId: string, all: MemoryEntry[]): ResolvedLink {
  if (/^sealed:/i.test(name)) return { name, targetId: null, sealed: true };
  const needle = name.toLowerCase();
  const hit = all.find(
    (o) => o.id !== selfId &&
      (o.scope.toLowerCase() === needle || o.content.toLowerCase().includes(needle)),
  );
  return { name, targetId: hit ? hit.id : null, sealed: !hit };
}

function contentPreview(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length > 120 ? `${flat.slice(0, 117)}…` : flat;
}

// --- New entry (create is wired to the store) -------------------------------
function NewEntryForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = useApp();
  const [scope, setScope] = useState('global');
  const [kind, setKind] = useState('note');
  const [content, setContent] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = () => {
    if (!content.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .createMemory({ scope: scope.trim() || 'global', kind, content: content.trim() })
      .then(() => {
        onCreated();
        onClose();
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setBusy(false);
      });
  };

  return (
    <Modal title={t('memory.newEntry')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('memory.content')}>
        <Textarea value={content} autoFocus onChange={(e) => setContent(e.target.value)} />
      </FormRow>
      <FormRow label={t('memory.kind')}>
        <Select value={kind} onChange={(e) => setKind(e.target.value)}>
          {MEMORY_KINDS.map((k) => (
            <option key={k} value={k}>{k}</option>
          ))}
        </Select>
      </FormRow>
      <FormRow label={t('memory.scope')}>
        <Input value={scope} onChange={(e) => setScope(e.target.value)} />
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" disabled={busy} onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

// --- Edit entry (component built per §D; Save is honestly disabled because the
// desktop store exposes no `update_memory` command yet) ----------------------
function EditEntryForm({ entry, onClose }: { entry: MemoryEntry; onClose: () => void }) {
  const { t, lang } = useApp();
  const L = (en: string, hy: string) => pick(lang, en, hy);
  return (
    <Modal title={L('Edit memory', 'Խմբագրել հիշողությունը')} onClose={onClose}>
      <div className="mem-note" role="note">
        {L(
          'Editing a memory is not wired yet — the desktop store has no update command. Fields are shown read-only.',
          'Հիշողության խմբագրումը դեռ միացված չէ — store-ը թարմացման հրաման չունի։ Դաշտերը միայն ընթերցման համար են։',
        )}
      </div>
      <FormRow label={t('memory.content')}>
        <Textarea value={entry.content} readOnly />
      </FormRow>
      <FormRow label={t('memory.kind')}>
        <Input value={entry.kind} readOnly />
      </FormRow>
      <FormRow label={t('memory.scope')}>
        <Input value={entry.scope} readOnly />
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button
          variant="primary"
          disabled
          title={L('Editing arrives with the update command.', 'Խմբագրումը գալիս է թարմացման հրամանի հետ։')}
        >
          {t('action.save')}
        </Button>
      </div>
    </Modal>
  );
}

// --- Recall rail · detail of a selected memory ------------------------------
function MemoryDetail(
  { entry, links, blocked, fmtDate, onJump, onEdit, onPinToggle, onDelete }:
  {
    entry: MemoryEntry;
    links: ResolvedLink[];
    blocked: boolean;
    fmtDate: (raw: string) => string;
    onJump: (id: string) => void;
    onEdit: () => void;
    onPinToggle: () => void;
    onDelete: () => void;
  },
) {
  const { t, lang } = useApp();
  const L = (en: string, hy: string) => pick(lang, en, hy);
  const sealed = links.filter((l) => l.sealed);

  return (
    <div className="mr-detail" data-id={entry.id}>
      <div className="mr-head">
        <Mark state="idle" size={40} />
        <div className="mr-id">
          <span className="eyebrow">{`${entry.kind.toUpperCase()} · ${L('MEMORY', 'ՀԻՇՈՂՈՒԹՅՈՒՆ')}`}</span>
          <b>{entry.scope}</b>
        </div>
      </div>

      <div className="mr-flags">
        <span className={`pill ${kindPill[entry.kind] ?? 'info'}`}>{entry.kind}</span>
        {entry.pinned && <span className="pill info">{t('memory.pinned')}</span>}
        {blocked && <span className="pill warn">{L('Sealed', 'Կնքված')}</span>}
      </div>

      {blocked && (
        <div className="mem-blocked" role="status">
          <strong>{L('References sealed evidence', 'Հղում է կնքված ապացույցին')}</strong>
          <div className="micro" style={{ marginTop: 4, textTransform: 'none', letterSpacing: 0 }}>
            {L(
              'This memory points at evidence the local store cannot surface. The referenced material stays sealed:',
              'Այս հիշողությունը հղում է ապացույցի, որը լոկալ store-ը չի կարող ցուցադրել։ Հղված նյութը մնում է կնքված․',
            )}
          </div>
          <ul className="mem-links" style={{ marginTop: 6 }}>
            {sealed.map((l) => (
              <li key={l.name}>
                <span className="mem-link mem-link--sealed" title={L('Sealed / unavailable', 'Կնքված / անհասանելի')}>
                  ⬡ [[{l.name}]]
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="mem-body">{entry.content}</p>

      <div className="mr-tags">
        <span className="tag">{entry.scope}</span>
        <span className="tag">{entry.kind}</span>
      </div>

      <div className="mr-meta">
        <span>
          <b className="mono">{fmtDate(entry.createdAt)}</b>
          <i>{L('formed', 'ձևավորվել է')}</i>
        </span>
        <span>
          <b className="mono">{fmtDate(entry.updatedAt)}</b>
          <i>{L('updated', 'թարմացվել է')}</i>
        </span>
        <span>
          <b className="mono">{links.length}</b>
          <i>{L('links', 'հղում')}</i>
        </span>
      </div>

      {links.length > 0 && (
        <div className="mem-refs">
          <div className="micro">{L('References', 'Հղումներ')}</div>
          {/* text-list fallback for the link graph (a11y) */}
          <ul className="mem-links" role="list">
            {links.map((l) => (
              <li key={l.name}>
                {l.targetId ? (
                  <button
                    type="button"
                    className="mem-link mem-link--resolved"
                    onClick={() => l.targetId && onJump(l.targetId)}
                  >
                    [[{l.name}]]
                  </button>
                ) : (
                  <span className="mem-link mem-link--sealed">⬡ [[{l.name}]]</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mr-foot">
        <Button small onClick={onEdit} title={`${t('action.edit')} · e`}>{t('action.edit')}</Button>
        <Button small onClick={onPinToggle}>{entry.pinned ? t('memory.unpin') : t('memory.pin')}</Button>
        <span className="mr-forget">
          <Button small variant="ghost" onClick={onDelete}>
            {t('action.delete')}
          </Button>
        </span>
      </div>
    </div>
  );
}

export function Memory() {
  const { t, lang, focus, clearFocus } = useApp();
  const L = (en: string, hy: string) => pick(lang, en, hy);

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<MemoryEntry | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [kindFilter, setKindFilter] = useState<string>('all');
  const searchRef = useRef<HTMLInputElement | null>(null);

  const s = useAsync(() => desktop.listMemory(), []);
  const all = useMemo(() => s.data ?? [], [s.data]);

  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'short' }),
    [lang],
  );
  const fmtDate = (raw: string): string => {
    const v = raw?.trim();
    if (!v) return '—';
    const d = new Date(isNaN(Number(v)) ? v : Number(v));
    return isNaN(d.getTime()) ? v : dateFmt.format(d);
  };

  // Resolve every `[[name]]` reference across the loaded memories once.
  const linksByMemory = useMemo(() => {
    const map = new Map<string, ResolvedLink[]>();
    for (const m of all) {
      const refs = extractLinks(m.content).map((name) => resolveLink(name, m.id, all));
      map.set(m.id, refs);
    }
    return map;
  }, [all]);

  const blockedIds = useMemo(() => {
    const set = new Set<string>();
    for (const [id, refs] of linksByMemory) {
      if (refs.some((r) => r.sealed)) set.add(id);
    }
    return set;
  }, [linksByMemory]);

  // Aggregated link graph rendered as a text list (a11y fallback for a graph).
  const graph = useMemo(() => {
    const byName = new Map<string, { name: string; targetId: string | null; sealed: boolean; sources: number }>();
    for (const refs of linksByMemory.values()) {
      for (const r of refs) {
        const key = r.name.toLowerCase();
        const cur = byName.get(key);
        if (cur) cur.sources += 1;
        else byName.set(key, { name: r.name, targetId: r.targetId, sealed: r.sealed, sources: 1 });
      }
    }
    return [...byName.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [linksByMemory]);

  // Filter + search over real data.
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return all.filter((m) => {
      if (kindFilter !== 'all' && m.kind !== kindFilter) return false;
      if (!q) return true;
      return (
        m.content.toLowerCase().includes(q) ||
        m.scope.toLowerCase().includes(q) ||
        m.kind.toLowerCase().includes(q)
      );
    });
  }, [all, query, kindFilter]);

  const selected = useMemo(
    () => all.find((m) => m.id === selectedId) ?? null,
    [all, selectedId],
  );

  // Honest metric strip — derived ENTIRELY from the real memory array. The
  // mockup's fixed counters (14 memories, 4 sealed, 2 pinned, 86% retention) and
  // its retention telemetry have no backing in the store, so they are omitted;
  // only honestly-countable facts appear here.
  const pinnedCount = useMemo(() => all.filter((m) => m.pinned).length, [all]);
  const metrics = useMemo(() => [
    { v: all.length, label: L('memories · store', 'հիշողություն · store'), tone: '' },
    { v: pinnedCount, label: L('pinned', 'ամրակցված'), tone: 'info' },
    { v: blockedIds.size, label: L('sealed refs', 'կնքված հղում'), tone: 'mint' },
    { v: graph.length, label: L('links', 'հղում'), tone: '' },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [all.length, pinnedCount, blockedIds.size, graph.length, lang]);

  // Consume a command-palette / global-search deep-link (kind: 'memory').
  useEffect(() => {
    if (focus?.kind !== 'memory' || s.loading || s.data === null) return;
    if (s.data.some((m) => m.id === focus.id)) {
      setSelectedId(focus.id);
      clearFocus();
    }
  }, [focus, s.data, s.loading, clearFocus]);

  // Keyboard: `/` search · `n` new · `e` edit selected. `Enter` open is handled
  // natively by the focusable list-item buttons (and the search field below).
  const modalOpen = creating || editing !== null || pendingDelete !== null;
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const el = document.activeElement;
      const typing = el instanceof HTMLElement &&
        (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable);
      if (e.key === '/' && !typing) {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (e.key === 'n' && !typing && !modalOpen) {
        e.preventDefault();
        setCreating(true);
      } else if (e.key === 'e' && !typing && !modalOpen && selected) {
        e.preventDefault();
        setEditing(selected);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [modalOpen, selected]);

  const togglePin = (id: string, pinned: boolean) => {
    desktop.setMemoryPinned(id, pinned).then(() => s.reload()).catch(() => s.reload());
  };
  const remove = (id: string) => {
    setPendingDelete(null);
    desktop.deleteMemory(id).then(() => s.reload()).catch(() => s.reload());
  };

  // Live-region announcement of load state / result count.
  const liveMessage = s.loading && s.data === null
    ? L('Loading memories…', 'Հիշողությունները բեռնվում են…')
    : s.error
      ? L('Could not load memories.', 'Չհաջողվեց բեռնել հիշողությունները։')
      : all.length === 0
        ? L('Bro has no memories yet.', 'Bro-ն դեռ հիշողություններ չունի։')
        : L(`${filtered.length} of ${all.length} memories.`, `${filtered.length} / ${all.length} հիշողություն։`);

  const openFirst = () => {
    if (filtered.length > 0) setSelectedId(filtered[0].id);
  };

  const filterKinds = ['all', ...MEMORY_KINDS];

  return (
    <div className="v-memory">
      <style>{MEMORY_CSS}</style>

      <header className="pageHead">
        <div>
          <span className="eyebrow">{L('MEMORY FIELD · TEMPORAL FIELD', 'ՀԻՇՈՂՈՒԹՅԱՆ ԴԱՇՏ · TEMPORAL FIELD')}</span>
          <h1>{t('nav.memory')}</h1>
          <p className="sub">{t('memory.subtitle')}</p>
        </div>
        <div className="right">
          <span className="pill info">{L('Verifiable memory', 'Ստուգելի հիշողություն')}</span>
          <Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>
        </div>
      </header>

      {creating && <NewEntryForm onClose={() => setCreating(false)} onCreated={() => s.reload()} />}

      {editing && <EditEntryForm entry={editing} onClose={() => setEditing(null)} />}

      {pendingDelete && (
        <ConfirmDialog
          title={t('confirm.deleteTitle')}
          message={t('confirm.deleteBody')}
          confirmLabel={t('action.delete')}
          cancelLabel={t('action.cancel')}
          onConfirm={() => remove(pendingDelete)}
          onCancel={() => setPendingDelete(null)}
        />
      )}

      <div className="mem-sr-only" aria-live="polite" role="status">{liveMessage}</div>

      <div className="mboard mem-shell">
        {/* ── Memories browser ─────────────────────────────────────────── */}
        <section className="surface soft mem-browser">
          <div className="sec-head">
            <h2>{L('Memories', 'Հիշողություններ')}</h2>
            <span className="note">
              <b className="mono">{filtered.length}</b>{' / '}
              <b className="mono">{all.length}</b>{' '}
              {L('in field', 'դաշտում')}
            </span>
          </div>

          <Input
            ref={searchRef}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); openFirst(); } }}
            placeholder={L('Search memories…  ( / )', 'Փնտրիր հիշողություններ…  ( / )')}
            aria-label={L('Search memories', 'Փնտրիր հիշողություններ')}
          />

          <div className="mem-filters" role="group" aria-label={L('Filter by type', 'Զտել ըստ տեսակի')}>
            {filterKinds.map((k) => (
              <button
                key={k}
                type="button"
                className="chip mem-filter"
                aria-pressed={kindFilter === k}
                onClick={() => setKindFilter(k)}
              >
                {k === 'all' ? L('All', 'Բոլորը') : k}
              </button>
            ))}
          </div>

          {s.loading && s.data === null ? (
            <Skeleton rows={5} />
          ) : s.error ? (
            <ErrorState message={s.error} onRetry={s.reload} />
          ) : all.length === 0 ? (
            <EmptyState
              glyph="❖"
              title={L('Bro has no memories yet', 'Bro-ն դեռ հիշողություններ չունի')}
              hint={L('Create the first memory to build persistent context.', 'Ստեղծիր առաջին հիշողությունը՝ մշտական համատեքստ կառուցելու համար։')}
            />
          ) : filtered.length === 0 ? (
            <EmptyState
              glyph="◍"
              title={L('No memories match', 'Համընկնող հիշողություն չկա')}
              hint={L('Adjust the search or type filter.', 'Փոխիր որոնումը կամ տեսակի զտիչը։')}
            />
          ) : (
            <ul className="mem-list" role="list">
              {filtered.map((m) => {
                const active = m.id === selectedId;
                const isBlocked = blockedIds.has(m.id);
                return (
                  <li key={m.id}>
                    <button
                      type="button"
                      className={`mem-item${active ? ' mem-item--active' : ''}`}
                      aria-current={active ? 'true' : undefined}
                      onClick={() => setSelectedId(m.id)}
                    >
                      <span className="mem-item-top">
                        <span className={`pill ${kindPill[m.kind] ?? 'info'} mem-kind`}>{m.kind}</span>
                        <span className="micro mem-item-scope">{m.scope}</span>
                        {m.pinned && <span className="tag mem-flag">{t('memory.pinned')}</span>}
                        {isBlocked && (
                          <span className="tag mem-flag mem-flag--sealed">
                            {L('Sealed', 'Կնքված')}
                          </span>
                        )}
                      </span>
                      <span className="mem-item-body">{contentPreview(m.content)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* ── Recall rail + link graph ─────────────────────────────────── */}
        <div className="mem-right">
          <aside className="mrail" aria-live="polite">
            {selected ? (
              <MemoryDetail
                entry={selected}
                links={linksByMemory.get(selected.id) ?? []}
                blocked={blockedIds.has(selected.id)}
                fmtDate={fmtDate}
                onJump={(id) => setSelectedId(id)}
                onEdit={() => setEditing(selected)}
                onPinToggle={() => togglePin(selected.id, !selected.pinned)}
                onDelete={() => setPendingDelete(selected.id)}
              />
            ) : (
              <div className="mr-core">
                <div className="mr-head">
                  <Mark state="thinking" size={40} />
                  <div className="mr-id">
                    <span className="eyebrow">{L('MEMORY CORE', 'ՀԻՇՈՂՈՒԹՅԱՆ ՄԻՋՈՒԿ')}</span>
                    <b>{L('Pick a memory to inspect it', 'Ընտրիր հիշողություն՝ ստուգելու համար')}</b>
                  </div>
                </div>
                <p className="mr-body">
                  {L('Enter opens the focused item · n new · e edit · / search',
                    'Enter՝ բացել · n՝ նոր · e՝ խմբագրել · /՝ որոնում')}
                </p>
                <div className="mr-core-grid">
                  <div className="mc-cell"><b className="mono">{all.length}</b><span className="micro">{L('memories', 'հիշողություն')}</span></div>
                  <div className="mc-cell"><b className="mono">{pinnedCount}</b><span className="micro">{L('pinned', 'ամրակցված')}</span></div>
                  <div className="mc-cell"><b className="mono">{blockedIds.size}</b><span className="micro">{L('sealed refs', 'կնքված հղում')}</span></div>
                  <div className="mc-cell"><b className="mono">{graph.length}</b><span className="micro">{L('links', 'հղում')}</span></div>
                </div>
              </div>
            )}
          </aside>

          <section className="surface soft mem-graph">
            <div className="sec-head">
              <h2>{L('Link graph', 'Հղումների գրաֆ')}</h2>
              <span className="note">{L('derived from real [[links]]', 'իրական [[հղումներից]]')}</span>
            </div>
            {graph.length === 0 ? (
              <div className="micro" style={{ textTransform: 'none', letterSpacing: 0 }}>
                {L('No [[links]] between memories yet.', 'Հիշողությունների միջև դեռ [[հղումներ]] չկան։')}
              </div>
            ) : (
              <ul className="mem-links" role="list" aria-label={L('Memory links', 'Հիշողությունների հղումներ')}>
                {graph.map((g) => (
                  <li key={g.name} className="mem-graph-row">
                    {g.targetId ? (
                      <button
                        type="button"
                        className="mem-link mem-link--resolved"
                        onClick={() => g.targetId && setSelectedId(g.targetId)}
                      >
                        [[{g.name}]]
                      </button>
                    ) : (
                      <span className="mem-link mem-link--sealed">⬡ [[{g.name}]]</span>
                    )}
                    <span className="micro mem-graph-meta">
                      {g.sealed
                        ? L('sealed', 'կնքված')
                        : L(`${g.sources} ref${g.sources === 1 ? '' : 's'}`, `${g.sources} հղում`)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>

      {/* ── Honest metric strip (real derived counts only) ─────────────── */}
      {!s.error && all.length > 0 && (
        <section className="surface soft mem-metrics">
          <div className="sec-head">
            <h2>{L('Memory state', 'Հիշողության վիճակ')}</h2>
            <span className="note">{L('counted from the store', 'store-ից հաշված')}</span>
          </div>
          <div className="mstats">
            {metrics.map((x, i) => (
              <div
                key={i}
                className={`mstat${x.tone ? ` ms-${x.tone}` : ''}`}
                style={{ ['--i' as string]: i + 3 } as CSSProperties}
              >
                <b className="mono num">{x.v}</b>
                <span className="micro">{x.label}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

// Local styles — scoped under `.v-memory`; reuse aios tokens. The temporal-field
// hero, consolidation beam/ledger and retention telemetry from the mockup are
// intentionally NOT rendered (their data is fabricated); these styles dress the
// real browser · recall-rail · link-graph · honest-metric surfaces only.
const MEMORY_CSS = `
.v-memory .mem-sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
.v-memory .mem-shell { align-items: start; }
.v-memory .mem-browser, .v-memory .mem-graph, .v-memory .mem-metrics { padding: var(--s5); }
.v-memory .mem-browser { display: grid; gap: var(--s4); }
.v-memory .mem-right { display: grid; gap: var(--s5); }

.v-memory .mem-filters { display: flex; flex-wrap: wrap; gap: 6px; }
.v-memory .mem-filter { height: 26px; padding: 0 11px; font-size: var(--t-micro); text-transform: capitalize; cursor: pointer; }
.v-memory .mem-filter[aria-pressed="true"] { color: var(--cyan); border-color: rgb(var(--cyan-rgb)/.5);
  background: rgb(var(--cyan-rgb)/.09); box-shadow: 0 0 16px rgb(var(--cyan-rgb)/.12); }

.v-memory .mem-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px;
  max-height: 62vh; overflow-y: auto; }
.v-memory .mem-item { display: flex; flex-direction: column; gap: 6px; width: 100%; text-align: left;
  background: rgb(var(--raised-rgb)/.4); color: var(--ink); cursor: pointer; font: inherit;
  border: 1px solid rgb(var(--line-rgb)/.7); border-radius: var(--r); padding: 10px 12px;
  transition: background var(--fast), border-color var(--fast), transform var(--fast); }
.v-memory .mem-item:hover { border-color: rgb(var(--cyan-rgb)/.35); transform: translateY(-1px); }
.v-memory .mem-item:focus-visible { outline: none; border-color: var(--cyan); box-shadow: 0 0 0 2px rgb(var(--cyan-rgb)/.4); }
.v-memory .mem-item--active { border-color: rgb(var(--cyan-rgb)/.55); background: rgb(var(--cyan-rgb)/.08); }
.v-memory .mem-item-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.v-memory .mem-kind { text-transform: capitalize; }
.v-memory .mem-item-scope { color: var(--ink-muted); }
.v-memory .mem-flag { color: var(--cyan-soft); }
.v-memory .mem-flag--sealed { color: var(--warning); border-color: rgb(var(--warning-rgb)/.32); }
.v-memory .mem-item-body { font-size: var(--t-small); color: var(--ink-muted); overflow: hidden;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }

.v-memory .mr-flags { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: var(--s4); }
.v-memory .mem-body { white-space: pre-wrap; line-height: 1.55; font-size: var(--t-small);
  color: var(--ink); margin: 0 0 var(--s4); }
.v-memory .mr-forget { display: inline-flex; }
.v-memory .mr-forget:hover .btn { color: var(--danger); border-color: rgb(var(--danger-rgb)/.4); }

.v-memory .mem-refs { margin-top: var(--s4); display: grid; gap: 6px; }
.v-memory .mem-blocked { border: 1px solid rgb(var(--danger-rgb)/.34);
  background: rgb(var(--danger-rgb)/.08); border-radius: var(--r); padding: 10px 12px; margin-bottom: var(--s4); }
.v-memory .mem-blocked strong { color: var(--danger); }
.v-memory .mem-links { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.v-memory .mem-graph-row { display: flex; align-items: center; justify-content: space-between; gap: var(--s3); }
.v-memory .mem-graph-meta { color: var(--ink-muted); }
.v-memory .mem-link { font-family: var(--f-mono); font-size: var(--t-micro); border-radius: var(--r-sm);
  padding: 3px 7px; border: 1px solid rgb(var(--line-rgb)/.7); background: transparent; color: var(--ink-muted); }
.v-memory .mem-link--resolved { background: rgb(var(--cyan-rgb)/.09); color: var(--cyan);
  border-color: rgb(var(--cyan-rgb)/.3); cursor: pointer; }
.v-memory .mem-link--resolved:hover { border-color: rgb(var(--cyan-rgb)/.5); box-shadow: 0 0 14px rgb(var(--cyan-rgb)/.12); }
.v-memory .mem-link--sealed { color: var(--warning); background: rgb(var(--warning-rgb)/.08);
  border-color: rgb(var(--warning-rgb)/.28); }

.v-memory .mem-note { font-size: var(--t-small); color: var(--warning);
  background: rgb(var(--warning-rgb)/.1); border: 1px solid rgb(var(--warning-rgb)/.3);
  border-radius: var(--r); padding: 9px 12px; margin-bottom: var(--s4); }

@media (max-width: 960px) {
  .v-memory .mem-list { max-height: none; }
}
@media (prefers-reduced-motion: reduce) {
  .v-memory .mem-item { transition: none; }
}
`;
