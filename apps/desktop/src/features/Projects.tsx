import { useEffect, useMemo, useState } from 'react';
import { useApp } from '../app/store';
import { useAsync } from '../hooks/useAsync';
import { desktop } from '../services/desktop';
import { Mark } from '../components/Ambient';
import { useToast } from '../components/toast';
import { Modal, FormRow, Input, Textarea, Select, Button } from '../components/ui';
import { PRIORITIES, PROJECT_STATUSES } from '../domain/enums';
import { priorityLabel, statusLabel } from '../domain/statusLabels';
import type { Project, Task } from '../domain/entities';
import { STR, type StrKey } from './Projects.strings';

// ── `projects` ❖ Հոսքերի դաշտ — the workstream field, dressed as the AI-OS mockup ──
// The mockup (views/projects.js · «Հոսքերի դաշտ») paints every project as an energy
// line whose colour is its state, over a `.surface .soft .lg .hud` field, then a
// portfolio-pulse board. This React port keeps that chrome but drives EVERY lane from
// the REAL `list_projects` command, expanding a selected lane into its real linked
// tasks (`list_tasks_by_project`) and status control (`set_project_status`). No
// fabricated stream: the mockup's momentum numbers, phase-spines, weekly sparkline
// and Bro's narrative "read" have NO backing in the real Project/Task entities, so
// they are OMITTED — the portfolio KPIs are live counts over the real projects, and
// the read panel states the governed read is pending rather than inventing one.

// project.status → shared aios state class (drives the --st-rgb colour token).
const STATUS_STATE: Record<string, string> = {
  planned: 'state-idle', active: 'state-working', blocked: 'state-blocked',
  completed: 'state-completed', archived: 'state-idle',
};
// project.status → foundation `.pill` tone (`.bad` is defined locally below).
const STATUS_PILL: Record<string, string> = {
  planned: 'off', active: 'live', blocked: 'bad', completed: 'mint', archived: 'off',
};
// project.status → GLYPH power-mark state (mockup rule: mark reflects real status).
const STATUS_MARK: Record<string, string> = {
  planned: 'idle', active: 'live', blocked: 'alert', completed: 'live', archived: 'idle',
};
const stState = (s: string) => STATUS_STATE[s] ?? 'state-idle';
const stPill = (s: string) => STATUS_PILL[s] ?? 'off';
const stMark = (s: string) => STATUS_MARK[s] ?? 'idle';
const LEGEND_ORDER = ['active', 'planned', 'blocked', 'completed', 'archived'];

// task.status → pill tone for the linked-tasks list.
const TASK_PILL: Record<string, string> = {
  inbox: 'off', planned: 'off', active: 'info', review: 'warn',
  blocked: 'bad', done: 'mint', cancelled: 'off',
};

// UI strings live in `./Projects.strings` (trilingual en/hy/ru). `L(key)` resolves
// the active language via the store's `lang`, falling back to English. Status
// labels are derived from the same table (keys `st_<status>`) and shared between
// the pills, the legend and the KPI tiles.

function NewProjectForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t, lang } = useApp();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState('normal');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .createProject({ name: name.trim(), description: description.trim(), priority, workspaceId: null })
      .then(() => { onCreated(); onClose(); })
      .catch((e: unknown) => { setError(e instanceof Error ? e.message : String(e)); setBusy(false); });
  };

  return (
    <Modal title={t('form.newProject')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('field.name')}>
        <Input value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.description')}>
        <Textarea value={description} onChange={(e) => setDescription(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.priority')}>
        <Select value={priority} onChange={(e) => setPriority(e.target.value)}>
          {PRIORITIES.map((p) => <option key={p} value={p}>{priorityLabel(p, lang)}</option>)}
        </Select>
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

function EditProjectForm({ project, onClose, onSaved }: { project: Project; onClose: () => void; onSaved: () => void }) {
  const { t, lang } = useApp();
  const toast = useToast();
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const [priority, setPriority] = useState(project.priority);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .updateProject(project.id, name.trim(), description, priority)
      .then(() => { toast(t('toast.saved'), 'success'); onSaved(); onClose(); })
      .catch((e: unknown) => { setError(e instanceof Error ? e.message : String(e)); setBusy(false); });
  };

  return (
    <Modal title={t('form.editProject')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('field.name')}>
        <Input value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.description')}>
        <Textarea value={description} onChange={(e) => setDescription(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.priority')}>
        <Select value={priority} onChange={(e) => setPriority(e.target.value)}>
          {PRIORITIES.map((p) => <option key={p} value={p}>{priorityLabel(p, lang)}</option>)}
        </Select>
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" onClick={save}>{t('action.save')}</Button>
      </div>
    </Modal>
  );
}

// ── The expanded lane detail — real overview + real linked tasks ──────────────
function ProjectDetail({
  project, statusLabels, L, onClose, onSaved,
}: {
  project: Project;
  statusLabels: Record<string, string>;
  L: (k: StrKey) => string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t, lang } = useApp();
  const s = useAsync(() => desktop.listTasksByProject(project.id), [project.id]);
  const [tab, setTab] = useState<'overview' | 'tasks'>('overview');
  const [editing, setEditing] = useState(false);

  const changeStatus = (status: string) => {
    desktop.setProjectStatus(project.id, status).then(() => onSaved()).catch(() => onSaved());
  };

  const tasks: Task[] = s.data ?? [];
  const doneCount = tasks.filter((x) => x.status === 'done').length;
  const pct = tasks.length ? Math.round((doneCount / tasks.length) * 100) : 0;
  const label = statusLabels[project.status] ?? project.status;

  return (
    <section className={`pf-detail surface soft ${stState(project.status)}`} aria-label={project.name}>
      {editing && <EditProjectForm project={project} onClose={() => setEditing(false)} onSaved={onSaved} />}

      <div className="pd-head">
        <span className="pd-face"><Mark state={stMark(project.status)} size={38} /></span>
        <div className="pd-id">
          <h2>{project.name}</h2>
          <span className={`pill ${stPill(project.status)}`}>{label}</span>
        </div>
        <Button small variant="ghost" onClick={onClose}>{t('action.viewAll')}</Button>
      </div>

      <div className="pd-tabs" role="tablist" aria-label={project.name}>
        <button type="button" role="tab" aria-selected={tab === 'overview'}
          className={`pd-tab${tab === 'overview' ? ' sel' : ''}`} onClick={() => setTab('overview')}>
          {t('projects.tab.overview')}
        </button>
        <button type="button" role="tab" aria-selected={tab === 'tasks'}
          className={`pd-tab${tab === 'tasks' ? ' sel' : ''}`} onClick={() => setTab('tasks')}>
          {t('projects.tab.tasks')}
        </button>
      </div>

      {tab === 'overview' ? (
        <div role="tabpanel">
          {project.description && <p className="muted pd-desc">{project.description}</p>}
          <div className="pd-facts">
            <div className="pd-fact">
              <span className="pd-fk">{t('field.status')}</span>
              <div className="pd-statusrow">
                <span className={`pill ${stPill(project.status)}`}>{label}</span>
                <Select value={project.status} onChange={(e) => changeStatus(e.target.value)}>
                  {PROJECT_STATUSES.map((st) => (
                    <option key={st} value={st}>{statusLabels[st] ?? st}</option>
                  ))}
                </Select>
              </div>
            </div>
            <div className="pd-fact">
              <span className="pd-fk">{t('field.priority')}</span>
              <span className="tag">{priorityLabel(project.priority, lang)}</span>
            </div>
          </div>
          <div style={{ marginTop: 'var(--s4)' }}>
            <Button small variant="primary" onClick={() => setEditing(true)}>{t('action.edit')}</Button>
          </div>
        </div>
      ) : (
        <div role="tabpanel">
          <div className="pd-block-head">
            <span className="micro">{t('projects.linkedTasks')}</span>
            {tasks.length > 0 && (
              <span className="micro pd-prog-lbl">{`${doneCount}/${tasks.length} ${L('tasksDone')}`}</span>
            )}
          </div>

          {tasks.length > 0 && (
            <div className="pd-meter" aria-hidden="true"><span style={{ width: `${pct}%` }} /></div>
          )}

          {s.loading && s.data === null ? (
            <p className="muted" aria-live="polite">{L('tasksBuilding')}</p>
          ) : s.error ? (
            <div role="alert">
              <p className="muted">{`${L('tasksLinkLost')} ${s.error}`}</p>
              <Button small variant="ghost" onClick={s.reload}>{L('retry')}</Button>
            </div>
          ) : tasks.length === 0 ? (
            <div className="pd-empty" role="status">
              <div className="pd-empty-title">{t('state.empty')}</div>
              <p className="muted">{t('state.emptyHint')}</p>
            </div>
          ) : (
            <ul className="pd-tasks" role="list">
              {tasks.map((x) => (
                <li key={x.id} className="pd-row" role="listitem">
                  <span className="pd-tt">{x.title}</span>
                  <span className={`pill ${TASK_PILL[x.status] ?? 'off'}`}>{statusLabel(x.status, lang)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

export function Projects() {
  const { t, lang, focus, clearFocus } = useApp();
  const toast = useToast();
  const L = (k: StrKey) => STR[k][lang] ?? STR[k].en;
  const statusLabels: Record<string, string> = {
    planned: L('st_planned'), active: L('st_active'), blocked: L('st_blocked'),
    completed: L('st_completed'), archived: L('st_archived'),
  };

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const state = useAsync(() => desktop.listProjects(), []);

  const projects = useMemo(() => state.data ?? [], [state.data]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { planned: 0, active: 0, blocked: 0, completed: 0, archived: 0 };
    for (const p of projects) c[p.status] = (c[p.status] ?? 0) + 1;
    return c;
  }, [projects]);

  // Command-palette deep-link: open a project's detail then consume the target.
  useEffect(() => {
    if (focus?.kind === 'project') {
      setSelectedId(focus.id);
      clearFocus();
    }
  }, [focus]); // eslint-disable-line react-hooks/exhaustive-deps

  const selected = projects.find((p) => p.id === selectedId) ?? null;
  const announcement = selected
    ? `${selected.name} · ${statusLabels[selected.status] ?? selected.status}`
    : '';

  const header = (
    <div className="pageHead">
      <div>
        <span className="eyebrow">{L('eyebrow')}</span>
        <h1>{t('nav.projects')}</h1>
        <p className="sub">{t('projects.subtitle')}</p>
      </div>
      <div className="right">
        {projects.length > 0 && (
          <>
            <span className="pill live">{`${counts.active} ${L('activeWord')}`}</span>
            {counts.blocked > 0 && <span className="pill bad">{`${counts.blocked} ${L('blockedWord')}`}</span>}
            <span className="pill info">{`${projects.length} ${L('totalWord')}`}</span>
          </>
        )}
        <Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>
      </div>
    </div>
  );

  const creatingModal = creating && (
    <NewProjectForm
      onClose={() => setCreating(false)}
      onCreated={() => { state.reload(); toast(t('toast.created'), 'success'); }}
    />
  );

  // ── States: loading · error(link lost) · empty ──────────────────────────────
  if (state.loading && state.data === null) {
    return (
      <div className="v-projects">
        <style>{PF_CSS}</style>
        {header}{creatingModal}
        <section className="surface soft lg hud" aria-label={t('nav.projects')}>
          <i className="bracket tl" /><i className="bracket tr" /><i className="bracket bl" /><i className="bracket br" />
          <div className="muted" style={{ marginBottom: 14 }} aria-live="polite">{L('building')}</div>
          <div className="pf-skel" aria-hidden="true"><i /><i /><i /><i /></div>
        </section>
      </div>
    );
  }

  if (state.error) {
    return (
      <div className="v-projects">
        <style>{PF_CSS}</style>
        {header}{creatingModal}
        <section className="surface soft" role="alert" style={{ padding: 'var(--s6)' }}>
          <span className="eyebrow">{L('eyebrow')}</span>
          <p className="muted" style={{ margin: '10px 0 14px', maxWidth: '60ch' }}>{`${L('linkLost')} ${state.error}`}</p>
          <Button variant="ghost" onClick={state.reload}>{L('retry')}</Button>
        </section>
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="v-projects">
        <style>{PF_CSS}</style>
        {header}{creatingModal}
        <section className="surface soft pf-empty" role="status">
          <span className="pf-empty-glyph" aria-hidden="true">❖</span>
          <div className="pd-empty-title">{L('emptyTitle')}</div>
          <p className="muted">{L('emptyHint')}</p>
        </section>
      </div>
    );
  }

  // KPI tiles — live counts over the real projects (no fabricated momentum).
  const kpis: Array<{ n: number; word: string; st: string }> = [
    { n: counts.active, word: L('activeWord'), st: 'state-working' },
    { n: counts.blocked, word: L('blockedWord'), st: 'state-blocked' },
    { n: counts.completed, word: L('completedWord'), st: 'state-completed' },
    { n: projects.length, word: L('totalWord'), st: 'state-idle' },
  ];

  // ── Default: the workstream field + portfolio board ─────────────────────────
  return (
    <div className="v-projects">
      <style>{PF_CSS}</style>
      {header}{creatingModal}

      <span className="pf-sr" aria-live="polite">{announcement}</span>

      {/* HERO · the workstream field */}
      <section className="surface soft lg hud pf-field reveal" aria-label={t('nav.projects')}>
        <i className="bracket tl" /><i className="bracket tr" /><i className="bracket bl" /><i className="bracket br" />
        <div className="ticks" aria-hidden="true">{Array.from({ length: 9 }).map((_, i) => <i key={i} />)}</div>

        <div className="field-top">
          <span className="micro">{L('heroHint')}</span>
          <div className="pf-legend" aria-hidden="true">
            {LEGEND_ORDER.map((st) => (
              <span key={st} className={stState(st)}><i />{statusLabels[st]}</span>
            ))}
          </div>
        </div>

        <div className="pf-lanes">
          {projects.map((p) => {
            const label = statusLabels[p.status] ?? p.status;
            const sel = p.id === selectedId;
            return (
              <button
                key={p.id}
                type="button"
                className={`pf-lane ${stState(p.status)}${sel ? ' sel' : ''}`}
                aria-expanded={sel}
                aria-label={`${p.name} · ${label}`}
                onClick={() => setSelectedId(sel ? null : p.id)}
              >
                <span className="pf-lane-face"><Mark state={stMark(p.status)} size={30} /></span>
                <span className="pl-who">
                  <b>{p.name}</b>
                  <span className="micro">{priorityLabel(p.priority, lang)}</span>
                </span>
                <span className={`pill ${stPill(p.status)}`}>{label}</span>
              </button>
            );
          })}
        </div>
      </section>

      {selected && (
        <ProjectDetail
          project={selected}
          statusLabels={statusLabels}
          L={L}
          onClose={() => setSelectedId(null)}
          onSaved={() => state.reload()}
        />
      )}

      {/* SUB-BOARD · portfolio pulse (live counts) + Bro's read (governed, pending) */}
      <div className="sec-head" style={{ marginTop: 'var(--s5)' }}>
        <h2>{L('boardHead')}</h2>
        <span className="note">{L('boardNote')}</span>
      </div>

      <div className="pf-board">
        <section className="surface soft pf-pulse rise">
          <div className="pf-kpis">
            {kpis.map((k) => (
              <div key={k.word} className={`pf-kpi ${k.st}`}>
                <b>{k.n}</b>
                <span className="micro">{k.word}</span>
              </div>
            ))}
          </div>
          <div className="wire" aria-hidden="true" />
        </section>

        <section className="surface soft pf-read rise">
          <div className="read-top">
            <Mark state="thinking" size={40} />
            <span className="eyebrow">{L('readEyebrow')}</span>
          </div>
          <p className="read-body muted">{L('readPending')}</p>
        </section>
      </div>
    </div>
  );
}

// Field-internal styling (scoped under `.v-projects`, prefixed `pf-`/`pd-`) for the
// energy lanes, the portfolio board and the expanded detail. The panel chrome
// (surface/soft/lg/hud/bracket/ticks/eyebrow/pill/tag/wire/sec-head/pageHead/micro/
// muted) is the shared aios.css; colours resolve through the `--st-rgb` state token.
const PF_CSS = `
.v-projects .pf-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
.v-projects .pill.bad{color:var(--danger);border-color:rgb(var(--danger-rgb)/.32);background:rgb(var(--danger-rgb)/.09)}

.v-projects .pf-field{padding:var(--s6) var(--s5) var(--s5)}
.v-projects .field-top{display:flex;justify-content:space-between;align-items:center;gap:var(--s4);flex-wrap:wrap;margin-bottom:var(--s4)}
.v-projects .pf-legend{display:flex;gap:12px;flex-wrap:wrap}
.v-projects .pf-legend span{display:inline-flex;align-items:center;gap:5px;font-family:var(--f-mono);font-size:var(--t-micro);
  text-transform:uppercase;letter-spacing:.1em;font-weight:700;color:var(--ink-muted)}
.v-projects .pf-legend i{width:8px;height:8px;border-radius:2px;background:rgb(var(--st-rgb)/.85);box-shadow:0 0 6px rgb(var(--st-rgb)/.5)}

.v-projects .pf-lanes{display:grid;gap:10px}
.v-projects .pf-lane{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:var(--s4);
  width:100%;text-align:left;cursor:pointer;font:inherit;color:var(--ink);padding:12px 14px;border-radius:14px;
  border:1.5px solid rgb(var(--st-rgb)/.32);border-left-width:3px;
  background:linear-gradient(158deg,rgb(var(--raised-rgb)/.6),rgb(var(--surface-rgb)/.42));
  transition:transform var(--slow),border-color var(--slow),box-shadow var(--slow)}
.v-projects .pf-lane:hover{transform:translateY(-2px);border-color:rgb(var(--st-rgb)/.62)}
.v-projects .pf-lane:focus-visible{outline:2px solid var(--cyan-soft);outline-offset:3px}
.v-projects .pf-lane.sel{border-color:rgb(var(--st-rgb)/.85);box-shadow:0 0 20px -6px rgb(var(--st-rgb)/.5),var(--shadow-1)}
.v-projects .pf-lane.state-working{animation:pf-glow 2.8s cubic-bezier(.4,0,.2,1) infinite}
.v-projects .pf-lane.state-blocked{animation:pf-interrupt 1.4s ease-in-out infinite}
@keyframes pf-glow{0%,100%{box-shadow:0 0 8px -4px rgb(var(--st-rgb)/.3),var(--shadow-1)}
  50%{box-shadow:0 0 18px -3px rgb(var(--st-rgb)/.5),var(--shadow-1)}}
@keyframes pf-interrupt{0%,100%{border-left-color:rgb(var(--st-rgb)/.9)}50%{border-left-color:rgb(var(--st-rgb)/.3)}}
.v-projects .pf-lane-face{flex:0 0 auto}
.v-projects .pf-lane-face .mark{width:30px;height:30px}
.v-projects .pl-who{min-width:0}
.v-projects .pl-who b{font-family:var(--f-display);font-weight:700;font-size:14px;letter-spacing:-.01em;display:block;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.v-projects .pl-who .micro{display:block;margin-top:2px;text-transform:lowercase;letter-spacing:.02em;color:var(--ink-muted)}

/* portfolio board */
.v-projects .pf-board{display:grid;grid-template-columns:1.35fr 1fr;gap:var(--s4)}
@media(max-width:820px){.v-projects .pf-board{grid-template-columns:1fr}}
.v-projects .pf-pulse,.v-projects .pf-read{padding:var(--s5)}
.v-projects .pf-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:var(--s4)}
@media(max-width:560px){.v-projects .pf-kpis{grid-template-columns:repeat(2,1fr)}}
.v-projects .pf-kpi{display:flex;flex-direction:column;gap:5px}
.v-projects .pf-kpi b{font-family:var(--f-display);font-weight:800;font-size:clamp(22px,3vw,28px);line-height:1;color:rgb(var(--st-rgb))}
.v-projects .pf-read{display:flex;flex-direction:column;gap:12px}
.v-projects .read-top{display:flex;align-items:center;gap:12px}
.v-projects .read-top .mark{width:40px;height:40px;flex:0 0 auto}
.v-projects .read-body{font-size:13px;line-height:1.6;margin:0;max-width:58ch}

/* expanded detail */
.v-projects .pf-detail{margin-top:var(--s4);padding:var(--s5)}
.v-projects .pd-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:var(--s3)}
.v-projects .pd-face .mark{width:38px;height:38px}
.v-projects .pd-id{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.v-projects .pd-id h2{font-size:var(--t-h2);margin:0}
.v-projects .pd-head>:last-child{margin-left:auto}
.v-projects .pd-tabs{display:flex;gap:8px;margin:var(--s3) 0 var(--s4)}
.v-projects .pd-tab{font:inherit;font-family:var(--f-mono);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;
  height:28px;padding:0 12px;border-radius:8px;cursor:pointer;color:var(--ink-muted);
  border:1px solid rgb(var(--line-rgb)/.9);background:transparent;transition:color var(--fast),border-color var(--fast),background var(--fast)}
.v-projects .pd-tab:hover{color:var(--ink)}
.v-projects .pd-tab:focus-visible{outline:2px solid var(--cyan-soft);outline-offset:2px}
.v-projects .pd-tab.sel{color:var(--cyan);border-color:rgb(var(--cyan-rgb)/.4);background:rgb(var(--cyan-rgb)/.08)}
.v-projects .pd-desc{font-size:13px;line-height:1.55;margin:0 0 var(--s4);max-width:70ch}
.v-projects .pd-facts{display:grid;grid-template-columns:1fr 1fr;gap:var(--s4)}
@media(max-width:560px){.v-projects .pd-facts{grid-template-columns:1fr}}
.v-projects .pd-fact{display:flex;flex-direction:column;gap:6px;min-width:0}
.v-projects .pd-fk{font-family:var(--f-mono);font-size:8.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-muted)}
.v-projects .pd-statusrow{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.v-projects .pd-block-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}
.v-projects .pd-prog-lbl{color:var(--cyan-soft)}
.v-projects .pd-meter{height:6px;border-radius:99px;background:rgb(var(--line-rgb)/.9);overflow:hidden;margin-bottom:var(--s4)}
.v-projects .pd-meter span{display:block;height:100%;background:var(--cyan);box-shadow:0 0 10px rgb(var(--cyan-rgb)/.6);transition:width var(--slow)}
.v-projects .pd-tasks{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.v-projects .pd-row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 12px;border-radius:10px;
  border:1px solid rgb(var(--line-rgb)/.8);background:rgb(var(--raised-rgb)/.4)}
.v-projects .pd-tt{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}
.v-projects .pd-empty,.v-projects .pf-empty{text-align:center;padding:var(--s6) var(--s5);display:grid;gap:8px;place-items:center}
.v-projects .pf-empty-glyph{font-size:34px;color:var(--cyan-soft)}
.v-projects .pd-empty-title{font-family:var(--f-display);font-weight:700;font-size:17px}

/* loading skeleton */
.v-projects .pf-skel{display:grid;gap:10px}
.v-projects .pf-skel i{height:52px;border-radius:14px;
  background:linear-gradient(90deg,transparent,rgb(var(--cyan-rgb)/.12) 40%,rgb(var(--line-rgb)/.9) 50%,rgb(var(--cyan-rgb)/.12) 60%,transparent);
  background-size:200% 100%;animation:pf-shimmer 1.4s linear infinite}
.v-projects .pf-skel i:nth-child(2){width:88%}.v-projects .pf-skel i:nth-child(3){width:72%}.v-projects .pf-skel i:nth-child(4){width:80%}
@keyframes pf-shimmer{from{background-position:200% 0}to{background-position:-200% 0}}

@media(prefers-reduced-motion:reduce){
  .v-projects .pf-lane,.v-projects .pf-lane.state-working,.v-projects .pf-lane.state-blocked,
  .v-projects .pd-meter span,.v-projects .pf-skel i{animation:none;transition:none}
}
`;
