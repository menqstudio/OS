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
import type { Lang, Tone } from '../domain/enums';
import { statusLabel, priorityLabel } from '../domain/statusLabels';
import type { Agent, Task } from '../domain/entities';
import type { DictKey } from '../i18n';
import { STR } from './Tasks.strings';
import {
  CAPABILITY_TIERS, MODES, RISKS, TIER_TOOLS,
  CONTRACT_SCHEMA_SOURCE, DISPATCH_REQUIREMENT,
  attemptDispatch, buildAssignment, previewJson, splitLines, tauriDispatchTransport,
  uuid, validateAssignment,
  type Assignment, type CapabilityTier, type DispatchOutcome, type Mode, type Risk,
} from '../services/agentsDispatch';

type StrKey = keyof typeof STR;
type Lstr = (k: StrKey) => string;

// Mission board — the brops-aios "Առաքելություն" reskin. Lanes group tasks by
// their REAL status (the full status vocabulary maps onto the four mockup lanes
// so no task is ever invisible). Card visuals, the mission hero metrics, the
// risk pill and the "free the blocker" flow are all driven by real data
// (listTasks / listProjects / listTaskDependencies / setTaskStatus). Nothing —
// no crew avatars, no critical-path rail, no fabricated counts — is invented.
const LANES: { id: string; nmKey: StrKey; tone: '' | 'info' | 'warn' | 'mint'; statuses: string[] }[] = [
  { id: 'queue', nmKey: 'lane_queue', tone: '',     statuses: ['inbox', 'planned'] },
  { id: 'prog',  nmKey: 'lane_prog',  tone: 'info', statuses: ['active', 'review'] },
  { id: 'block', nmKey: 'lane_block', tone: 'warn', statuses: ['blocked'] },
  { id: 'done',  nmKey: 'lane_done',  tone: 'mint', statuses: ['done', 'cancelled'] },
];

