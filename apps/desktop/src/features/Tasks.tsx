import { useEffect, useMemo, useState } from 'react';
import { useApp } from '../app/store';
import {
  PageHeader, Button, Badge, Async, Modal, FormRow, Input, Textarea, Select,
} from '../components/ui';
import { Mark } from '../components/Ambient';
import { desktop } from '../services/desktop';
import { useAsync } from '../hooks/useAsync';
import { useToast } from '../components/toast';
import { statusTone, PRIORITIES, TASK_STATUSES } from '../domain/enums';
import type { Task } from '../domain/entities';
import type { DictKey } from '../i18n';

// Mission board — the brops-aios "Առաքելություն" reskin. Lanes group tasks by
// their REAL status (the full status vocabulary maps onto the four mockup lanes
// so no task is ever invisible). Card visuals, the mission hero metrics, the
// risk pill and the "free the blocker" flow are all driven by real data
// (listTasks / listProjects / listTaskDependencies / setTaskStatus). Nothing —
// no crew avatars, no critical-path rail, no fabricated counts — is invented.
const LANES: { id: string; nm: string; tone: '' | 'info' | 'warn' | 'mint'; statuses: string[] }[] = [
  { id: 'queue', nm: 'Հերթ',       tone: '',     statuses: ['inbox', 'planned'] },
  { id: 'prog',  nm: 'Ընթացքում',  tone: 'info', statuses: ['active', 'review'] },
  { id: 'block', nm: 'Արգելափակ',  tone: 'warn', statuses: ['blocked'] },
  { id: 'done',  nm: 'Ավարտ',      tone: 'mint', statuses: ['done', 'cancelled'] },
];

// Real task status → the mockup's card left-rail state class (purely visual).
const STATE_CLASS: Record<string, string> = {
  active: 'state-working', review: 'state-thinking', blocked: 'state-blocked', done: 'state-completed',
};
// Real priority → the mockup's prio chip (label + class). low/normal collapse to "mid".
const PRIO: Record<string, { lab: string; cls: string }> = {
  critical: { lab: 'ԿՐԻՏ', cls: 'crit' },
  high:     { lab: 'ԲԱՐՁՐ', cls: 'high' },
  normal:   { lab: 'ՄԻՋ', cls: 'mid' },
  low:      { lab: 'ՄԻՋ', cls: 'mid' },
};

const laneOf = (status: string) => LANES.find((l) => l.statuses.includes(status));

function NewTaskForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = useApp();
  const projects = useAsync(() => desktop.listProjects(), []);
  const [title, setTitle] = useState('');
  const [priority, setPriority] = useState('normal');
  const [projectId, setProjectId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = () => {
    if (!title.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .createTask({ title: title.trim(), description: '', priority, projectId: projectId || null, assignedAgentId: null })
      .then(() => { onCreated(); onClose(); })
      .catch((e: unknown) => { setError(e instanceof Error ? e.message : String(e)); setBusy(false); });
  };

  return (
    <Modal title={t('form.newTask')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <FormRow label={t('field.title')}>
        <Input value={title} autoFocus onChange={(e) => setTitle(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.priority')}>
        <Select value={priority} onChange={(e) => setPriority(e.target.value)}>
          {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
        </Select>
      </FormRow>
      <FormRow label={t('field.project')}>
        <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          <option value="">{t('field.none')}</option>
          {(projects.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>
      </FormRow>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" onClick={submit}>{t('action.create')}</Button>
      </div>
    </Modal>
  );
}

function TaskDetail({ task, onClose, onSaved }: { task: Task; onClose: () => void; onSaved: () => void }) {
  const { t } = useApp();
  const toast = useToast();
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
  const [priority, setPriority] = useState(task.priority);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Dependencies (blockers) for this task, plus the full task list to pick new
  // blockers from. Both reload explicitly after a mutation — never on render.
  const deps = useAsync(() => desktop.listTaskDependencies(task.id), [task.id]);
  const allTasks = useAsync(() => desktop.listTasks(), []);
  const [pick, setPick] = useState('');

  const depList = deps.data ?? [];
  const available = (allTasks.data ?? []).filter(
    (x) => x.id !== task.id && !depList.some((d) => d.id === x.id),
  );

  const addDep = () => {
    if (!pick) return;
    setError(null);
    desktop
      .addTaskDependency(task.id, pick)
      .then(() => { deps.reload(); setPick(''); toast(t('toast.saved'), 'success'); })
      .catch((e: unknown) => { setError(e instanceof Error ? e.message : String(e)); });
  };

  const removeDep = (depId: string) => {
    setError(null);
    desktop
      .removeTaskDependency(task.id, depId)
      .then(() => { deps.reload(); })
      .catch((e: unknown) => { setError(e instanceof Error ? e.message : String(e)); });
  };

  const save = () => {
    if (!title.trim() || busy) return;
    setBusy(true);
    setError(null);
    desktop
      .updateTask(task.id, title.trim(), description, priority)
      .then(() => { toast(t('toast.saved'), 'success'); onSaved(); onClose(); })
      .catch((e: unknown) => { setError(e instanceof Error ? e.message : String(e)); setBusy(false); });
  };

  return (
    <Modal title={t('form.editTask')} onClose={onClose}>
      {error && <div className="form-error">{error}</div>}
      <div className="row" style={{ gap: 8, marginBottom: 12 }}>
        <Badge tone={statusTone[task.status] ?? 'neutral'}>{task.status.replace(/_/g, ' ')}</Badge>
      </div>
      <FormRow label={t('field.title')}>
        <Input value={title} autoFocus onChange={(e) => setTitle(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.description')}>
        <Textarea value={description} onChange={(e) => setDescription(e.target.value)} />
      </FormRow>
      <FormRow label={t('field.priority')}>
        <Select value={priority} onChange={(e) => setPriority(e.target.value)}>
          {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
        </Select>
      </FormRow>

      <FormRow label={t('tasks.dependencies')}>
        <div className="stack" style={{ gap: 8 }}>
          {depList.length === 0 && <span className="muted">{t('tasks.noDependencies')}</span>}
          {depList.map((d) => (
            <div key={d.id} className="row" style={{ gap: 8, justifyContent: 'space-between' }}>
              <span>{d.title}</span>
              <Button variant="ghost" small onClick={() => removeDep(d.id)}>{t('tasks.remove')}</Button>
            </div>
          ))}
          <div className="row" style={{ gap: 8 }}>
            <Select value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">{t('tasks.pickBlocker')}</option>
              {available.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}
            </Select>
            <Button variant="ghost" small onClick={addDep} disabled={!pick}>{t('tasks.addDependency')}</Button>
          </div>
        </div>
      </FormRow>

      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button variant="primary" onClick={save}>{t('action.save')}</Button>
      </div>
    </Modal>
  );
}

// The live mission clock — the one honestly-live HUD readout (no fabricated ETA,
// no auto-recalc). Ticks the wall clock and cleans up on unmount.
function MissionClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const p = (n: number) => (n < 10 ? '0' : '') + n;
  return (
    <span className="m-clock mono" aria-hidden="true">
      {p(now.getHours())}:{p(now.getMinutes())}:{p(now.getSeconds())}
    </span>
  );
}

// One board card. For blocked tasks it loads the task's REAL dependencies and
// surfaces them as the blocker note; the "Ազատել" button is a real status
// mutation (blocked → active), the honest equivalent of "freeing" the card.
function TaskCard({
  task, projectName, onOpen, onMove, t,
}: {
  task: Task;
  projectName?: string;
  onOpen: (task: Task) => void;
  onMove: (task: Task, status: string) => void;
  t: (k: DictKey) => string;
}) {
  const isBlocked = task.status === 'blocked';
  const deps = useAsync(
    () => (isBlocked ? desktop.listTaskDependencies(task.id) : Promise.resolve([] as Task[])),
    [task.id, isBlocked],
  );
  const stateCls = STATE_CLASS[task.status] ?? '';
  const prio = PRIO[task.priority] ?? PRIO.normal;
  const blockers = deps.data ?? [];

  return (
    <article
      className={`mtask surface soft ${stateCls}`.trim()}
      tabIndex={0}
      aria-label={task.title}
      onClick={() => onOpen(task)}
      onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); onOpen(task); } }}
    >
      <span className="stream" aria-hidden="true" />
      <div className="mt-head">
        <span className={`prio prio-${prio.cls}`}>{prio.lab}</span>
        {task.dueAt && (
          <span className="mt-eta micro">{new Date(task.dueAt).toLocaleDateString()}</span>
        )}
      </div>
      <div className="mt-body">
        <div className="mt-title">{task.title}</div>
        {projectName && <div className="mt-zone micro">{projectName}</div>}
      </div>

      {isBlocked && (
        <>
          {blockers.length > 0 && (
            <div className="mt-deps">
              {blockers.map((d) => <span key={d.id} className="dep">{d.title}</span>)}
            </div>
          )}
          <div className="mt-block">
            <span className="mt-block-txt">
              <b>Արգելափակում</b>
              {deps.loading
                ? '…'
                : blockers.length > 0
                  ? blockers.map((d) => d.title).join(', ')
                  : t('tasks.noDependencies')}
            </span>
            <button
              className="chip mt-unblock"
              type="button"
              aria-label={`${t('action.open')}: ${task.title}`}
              onClick={(e) => { e.stopPropagation(); onMove(task, 'active'); }}
            >
              Ազատել
            </button>
          </div>
        </>
      )}

      <div className="mt-foot">
        <select
          className="mt-status"
          value={task.status}
          aria-label={`${t('field.status')}: ${task.title}`}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
          onChange={(e) => onMove(task, e.target.value)}
        >
          {TASK_STATUSES.map((sv) => (
            <option key={sv} value={sv}>{sv.replace(/_/g, ' ')}</option>
          ))}
        </select>
        {task.assignedAgentId && <span className="mt-own micro">{task.assignedAgentId}</span>}
      </div>
    </article>
  );
}

export function Tasks() {
  const { t, focus, clearFocus } = useApp();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [detail, setDetail] = useState<Task | null>(null);
  const [announce, setAnnounce] = useState('');
  const s = useAsync(() => desktop.listTasks(), []);
  const projects = useAsync(() => desktop.listProjects(), []);

  const projectName = useMemo(() => {
    const m = new Map<string, string>();
    for (const p of projects.data ?? []) m.set(p.id, p.name);
    return m;
  }, [projects.data]);

  // Deep-link consumer: when a `task` focus is pending, open its detail once the
  // list has loaded. Clear focus only after we actually open the task, so a
  // focus set before data arrives still resolves. If the id is genuinely absent
  // from a fully-loaded list, clear focus too, to avoid a stuck pending state.
  useEffect(() => {
    if (focus?.kind !== 'task' || s.loading || !s.data) return;
    const target = s.data.find((x) => x.id === focus.id);
    if (target) {
      setDetail(target);
      clearFocus();
    } else {
      clearFocus();
    }
  }, [focus, s.data, s.loading, clearFocus]);

  const moveTo = (task: Task, status: string) => {
    if (status === task.status) return;
    const lane = laneOf(status);
    setAnnounce(`${task.title} → ${lane?.nm ?? status}`);
    desktop.setTaskStatus(task.id, status).then(() => s.reload()).catch(() => s.reload());
  };

  return (
    <div className="v-tasks">
      <style>{TASKS_CSS}</style>
      <PageHeader
        title={t('nav.tasks')}
        subtitle={t('tasks.subtitle')}
        actions={<Button variant="primary" onClick={() => setCreating(true)}>{t('action.new')}</Button>}
      />

      <div className="t-sr-only" role="status" aria-live="polite">{announce}</div>

      {creating && (
        <NewTaskForm
          onClose={() => setCreating(false)}
          onCreated={() => { s.reload(); toast(t('toast.created'), 'success'); }}
        />
      )}
      {detail && <TaskDetail task={detail} onClose={() => setDetail(null)} onSaved={() => s.reload()} />}

      <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
        {(tasks) => {
          const blocked = tasks.filter((x) => x.status === 'blocked').length;
          const active = tasks.filter((x) => x.status === 'active').length;
          const doneCount = tasks.filter((x) => x.status === 'done').length;
          const total = tasks.length;
          const pct = total ? Math.round((doneCount / total) * 100) : 0;
          const ledger: { n: number; lab: string; cls: string }[] = [
            { n: total, lab: 'ընդամենը', cls: '' },
            { n: active, lab: 'ընթացքում', cls: 'lg-info' },
            { n: blocked, lab: 'արգելափակ', cls: 'lg-warn' },
            { n: doneCount, lab: 'Ավարտ', cls: 'lg-mint' },
          ];

          return (
            <>
              {/* HERO · honest mission readout — metrics derived from real status counts */}
              <section className="mission surface soft lg hud">
                <span className="bracket tl" aria-hidden="true" />
                <span className="bracket tr" aria-hidden="true" />
                <span className="bracket bl" aria-hidden="true" />
                <span className="bracket br" aria-hidden="true" />
                <div className="m-top">
                  <span className="eyebrow">ԱՌԱՔԵԼՈՒԹՅԱՆ ԿՈՆՏՐՈԼ</span>
                  <MissionClock />
                  <div className="m-top-r">
                    {blocked > 0
                      ? <span className="pill warn">{blocked} ԱՐԳԵԼՔ</span>
                      : <span className="pill live">ՈՒՂԻՆ ՄԱՔՈՒՐ</span>}
                    <span aria-hidden="true"><Mark state={blocked > 0 ? 'alert' : 'idle'} size={30} /></span>
                  </div>
                </div>
                <div className="m-hd">
                  <div className="m-title">
                    <h1>{t('nav.tasks')}</h1>
                    <p className="sub">{t('tasks.subtitle')}</p>
                  </div>
                  <div className="m-prog">
                    <b className="bignum">{pct}<small>%</small></b>
                    <span className="micro">{doneCount}/{total} · Ավարտ</span>
                  </div>
                </div>
                <div className="m-foot">
                  <div className="ledger">
                    {ledger.map((l) => (
                      <div key={l.lab} className={`lg-item ${l.cls}`.trim()}>
                        <b className="count num">{l.n}</b>
                        <span className="micro">{l.lab}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </section>

              {/* BOARD BAR · quiet toolbar + legend */}
              <div className="board-bar">
                <div className="sec-head"><h2>Առաքելության տախտակ</h2>
                  <span className="note">կախվածություններ + արգելքներ</span></div>
                <div className="legend">
                  <span className="chip lg-c"><i className="d-block" aria-hidden="true" />Արգելափակ</span>
                  <span className="chip lg-c"><i className="d-dep" aria-hidden="true" />Կախված</span>
                </div>
              </div>

              {/* BOARD · four ops lanes, grouped by real status */}
              <div className="board">
                {LANES.map((lane) => {
                  const items = tasks.filter((x) => lane.statuses.includes(x.status));
                  return (
                    <section
                      key={lane.id}
                      className={`lane lane-${lane.id}`}
                      aria-label={`${lane.nm} · ${items.length}`}
                    >
                      <header className="lane-hd">
                        <span className={`lane-dot ${lane.tone ? `t-${lane.tone}` : ''}`.trim()} aria-hidden="true" />
                        <h3 className="lane-nm">{lane.nm}</h3>
                        <span className="lane-ct mono">{items.length}</span>
                      </header>
                      <div className="lane-body">
                        {items.map((x) => (
                          <TaskCard
                            key={x.id}
                            task={x}
                            projectName={x.projectId ? projectName.get(x.projectId) : undefined}
                            onOpen={setDetail}
                            onMove={moveTo}
                            t={t}
                          />
                        ))}
                        {items.length === 0 && <p className="lane-empty micro">—</p>}
                      </div>
                    </section>
                  );
                })}
              </div>
            </>
          );
        }}
      </Async>
    </div>
  );
}

// Local styles — scoped under `.v-tasks`; the board/lane/mtask/mission classes
// themselves live in the global aios theme. These only fill the small gaps the
// reskin needs: the sr-only live region, the per-card status control, the
// keyboard focus ring and the empty-lane hint. No shared file is touched.
const TASKS_CSS = `
.v-tasks .t-sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
.v-tasks .mtask { cursor: pointer; }
.v-tasks .mtask:focus-visible { outline: none; border-color: var(--cyan);
  box-shadow: 0 0 0 2px rgb(var(--cyan-rgb)/.4); }
.v-tasks .mt-foot { justify-content: space-between; }
.v-tasks .mt-status { height: 28px; max-width: 60%; padding: 0 8px; font: inherit; font-size: 11px;
  color: var(--ink); background: rgb(var(--raised-rgb)/.5); border: 1px solid rgb(var(--line-rgb)/.7);
  border-radius: 8px; text-transform: capitalize; cursor: pointer; }
.v-tasks .mt-status:focus-visible { outline: none; border-color: var(--cyan);
  box-shadow: 0 0 0 2px rgb(var(--cyan-rgb)/.35); }
.v-tasks .lane-empty { color: var(--ink-muted); padding: 6px 4px; }
`;
