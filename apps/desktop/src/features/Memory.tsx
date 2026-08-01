import { useEffect, useMemo, useRef, useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Panel, Button, Badge, Skeleton, ErrorState, EmptyState,
  Modal, FormRow, Input, Textarea, Select, ConfirmDialog,
} from '../components/ui';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { MEMORY_KINDS, type Tone } from '../domain/enums';
import type { MemoryEntry } from '../domain/entities';

// ---------------------------------------------------------------------------
// §D `memory` page. Data source: desktop memory store (`list_memory` /
// `create_memory` / `set_memory_pinned` / `delete_memory`). Fields the store
// records: scope, kind, content, pinned. Two concepts the §D spec lists —
// `[[name]]` link graph and per-memory confidence — are NOT columns in the
// store. We derive links honestly from real content and, where the store
// records nothing (confidence, an update/edit command, sealed-evidence flags),
// we render the honest "not recorded / unavailable" affordance the spec's
// `blocked`/empty states require rather than fabricate values.
// ---------------------------------------------------------------------------

// Bilingual inline strings for copy that has no shared i18n key yet (the thin
// pages inline the same way). `t()` is still used for every existing key.
type Lang = 'hy' | 'en' | 'ru';
function pick(lang: Lang, en: string, hy: string): string {
  return lang === 'hy' ? hy : en; // ru falls back to en, matching the shell
}