// Real task status → the mockup's card left-rail state class (purely visual).
const STATE_CLASS: Record<string, string> = {
  active: 'state-working', review: 'state-thinking', blocked: 'state-blocked', done: 'state-completed',
};
// Real priority → the mockup's prio chip class (purely visual). low/normal
// collapse to "mid". The chip TEXT is the localized priorityLabel.
const PRIO_CLS: Record<string, string> = {
  critical: 'crit', high: 'high', normal: 'mid', low: 'mid',
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
  const { t, lang } = useApp();
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
        <Badge tone={statusTone[task.status] ?? 'neutral'}>{statusLabel(task.status, lang)}</Badge>
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

// ── Governed dispatch (Phase 6) ─────────────────────────────────────────────
// The board's missing half: turning a task into an ACTUAL contract-shaped assignment
// — agent identity, role, capability tier, scope, prohibited_scope, risk, verifier —
// and attempting to hand it to the engine.
//
// The three honesty rules this composer obeys:
//   1. Nothing here is filled in on the user's behalf that the desktop cannot know.
//      `pack_id` and `core_skills` stay empty and the pre-flight refuses until they are
//      stated, because the desktop has no IPC that can read engine/packs/registry.json
//      or engine/skills — and a guessed pack id in a signed contract is worse than a
//      blocked form.
//   2. The default grant is the NARROWEST one: `reader` tier, `review` mode, `low` risk.
//      Widening is a deliberate act by whoever composes the dispatch.
//   3. The outcome shown is the real outcome. `accepted` is rendered only for an
//      engine-accepted frame carrying a lease, a sha256 contract digest and the sealed
//      repository binding; every other result renders as refused, invalid, or — the
//      state this build is actually in — not dispatched at all.

const OUTCOME_TONE: Record<DispatchOutcome['state'], Tone> = {
  accepted: 'success',
  refused: 'danger',
  unreachable: 'warning',
  invalid: 'warning',
};

function DispatchModal({
  task, agents, onClose, L,
}: {
  task: Task;
  agents: Agent[];
  onClose: () => void;
  L: Lstr;
}) {
  const { t } = useApp();

  const [agentSlug, setAgentSlug] = useState(() => {
    const assigned = agents.find((a) => a.id === task.assignedAgentId);
    return (assigned ?? agents[0])?.slug ?? '';
  });
  // Narrowest grant by default — see rule 2 above.
  const [tier, setTier] = useState<CapabilityTier>('reader');
  const [mode, setMode] = useState<Mode>('review');
  const [risk, setRisk] = useState<Risk>('low');
  const [packId, setPackId] = useState('');
  const [objective, setObjective] = useState(task.description.trim() || task.title);
  const [scopeText, setScopeText] = useState('');
  const [prohibitedText, setProhibitedText] = useState('');
  const [skillsText, setSkillsText] = useState('');
  const [doneText, setDoneText] = useState('');
  const [verifierSlug, setVerifierSlug] = useState('');
  const [verifyCmdsText, setVerifyCmdsText] = useState('');
  const [rollback, setRollback] = useState('');
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<DispatchOutcome | null>(null);

  const selected = agents.find((a) => a.slug === agentSlug) ?? null;
  const verifierCandidates = agents.filter((a) => a.slug !== agentSlug);
  const verifier = agents.find((a) => a.slug === verifierSlug) ?? null;

  const assignment: Assignment = useMemo(() => buildAssignment({
    taskId: task.id,
    title: task.title,
    objective,
    mode,
    risk,
    packId,
    agentSlug,
    assigneeRole: selected?.role ?? '',
    tier,
    scope: splitLines(scopeText),
    prohibitedScope: splitLines(prohibitedText),
    coreSkills: splitLines(skillsText),
    doneCriteria: splitLines(doneText),
    verifierAgentSlug: verifierSlug || null,
    verifierRole: verifier?.role ?? null,
    verificationCommands: splitLines(verifyCmdsText),
    rollbackStrategy: rollback,
  }), [
    task.id, task.title, objective, mode, risk, packId, agentSlug, selected?.role, tier,
    scopeText, prohibitedText, skillsText, doneText, verifierSlug, verifier?.role,
    verifyCmdsText, rollback,
  ]);

  const problems = useMemo(() => validateAssignment(assignment), [assignment]);

  const send = () => {
    if (busy) return;
    setBusy(true);
    setOutcome(null);
    attemptDispatch(assignment, tauriDispatchTransport(), uuid)
      .then((o) => { setOutcome(o); setBusy(false); })
      // attemptDispatch already maps a thrown transport to `unreachable`; this only
      // catches a fault in the composer itself, and it must still not read as success.
      .catch((e: unknown) => {
        setOutcome({ state: 'unreachable', reason: e instanceof Error ? e.message : String(e) });
        setBusy(false);
      });
  };

  return (
    <Modal title={`${L('dispatchTitle')} · ${task.title}`} onClose={onClose}>
      <p className="muted dsp-note">{L('dispatchIntro')}</p>
      <div className="dsp-warn" role="note">{L('draftWarning')}</div>

      {agents.length === 0 && <div className="form-error">{L('noAgents')}</div>}

      <FormRow label={L('fAgent')}>
        <Select value={agentSlug} onChange={(e) => setAgentSlug(e.target.value)}>
          {agents.map((a) => (
            <option key={a.id} value={a.slug}>{a.displayName} · {a.role}</option>
          ))}
        </Select>
      </FormRow>
      <FormRow label={L('fTier')}>
        <Select value={tier} onChange={(e) => setTier(e.target.value as CapabilityTier)}>
          {CAPABILITY_TIERS.map((x) => <option key={x} value={x}>{x}</option>)}
        </Select>
      </FormRow>

      {/* The capability half, split by what is actually enforced. The TIER is spawned and
          its tool list is what the CLI receives — that is the real bound. The pack-role
          definition is only READ, for the specialism and its authority record, so it is
          labelled advisory rather than shown beside the tier as if it contained anything. */}
      <div className="dsp-grant">
        <span className="micro">{L('grantTitle')}</span>

        <div className="dsp-half">
          <span className="dsp-tag dsp-tag--on">{L('enforcedWord')}</span>
          <div className="dsp-mono">{assignment.grant.tierDefinitionPath}</div>
          <div className="dsp-tools">
            <span className="micro">{L('toolsWord')}</span>
            {TIER_TOOLS[tier].map((tool) => <span key={tool} className="chip">{tool}</span>)}
          </div>
          <p className="muted dsp-half-note">{L('enforcedNote')}</p>
        </div>

        <div className="dsp-half">
          <span className="dsp-tag">{L('advisoryWord')}</span>
          {assignment.grant.packRolePath ? (
            <div className="dsp-mono">{assignment.grant.packRolePath}</div>
          ) : (
            <p className="muted dsp-half-note">{L('packRoleUnset')}</p>
          )}
          <p className="muted dsp-half-note">{L('packRoleNote')}</p>
        </div>
      </div>

      <FormRow label={L('fMode')}>
        <Select value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
          {MODES.map((x) => <option key={x} value={x}>{x}</option>)}
        </Select>
      </FormRow>
      <FormRow label={L('fRisk')}>
        <Select value={risk} onChange={(e) => setRisk(e.target.value as Risk)}>
          {RISKS.map((x) => <option key={x} value={x}>{x}</option>)}
        </Select>
      </FormRow>
      <FormRow label={L('fPack')}>
        <Input value={packId} placeholder="architecture-audit" onChange={(e) => setPackId(e.target.value)} />
      </FormRow>
      <FormRow label={L('fObjective')}>
        <Textarea value={objective} onChange={(e) => setObjective(e.target.value)} />
      </FormRow>
      <FormRow label={L('fScope')}>
        <Textarea value={scopeText} placeholder={'apps/desktop/src/features'} onChange={(e) => setScopeText(e.target.value)} />
      </FormRow>
      <FormRow label={L('fProhibited')}>
        <Textarea value={prohibitedText} placeholder={'engine'} onChange={(e) => setProhibitedText(e.target.value)} />
      </FormRow>
      <FormRow label={L('fSkills')}>
        <Textarea value={skillsText} placeholder={'analysis-primary'} onChange={(e) => setSkillsText(e.target.value)} />
      </FormRow>
      <FormRow label={L('fDone')}>
        <Textarea value={doneText} onChange={(e) => setDoneText(e.target.value)} />
      </FormRow>
      <FormRow label={L('fVerifier')}>
        <Select value={verifierSlug} onChange={(e) => setVerifierSlug(e.target.value)}>
          <option value="">{L('noVerifier')}</option>
          {verifierCandidates.map((a) => (
            <option key={a.id} value={a.slug}>{a.displayName} · {a.role}</option>
          ))}
        </Select>
      </FormRow>
      <FormRow label={L('fVerifyCmds')}>
        <Textarea value={verifyCmdsText} onChange={(e) => setVerifyCmdsText(e.target.value)} />
      </FormRow>
      <FormRow label={L('fRollback')}>
        <Input value={rollback} onChange={(e) => setRollback(e.target.value)} />
      </FormRow>

      {/* Pre-flight. Refusals only — clearing them is not acceptance. */}
      {problems.length > 0 ? (
        <div className="dsp-problems" role="alert">
          <span className="micro">{L('problemsTitle')} · {CONTRACT_SCHEMA_SOURCE}</span>
          <ul>
            {problems.map((p, i) => (
              <li key={`${p.field}-${i}`}><b className="dsp-mono">{p.field}</b> — {p.message}</li>
            ))}
          </ul>
          <p className="muted">{L('problemsNote')}</p>
        </div>
      ) : (
        <div className="dsp-ok" role="status">{L('wellFormed')}</div>
      )}

      <details className="dsp-preview">
        <summary>{L('previewTitle')}</summary>
        <pre className="dsp-json">{previewJson(assignment)}</pre>
      </details>

      {/* The true state of the attempt. */}
      {outcome && (
        <div className={`dsp-outcome dsp-outcome--${outcome.state}`} role="status">
          <Badge tone={OUTCOME_TONE[outcome.state]}>
            {outcome.state === 'accepted' ? L('outAccepted')
              : outcome.state === 'refused' ? L('outRefused')
                : outcome.state === 'invalid' ? L('outInvalid')
                  : L('outUnreachable')}
          </Badge>
          {outcome.state === 'accepted' && (
            <dl className="dsp-facts">
              <dt>{L('assignmentId')}</dt><dd className="dsp-mono">{outcome.assignmentId}</dd>
              <dt>{L('leaseId')}</dt><dd className="dsp-mono">{outcome.leaseId}</dd>
              <dt>{L('contractDigest')}</dt><dd className="dsp-mono">{outcome.contractDigest}</dd>
              <dt>base_commit</dt><dd className="dsp-mono">{outcome.repository.base_commit}</dd>
              <dt>tree_identity</dt><dd className="dsp-mono">{outcome.repository.tree_identity}</dd>
            </dl>
          )}
          {outcome.state === 'refused' && (
            <p className="dsp-mono">{outcome.reason}{outcome.detail ? ` — ${outcome.detail}` : ''}</p>
          )}
          {outcome.state === 'unreachable' && (
            <>
              <p>{L('unreachableNote')}</p>
              <p className="muted dsp-mono">{DISPATCH_REQUIREMENT}</p>
              <p className="muted dsp-mono">{outcome.reason}</p>
            </>
          )}
          {outcome.state === 'invalid' && (
            <p className="muted">{outcome.problems.map((x) => `${x.field}: ${x.message}`).join(' · ')}</p>
          )}
        </div>
      )}

      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>{t('action.cancel')}</Button>
        <Button
          variant="primary"
          onClick={send}
          disabled={busy || problems.length > 0 || agents.length === 0}
        >
          {busy ? L('sending') : L('dispatch')}
        </Button>
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
  task, projectName, onOpen, onMove, onDispatch, t, lang, L,
}: {
  task: Task;
  projectName?: string;
  onOpen: (task: Task) => void;
  onMove: (task: Task, status: string) => void;
  onDispatch: (task: Task) => void;
  t: (k: DictKey) => string;
  lang: Lang;
  L: Lstr;
}) {
  const isBlocked = task.status === 'blocked';
  const deps = useAsync(
    () => (isBlocked ? desktop.listTaskDependencies(task.id) : Promise.resolve([] as Task[])),
    [task.id, isBlocked],
  );
  const stateCls = STATE_CLASS[task.status] ?? '';
  const prioCls = PRIO_CLS[task.priority] ?? 'mid';
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
        <span className={`prio prio-${prioCls}`}>{priorityLabel(task.priority, lang)}</span>
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
              <b>{L('blocking')}</b>
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
              {L('release')}
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
            <option key={sv} value={sv}>{statusLabel(sv, lang)}</option>
          ))}
        </select>
        {/* Opens the dispatch composer. The card shows no dispatch STATE badge, because
            no dispatch state is persisted anywhere — a badge here would be decoration. */}
        <button
          className="chip mt-dispatch"
          type="button"
          aria-label={`${L('dispatch')}: ${task.title}`}
          onClick={(e) => { e.stopPropagation(); onDispatch(task); }}
        >
          {L('dispatch')}
        </button>
        {task.assignedAgentId && <span className="mt-own micro">{task.assignedAgentId}</span>}
      </div>
    </article>
  );
}

export function Tasks() {
  const { t, lang, focus, clearFocus } = useApp();
  const L: Lstr = (k) => STR[k][lang] ?? STR[k].en;
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [detail, setDetail] = useState<Task | null>(null);
  const [dispatching, setDispatching] = useState<Task | null>(null);
  const [announce, setAnnounce] = useState('');
  const s = useAsync(() => desktop.listTasks(), []);
  const projects = useAsync(() => desktop.listProjects(), []);
  // The real roster — a dispatch names a real agent identity or it names nobody.
  const agents = useAsync(() => desktop.listAgents(), []);

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
    setAnnounce(`${task.title} → ${lane ? L(lane.nmKey) : status}`);
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
      {dispatching && (
        <DispatchModal
          task={dispatching}
          agents={agents.data ?? []}
          onClose={() => setDispatching(null)}
          L={L}
        />
      )}

      <Async state={s} emptyTitle={t('state.empty')} emptyHint={t('state.emptyHint')}>
        {(tasks) => {
          const blocked = tasks.filter((x) => x.status === 'blocked').length;
          const active = tasks.filter((x) => x.status === 'active').length;
          const doneCount = tasks.filter((x) => x.status === 'done').length;
          const total = tasks.length;
          const pct = total ? Math.round((doneCount / total) * 100) : 0;
          const ledger: { id: string; n: number; lab: string; cls: string }[] = [
            { id: 'total', n: total, lab: L('kpi_total'), cls: '' },
            { id: 'active', n: active, lab: L('kpi_active'), cls: 'lg-info' },
            { id: 'blocked', n: blocked, lab: L('kpi_blocked'), cls: 'lg-warn' },
            { id: 'done', n: doneCount, lab: L('kpi_done'), cls: 'lg-mint' },
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
                  <span className="eyebrow">{L('eyebrow')}</span>
                  <MissionClock />
                  <div className="m-top-r">
                    {blocked > 0
                      ? <span className="pill warn">{blocked} {L('blockersWord')}</span>
                      : <span className="pill live">{L('pathClear')}</span>}
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
                    <span className="micro">{doneCount}/{total} · {L('doneCap')}</span>
                  </div>
                </div>
                <div className="m-foot">
                  <div className="ledger">
                    {ledger.map((l) => (
                      <div key={l.id} className={`lg-item ${l.cls}`.trim()}>
                        <b className="count num">{l.n}</b>
                        <span className="micro">{l.lab}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </section>

              {/* BOARD BAR · quiet toolbar + legend */}
              <div className="board-bar">
                <div className="sec-head"><h2>{L('boardTitle')}</h2>
                  <span className="note">{L('boardNote')}</span></div>
                <div className="legend">
                  <span className="chip lg-c"><i className="d-block" aria-hidden="true" />{L('legendBlocked')}</span>
                  <span className="chip lg-c"><i className="d-dep" aria-hidden="true" />{L('legendDep')}</span>
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
                      aria-label={`${L(lane.nmKey)} · ${items.length}`}
                    >
                      <header className="lane-hd">
                        <span className={`lane-dot ${lane.tone ? `t-${lane.tone}` : ''}`.trim()} aria-hidden="true" />
                        <h3 className="lane-nm">{L(lane.nmKey)}</h3>
                        <span className="lane-ct mono">{items.length}</span>
                      </header>
                      {/* §D: "board columns `role=list`, cards labeled". A lane is a LIST of
                          cards and was a bare <div>, so a screen reader announced the section
                          and then read the cards as loose content — no count, no position, no
                          "3 of 7". The lane header's number is on screen and was nowhere in the
                          accessibility tree except as the section's own label. */}
                      <div className="lane-body" role="list" aria-label={L(lane.nmKey)}>
                        {items.map((x) => (
                          <div role="listitem" key={x.id}>
                            <TaskCard
                              task={x}
                              projectName={x.projectId ? projectName.get(x.projectId) : undefined}
                              onOpen={setDetail}
                              onMove={moveTo}
                              onDispatch={setDispatching}
                              t={t}
                              lang={lang}
                              L={L}
                            />
                          </div>
                        ))}
                        {/* An em dash is not an empty state to a screen reader — it is a
                            character. The lane says it is empty, in words. */}
                        {items.length === 0 && (
                          <p className="lane-empty micro" role="listitem">
                            <span aria-hidden="true">—</span>
                            <span className="sr-only">{t('state.empty')}</span>
                          </p>
                        )}
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
.v-tasks .mt-dispatch { cursor: pointer; }
.v-tasks .mt-dispatch:focus-visible { outline: 2px solid var(--cyan-soft); outline-offset: 2px; }

/* Dispatch composer. The warning band and the outcome block are deliberately louder
   than the form: what state the dispatch is really in matters more than the inputs. */
.dsp-note { font-size: 12.5px; line-height: 1.55; margin: 0 0 10px; }
.dsp-warn { padding: 10px 12px; margin-bottom: 14px; border-radius: 10px; font-size: 12px;
  line-height: 1.55; color: var(--ink); border: 1px solid rgb(var(--warn-rgb,var(--line-rgb))/.45);
  background: rgb(var(--warn-rgb,var(--line-rgb))/.1); }
.dsp-mono { font-family: var(--f-mono); font-size: 11px; word-break: break-all; }
.dsp-grant { display: grid; gap: 6px; padding: 10px 12px; margin-bottom: 14px; border-radius: 10px;
  border: 1px solid rgb(var(--line-rgb)/.8); background: rgb(var(--raised-rgb)/.45); }
.dsp-tools { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
/* The enforced half reads first and looks live; the advisory half is visibly quieter so
   nobody mistakes the pack-role reference for the thing that contains the specialist. */
.dsp-half { display: grid; gap: 5px; padding-top: 8px; }
.dsp-half + .dsp-half { border-top: 1px dashed rgb(var(--line-rgb)/.8); }
.dsp-half-note { margin: 0; font-size: 11px; line-height: 1.5; }
.dsp-tag { justify-self: start; font-family: var(--f-mono); font-size: 8.5px; font-weight: 700;
  letter-spacing: .1em; text-transform: uppercase; padding: 2px 7px; border-radius: var(--r-pill);
  color: var(--ink-muted); border: 1px solid rgb(var(--line-rgb)/.9); }
.dsp-tag--on { color: var(--cyan); border-color: rgb(var(--cyan-rgb)/.45);
  background: rgb(var(--cyan-rgb)/.1); }
.dsp-problems { padding: 10px 12px; margin: 14px 0; border-radius: 10px;
  border: 1px solid rgb(var(--danger-rgb)/.4); background: rgb(var(--danger-rgb)/.08); }
.dsp-problems ul { margin: 8px 0; padding-left: 18px; display: grid; gap: 6px; }
.dsp-problems li { font-size: 12px; line-height: 1.5; }
.dsp-problems p { margin: 0; font-size: 11.5px; line-height: 1.5; }
.dsp-ok { padding: 8px 12px; margin: 14px 0; border-radius: 10px; font-size: 12px;
  border: 1px solid rgb(var(--line-rgb)/.8); color: var(--ink-muted); }
.dsp-preview { margin-bottom: 12px; }
.dsp-preview summary { cursor: pointer; font-size: 12px; color: var(--ink-muted); }
.dsp-json { max-height: 280px; overflow: auto; font-family: var(--f-mono); font-size: 10.5px;
  line-height: 1.5; padding: 10px; margin-top: 8px; border-radius: 8px;
  background: rgb(var(--raised-rgb)/.55); border: 1px solid rgb(var(--line-rgb)/.7); }
.dsp-outcome { display: grid; gap: 8px; padding: 12px; margin-bottom: 12px; border-radius: 10px;
  border: 1px solid rgb(var(--line-rgb)/.8); background: rgb(var(--raised-rgb)/.4); }
.dsp-outcome p { margin: 0; font-size: 12px; line-height: 1.55; }
.dsp-facts { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin: 0; font-size: 11px; }
.dsp-facts dt { font-family: var(--f-mono); font-size: 9px; letter-spacing: .08em;
  text-transform: uppercase; color: var(--ink-muted); }
.dsp-facts dd { margin: 0; }
`;