// Visual tone per memory type (presentation only — no data invented).
const kindTone: Record<string, Tone> = {
  fact: 'info',
  preference: 'accent',
  note: 'neutral',
  reference: 'warning',
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

// --- Detail pane ------------------------------------------------------------
function MemoryDetail(
  { entry, links, blocked, onJump, onEdit, onPinToggle, onDelete }:
  {
    entry: MemoryEntry;
    links: ResolvedLink[];
    blocked: boolean;
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
    <Panel
      title={L('Detail', 'Մանրամասն')}
      actions={
        <span className="row" style={{ gap: 8 }}>
          <Button small onClick={onEdit} title={`${t('action.edit')} · e`}>{t('action.edit')}</Button>
          <Button small onClick={onPinToggle}>{entry.pinned ? t('memory.unpin') : t('memory.pin')}</Button>
          <Button
            small
            variant="ghost"
            disabled
            title={t('action.deleteDisabledSafety')}
            onClick={onDelete}
          >
            {t('action.delete')}
          </Button>
        </span>
      }
    >
      <div className="stack">
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <Badge tone={kindTone[entry.kind] ?? 'accent'}>{entry.kind}</Badge>
          <span className="muted">{entry.scope}</span>
          {entry.pinned && <Badge tone="warning">{t('memory.pinned')}</Badge>}
          {blocked && <Badge tone="danger">{L('Blocked', 'Արգելափակված')}</Badge>}
        </div>

        {blocked && (
          <div className="mem-blocked" role="status">
            <strong>{L('References sealed evidence', 'Հղում է կնքված ապացույցին')}</strong>
            <div className="muted" style={{ marginTop: 4 }}>
              {L(
                'This memory points at evidence the local store cannot surface. The referenced material stays sealed:',
                'Այս հիշողությունը հղում է ապացույցի, որը լոկալ store-ը չի կարող ցուցադրել։ Հղված նյութը մնում է կնքված․',
              )}
            </div>
            <ul className="mem-links" style={{ marginTop: 6 }}>
              {sealed.map((l) => (
                <li key={l.name}>
                  <span className="mem-link mem-link--sealed" title={L('Sealed / unavailable', 'Կնքված / անհասանելի')}>
                    🔒 [[{l.name}]]
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="mem-detail-content">{entry.content}</div>

        <div className="mem-meta">
          <div className="field">
            <span className="field-label">{L('Confidence', 'Վստահություն')}</span>
            <span className="muted" title={L('The memory store does not record a confidence score yet.', 'Store-ը դեռ վստահության միավոր չի պահում։')}>
              {L('not recorded', 'չգրանցված')}
            </span>
          </div>
          <div className="field">
            <span className="field-label">{L('Links', 'Հղումներ')}</span>
            <span>{links.length}</span>
          </div>
        </div>

        {links.length > 0 && (
          <div className="stack" style={{ gap: 6 }}>
            <div className="field-label">{L('References', 'Հղումներ')}</div>
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
                    <span className="mem-link mem-link--sealed">🔒 [[{l.name}]]</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Panel>
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
    <>
      <style>{MEMORY_CSS}</style>

      <PageHeader
        title={t('nav.memory')}
        subtitle={t('memory.subtitle')}
        actions={<Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>}
      />

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

      <div className="chat-layout">
        <Panel title={L('Memories', 'Հիշողություններ')}>
          <div className="stack">
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
                  className={`mem-chip${kindFilter === k ? ' mem-chip--active' : ''}`}
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
                    <li key={m.id} role="listitem">
                      <button
                        type="button"
                        className={`mem-item${active ? ' mem-item--active' : ''}`}
                        aria-current={active ? 'true' : undefined}
                        onClick={() => setSelectedId(m.id)}
                      >
                        <span className="mem-item-top">
                          <Badge tone={kindTone[m.kind] ?? 'accent'}>{m.kind}</Badge>
                          <span className="muted mem-item-scope">{m.scope}</span>
                          {m.pinned && <span className="mem-pin" title={t('memory.pinned')}>📌</span>}
                          {isBlocked && <span className="mem-lock" title={L('References sealed evidence', 'Հղում է կնքված ապացույցին')}>🔒</span>}
                        </span>
                        <span className="mem-item-body">{contentPreview(m.content)}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </Panel>

        <div className="stack">
          {selected ? (
            <MemoryDetail
              entry={selected}
              links={linksByMemory.get(selected.id) ?? []}
              blocked={blockedIds.has(selected.id)}
              onJump={(id) => setSelectedId(id)}
              onEdit={() => setEditing(selected)}
              onPinToggle={() => togglePin(selected.id, !selected.pinned)}
              onDelete={() => setPendingDelete(selected.id)}
            />
          ) : (
            <Panel>
              <EmptyState
                glyph="❖"
                title={L('Pick a memory to inspect it', 'Ընտրիր հիշողություն՝ ստուգելու համար')}
                hint={L('Enter opens the focused item · n new · e edit · / search', 'Enter՝ բացել · n՝ նոր · e՝ խմբագրել · /՝ որոնում')}
              />
            </Panel>
          )}

          <Panel title={L('Link graph', 'Հղումների գրաֆ')}>
            {graph.length === 0 ? (
              <div className="muted">
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
                      <span className="mem-link mem-link--sealed">🔒 [[{g.name}]]</span>
                    )}
                    <span className="muted mem-graph-meta">
                      {g.sealed
                        ? L('sealed', 'կնքված')
                        : L(`${g.sources} ref${g.sources === 1 ? '' : 's'}`, `${g.sources} հղում`)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </>
  );
}

// Local styles — scoped by `mem-` prefix; reuse tokens + existing chat-layout.
const MEMORY_CSS = `
.mem-sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
.mem-filters { display: flex; flex-wrap: wrap; gap: 6px; }
.mem-chip { background: transparent; border: 1px solid var(--brops-border);
  color: var(--brops-muted); border-radius: var(--menq-radius-pill);
  padding: 3px 10px; font-size: 12px; font-weight: 600; cursor: pointer; text-transform: capitalize;
  transition: background var(--menq-motion-fast), border-color var(--menq-motion-fast), color var(--menq-motion-fast); }
.mem-chip:hover { background: var(--menq-color-hover); }
.mem-chip--active { color: var(--brops-accent); border-color: var(--brops-accent); background: var(--menq-color-selected); }
.mem-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.mem-item { display: flex; flex-direction: column; gap: 5px; width: 100%; text-align: left;
  background: transparent; color: var(--brops-text); cursor: pointer;
  border: 1px solid transparent; border-radius: var(--menq-radius-md); padding: 9px 11px; font: inherit;
  transition: background var(--menq-motion-fast), border-color var(--menq-motion-fast); }
.mem-item:hover { background: var(--menq-color-hover); }
.mem-item--active { background: var(--menq-color-selected); border-color: var(--brops-accent); }
.mem-item-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mem-item-scope { font-size: 12px; }
.mem-pin, .mem-lock { font-size: 12px; }
.mem-item-body { font-size: 13px; color: var(--brops-text); overflow: hidden;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.mem-detail-content { white-space: pre-wrap; line-height: 1.5; }
.mem-meta { display: flex; gap: var(--menq-space-5); flex-wrap: wrap; }
.mem-note { font-size: 12px; color: var(--menq-color-warning);
  background: color-mix(in srgb, var(--menq-color-warning) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--menq-color-warning) 30%, transparent);
  border-radius: var(--menq-radius-md); padding: 8px 11px; margin-bottom: var(--menq-space-4); }
.mem-blocked { border: 1px solid color-mix(in srgb, var(--menq-color-danger) 34%, transparent);
  background: color-mix(in srgb, var(--menq-color-danger) 10%, transparent);
  border-radius: var(--menq-radius-md); padding: 10px 12px; }
.mem-blocked strong { color: var(--menq-color-danger); }
.mem-links { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.mem-graph-row { display: flex; align-items: center; justify-content: space-between; gap: var(--menq-space-3); }
.mem-graph-meta { font-size: 12px; }
.mem-link { font-family: var(--menq-font-mono); font-size: 12px; border-radius: var(--menq-radius-sm);
  padding: 2px 6px; border: 1px solid var(--brops-border); }
.mem-link--resolved { background: var(--menq-color-selected); color: var(--brops-accent);
  border-color: transparent; cursor: pointer; }
.mem-link--resolved:hover { filter: brightness(1.08); }
.mem-link--sealed { color: var(--menq-color-danger);
  background: color-mix(in srgb, var(--menq-color-danger) 10%, transparent); border-color: transparent; }
@media (prefers-reduced-motion: reduce) {
  .mem-item, .mem-chip { transition: none; }
}
`;
