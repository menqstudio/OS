- **Purpose:** Define the canonical detailed UX flows for the Intelligence, Operations, and System workspaces that lack a dedicated flow document, completing Roadmap Phase 1 ("every MVP capability has a defined user flow").
- **Scope:** Knowledge, Memory, Decisions, Research, Library, Calendar, Automations, Activity, Notifications, Files, Integrations, Analytics, Security, Settings. For each: entry point, primary action, key sub-flows, and the canonical states it must show. Trilingual product surface (HY/EN/RU).
- **Owner:** Gev.
- **Related:** [WORKSPACES.md](WORKSPACES.md), [USER_FLOWS.md](USER_FLOWS.md), [STATES.md](STATES.md), [CHAT_FLOWS.md](CHAT_FLOWS.md), [PROJECT_TASK_FLOWS.md](PROJECT_TASK_FLOWS.md), [DECISION_APPROVAL_FLOWS.md](DECISION_APPROVAL_FLOWS.md), [AGENT_FLOWS.md](AGENT_FLOWS.md), [NAVIGATION.md](NAVIGATION.md), [SCREEN_INVENTORY.md](SCREEN_INVENTORY.md), [../AI_RUNTIME.md](../AI_RUNTIME.md).
- **Last updated:** 2026-07-19.

# BroPS Workspace Flows

Status: Draft canonical

This document specifies what the user actually sees and does inside each remaining workspace. It is concrete and step-by-step, and it defers to the single sources of truth: workspace responsibilities come from [WORKSPACES.md](WORKSPACES.md); every state named here (`loading`, `empty` with its first-run / no-results / filtered sub-patterns, `populated`, `error`, `offline`, `permission-denied`, `blocked`, `awaiting-approval`, `destructive-confirmation`, `success`) is the canonical pattern defined in [STATES.md](STATES.md) and MUST NOT be restated or redefined here — only referenced. Agent statuses, engines, approval levels (`A0–A3`), and the delegation contract are those in [../AI_RUNTIME.md](../AI_RUNTIME.md). Mandatory approval gates and the permission model follow [../docs/architecture/NOTIFICATIONS_AND_PERMISSIONS.md](../docs/architecture/NOTIFICATIONS_AND_PERMISSIONS.md).

Flows that already have dedicated documents are out of scope here: Chat and Group Chat ([CHAT_FLOWS.md](CHAT_FLOWS.md)), Projects and Tasks ([PROJECT_TASK_FLOWS.md](PROJECT_TASK_FLOWS.md)), Decisions-as-approval and Approvals ([DECISION_APPROVAL_FLOWS.md](DECISION_APPROVAL_FLOWS.md)), and Agents ([AGENT_FLOWS.md](AGENT_FLOWS.md)). The Decisions workspace surface itself is covered below for completeness and defers its approval mechanics to that document.

Global rule (from [USER_FLOWS.md](USER_FLOWS.md)): no flow may hide execution state, approval state, ownership, failure, or uncertainty.

---

## A. Intelligence

### A.1 Knowledge / Գիտելիք

- **Entry point:** Sidebar → Intelligence → **Knowledge**; also reached from a citation in any Bro answer, from a project's Knowledge tab, or from "Save to knowledge" on a chat message.
- **Primary action:** Find and cite a verified, attributable knowledge item — and add or promote one.
- **Key sub-flows:**
  1. **Browse / search.** Left facets (scope, owner, freshness, verification state, sensitivity). Center list shows each item's source, owner, version, freshness, and a canonical-vs-draft badge; canonical and draft remain visually distinct.
  2. **Open an item.** Right pane shows provenance (source identifier, created/updated), linked decisions, retrieval metadata, and supersession state. Every item traces to a source; nothing is source-less.
  3. **Add / promote.** Import a document, save a verified output, or promote a draft to canonical. Promotion records owner and verification state and never auto-overrides existing approved content — conflicts are surfaced, not merged.
  4. **Supersede / revoke.** Superseding an item references the prior version; revoked or deleted sources stop being retrieved and stop appearing in citations.
- **States:** `loading` (skeleton list, owner kept visible), `empty` (first-run invite to import; no-results vs. filtered-empty distinguished), `populated` (verification badge inline), `error` (retry a failed index/load), `offline` (cached items labeled stale, writes disabled), `permission-denied` (scoped/sensitive items visible-but-disabled with reason), `blocked` (unverified or conflicting source flagged, not shown as trusted), `destructive-confirmation` (revoke/delete names consequence), `success` (import/promote confirmed and reflected in the list). See [STATES.md](STATES.md).

### A.2 Memory / Հիշողություն

- **Entry point:** Sidebar → Intelligence → **Memory**; also from a "why did Bro know this?" affordance on any answer that used memory.
- **Primary action:** Inspect, correct, or remove any persistent memory. No hidden memory is permitted.
- **Key sub-flows:**
  1. **Browse by class.** Grouped by the memory classes (working, conversation, project, user preference, failure, canonical). Each record shows source, scope, timestamp, confidence, and owner.
  2. **Inspect usage.** Open a record to see where it came from and where it has been used (the system must expose both). Sensitive memory is marked and minimized.
  3. **Correct / supersede / expire / delete.** Any record can be corrected, superseded, expired, or deleted; corrections keep provenance.
  4. **Review write candidates.** A queue of proposed memories (`candidate → classify → deduplicate → verify source → approve policy → persist`) lets Gev accept or reject before anything persists.
- **States:** `loading`, `empty` (no memory yet in this class), `populated` (confidence + scope inline), `error`, `offline` (cached, writes disabled), `permission-denied` (sensitive memory gated), `awaiting-approval` (a write candidate needs owner approval before persisting), `destructive-confirmation` (delete/purge names the exact record), `success` (correction/deletion reflected). See [STATES.md](STATES.md).

### A.3 Decisions / Որոշումներ

- **Entry point:** Sidebar → Intelligence → **Decisions**; also from "Create decision" in chat/rooms and from a project's Decisions tab.
- **Primary action:** Record and track an explicit, attributable decision through its lifecycle. Approval mechanics defer to [DECISION_APPROVAL_FLOWS.md](DECISION_APPROVAL_FLOWS.md).
- **Key sub-flows:**
  1. **Browse / filter** by state (`proposed → under review → approved | rejected | deferred → superseded`), owner, scope, effective date.
  2. **Open a decision.** Shows context, options considered, chosen option, rationale, owner, approver, consequences, and rollback/replacement path.
  3. **Propose / move state.** Create a decision (state `proposed`); route to review; an approver approves/rejects/defers. Silence is never approval; chat agreement is not canonical until recorded; agents may recommend but must not impersonate the approver.
  4. **Supersede.** A superseding decision must reference the prior one; the chain stays visible.
- **States:** `loading`, `empty` (first-run invite to record the first decision), `populated` (state + owner + approver inline), `error`, `offline` (read cached, no state changes), `permission-denied` (approve gated to the approver), `blocked` (waiting on an upstream dependency or unverified context), `awaiting-approval` (high-impact decision paused for explicit owner approval), `destructive-confirmation` (reject/supersede names the effect), `success` (approved decision updates linked tasks/knowledge/policy). See [STATES.md](STATES.md).

### A.4 Research / Հետազոտություն

- **Entry point:** Sidebar → Intelligence → **Research**; also from "Investigate" on a command, a room, or a project risk.
- **Primary action:** Run an evidence-first investigation that ends in cited findings with explicit confidence and unresolved gaps.
- **Key sub-flows:**
  1. **Open / define an investigation.** State the question(s), scope, and sources to consider.
  2. **Gather evidence.** Bro or a research agent (for example a Probe-class specialist) fans out sources; the live run follows the agent execution model (`assigned → accepted → running → blocked | completed | failed | cancelled`) with the current step and agent name always visible.
  3. **Review findings.** Findings show sources, contradictions surfaced (not merged), confidence, and remaining gaps. Uncertainty is shown as uncertainty.
  4. **Promote.** A verified finding can become knowledge (into A.1) or decision evidence (into A.3) with provenance carried across.
- **States:** `loading` (determinate progress + live step label for a running investigation, never a bare spinner), `empty` (first-run: start an investigation), `populated` (findings with confidence + citations), `error` (a source or run step failed; retry), `offline` (cached findings marked stale; new runs disabled), `permission-denied` (restricted source or investigation), `blocked` (waiting on a source, a dependency, or an unverifiable claim — shown honestly, never as false success), `awaiting-approval` (a high-cost or external-fetch run pauses for approval), `success` (investigation verified and closed). See [STATES.md](STATES.md).

### A.5 Library / Գրադարան

- **Entry point:** Sidebar → Intelligence → **Library**; also from "Use template" when creating a project, task, room, or automation.
- **Primary action:** Find and apply a curated, reusable asset (template, prompt, spec, procedure, approved output).
- **Key sub-flows:**
  1. **Browse / search** by type, owner, and tags; each asset shows owner, version, and last-updated.
  2. **Preview.** Read the asset and see where it is used before applying it.
  3. **Apply.** Instantiate a template or insert a prompt/procedure into the target surface; the origin asset is linked back for provenance.
  4. **Add / version.** Save a new asset or publish a new version; superseded versions stay retrievable and referenced.
- **States:** `loading`, `empty` (first-run invite to add the first asset; no-results vs. filtered distinguished), `populated` (version + owner inline), `error`, `offline` (browse cached, apply/publish disabled), `permission-denied` (private/team assets gated), `destructive-confirmation` (delete/unpublish names the effect and dependents), `success` (asset applied or version published, reflected in the list). See [STATES.md](STATES.md).

---

## B. Operations

### B.1 Calendar / Օրացույց

- **Entry point:** Sidebar → Operations → **Calendar**; also from a task deadline, an automation schedule, or Home's calendar-pressure panel.
- **Primary action:** See and manage time commitments — deadlines, focus windows, agent schedules, and automation triggers — in one timeline.
- **Key sub-flows:**
  1. **Switch view** (day / week / month / agenda); filter by source (tasks, events, agent runs, automation triggers).
  2. **Open an entry.** Deadlines and agent/automation entries deep-link back to their owning task, agent run, or automation; ownership is named.
  3. **Create / reschedule.** Add a focus window or event; drag to reschedule. Rescheduling an item tied to a task or automation shows the downstream effect before saving.
  4. **Resolve pressure.** Overdue or colliding commitments are flagged with a path to the blocker or owner.
- **States:** `loading` (skeleton grid), `empty` (first-run: nothing scheduled), `populated` (each entry shows source + owner + live run status where applicable), `error`, `offline` (cached calendar marked stale; edits disabled), `permission-denied` (others' or restricted schedules gated), `blocked` (a deadline waiting on an upstream item is flagged, not silently passed), `destructive-confirmation` (delete/cancel an event names it), `success` (create/reschedule confirmed and reflected). See [STATES.md](STATES.md).

### B.2 Automations / Ավտոմատացումներ

- **Entry point:** Sidebar → Operations → **Automations**; also from "Automate this" on a repeated command or task.
- **Primary action:** Create, inspect, and safely control condition- or schedule-based workflows, each with a visible owner, trigger, action, permissions, approval policy, run history, and a disable switch.
- **Key sub-flows:**
  1. **Browse.** Each automation shows owner, trigger, action, enabled/disabled state, approval policy, and last-run result.
  2. **Create / configure.** Define trigger (schedule or condition), action, target scope, permission scope, and approval policy. Enabling an automation with external side effects is a mandatory approval gate.
  3. **Run / dry-run.** Preview effect; view run history (`triggered → skipped | completed | failed`) with evidence per run.
  4. **Disable / delete.** The disable switch is always one action away; deletion confirms consequences.
- **States:** `loading`, `empty` (first-run: create the first automation), `populated` (enabled state + last-run result inline), `error` (a run failed; retry/inspect log), `offline` (history cached; enable/run disabled), `permission-denied` (managing others' automations gated), `blocked` (an automation waiting on an unmet condition or dependency), `awaiting-approval` (enabling external-side-effect automations, or a high-risk run, pauses for approval), `destructive-confirmation` (disable/delete an active automation names the effect), `success` (enabled/created/run-complete confirmed). See [STATES.md](STATES.md).

### B.3 Activity / Գործունեություն

- **Entry point:** Sidebar → Operations → **Activity**; also from any object's "View activity" and from an execution-log link.
- **Primary action:** Read and filter the chronological, append-only record of user, agent, tool, system, and automation events.
- **Key sub-flows:**
  1. **Filter / search** by actor type, source, scope, event family, risk level, and time range.
  2. **Open an event.** Shows the event shape (actor, source, correlation/causation, scope, result, risk, approval id where applicable). Failed and denied actions appear here too.
  3. **Trace correlation.** Follow a `correlation_id` to see the full chain of related work across surfaces.
  4. **Export.** Export a filtered slice (permission-gated; export is an auditable action).
- **States:** `loading` (skeleton stream), `empty` (no events in scope yet), `populated` (each row names actor + result; append-only, never silently rewritten), `error`, `offline` (cached stream marked stale; live tail paused with a clear indicator), `permission-denied` (restricted-scope events gated), `success` (export completed with a link). Activity is read-only, so it has no destructive-confirmation of its own. See [STATES.md](STATES.md).

### B.4 Notifications / Ծանուցումներ

- **Entry point:** Shell notification bell / badge → **Notifications** (full workspace); also the notification center surface.
- **Primary action:** Triage actionable alerts to resolution. Every notification carries severity, source, object, reason, and a resolution path.
- **Key sub-flows:**
  1. **Triage inbox.** Filter by type (approval required, run completed, run failed, task due, mention, assignment, automation result, security warning, backup status) and severity; deduplicated by key.
  2. **Act.** Each item deep-links to its action target — approve, open the failed run, open the due task, jump to the mention. Approval-required items route into the approval flow.
  3. **Manage state.** Mark read, snooze, or dismiss; created/read timestamps are preserved.
  4. **Configure delivery.** Per-type channel (in-app, desktop, badge, optional email), quiet hours, and digest behavior.
- **States:** `loading`, `empty` (inbox zero — a positive state, not an error), `populated` (severity + source + resolution path inline), `error` (delivery/fetch failed; retry), `offline` (cached list marked stale; new deliveries queued/paused visibly), `permission-denied` (notifications for restricted objects gated), `awaiting-approval` (an approval-required notification reflects the pending gate), `destructive-confirmation` (bulk-dismiss/clear names the effect), `success` (item resolved and reflected). See [STATES.md](STATES.md).

---

## C. System

### C.1 Files / Ֆայլեր

- **Entry point:** Sidebar → System → **Files**; also from a project's Files tab, a chat attachment, and File preview.
- **Primary action:** Manage files with preview, provenance, versioning, links, permissions, and project associations.
- **Key sub-flows:**
  1. **Browse / search.** List or grid with owner, project association, version, and source; preview inline.
  2. **Open / preview.** File preview shows provenance (where it came from), version history, and linked objects (tasks, decisions, knowledge).
  3. **Upload / new version.** Add a file or publish a new version; associations and permissions are set at save.
  4. **Delete / overwrite.** File deletion or overwrite is a mandatory approval gate and always confirms consequences.
- **States:** `loading` (skeleton grid), `empty` (first-run: upload the first file; no-results vs. filtered distinguished), `populated` (owner + version + project inline), `error` (upload/preview failed; retry), `offline` (cached files marked stale; upload/delete disabled), `permission-denied` (restricted files visible-but-disabled with reason), `awaiting-approval` (delete/overwrite paused at the gate), `destructive-confirmation` (delete/overwrite names the exact file and irreversibility, with a match step for high-impact deletes), `success` (upload/version confirmed and reflected). See [STATES.md](STATES.md).

### C.2 Integrations / Ինտեգրացիաներ

- **Entry point:** Sidebar → System → **Integrations**; also from Settings → Integrations and from a flow that needs a not-yet-connected service.
- **Primary action:** Connect, inspect, and revoke external services with clear credential status, granted scopes, health, and sync state.
- **Key sub-flows:**
  1. **Browse connections.** Each shows connection status, granted scopes, health, and last sync.
  2. **Connect.** Run the provider authorization flow; on return, granted scopes are shown explicitly. In a non-interactive/offline context, the flow reports that authorization must be completed elsewhere rather than pretending success.
  3. **Manage scopes / re-auth.** Adjust granted scopes or refresh expired credentials; changing provider keys is a mandatory approval gate.
  4. **Revoke / disconnect.** Revocation confirms consequences (which automations, agents, or projects lose access) and stops further sync.
- **States:** `loading`, `empty` (first-run: no integrations connected), `populated` (status + scopes + health inline), `error` (auth/sync failed with a plain-language cause; retry), `offline` (status cached and marked stale; connect/revoke disabled), `permission-denied` (managing integrations gated to Owner/Admin, disabled with reason), `blocked` (a connection stuck awaiting external authorization, shown honestly — never as connected), `awaiting-approval` (provider-key/secret changes pause at the gate), `destructive-confirmation` (revoke/disconnect names dependents), `success` (connected/scopes-updated confirmed). See [STATES.md](STATES.md).

### C.3 Analytics / Վերլուծություն

- **Entry point:** Sidebar → System → **Analytics**; also from Home's system-health panel.
- **Primary action:** Read operational insight — outcomes, throughput, blockers, agent quality, costs, approvals, automation reliability, and system health.
- **Key sub-flows:**
  1. **Select scope / range.** Choose workspace/project scope, time range, and metric group.
  2. **Read dashboards.** Charts and KPI tiles follow the Design System (count-up on populate; reduced-motion shows final values instantly). Every metric names its source and freshness.
  3. **Drill down.** Click a metric to the underlying items (for example a cost spike → the runs that caused it) in Activity or the relevant workspace.
  4. **Export.** Export a filtered report (permission-gated, auditable).
- **States:** `loading` (skeleton tiles/charts), `empty` (not enough data yet for this scope — distinct from a failed load), `populated` (metrics with source + freshness), `error` (a metric/query failed; retry that tile without breaking the page), `offline` (dashboards cached and marked stale), `permission-denied` (restricted metrics/scopes gated), `blocked` (a metric that cannot be computed or verified is shown as uncertain, not as a confident zero), `success` (export completed). Analytics is read-only; no destructive-confirmation of its own. See [STATES.md](STATES.md).

### C.4 Security / Անվտանգություն

- **Entry point:** Sidebar → System → **Security**; also from a security-warning notification and from Settings → Privacy.
- **Primary action:** Manage permissions, secrets, sessions, devices, audit records, protected actions, backups, incidents, and recovery — the highest-trust surface, so every change is gated and audited.
- **Key sub-flows:**
  1. **Permissions.** Review roles (Owner, Admin, Member, Viewer, Agent, Service) and scoped grants; deny-by-default. Permission changes are a mandatory approval gate and require fresh authorization.
  2. **Secrets & sessions.** View secret and provider-key status, active sessions and devices; revoke a session/device; rotate a secret. Secret access and key changes are gated and never logged in plaintext.
  3. **Audit & incidents.** Read security events; acknowledge and resolve warnings (`raised → acknowledged → resolved`).
  4. **Backups & recovery.** Check backup status; run a recovery flow behind dual confirmation.
- **States:** `loading`, `empty` (for example no incidents — a healthy state, clearly positive), `populated` (each item names owner/authority and status), `error`, `offline` (status cached and marked stale; all security writes disabled offline), `permission-denied` (non-owner/admin sees a clear access-restricted surface naming the authority), `awaiting-approval` (permission changes, secret access, and key rotation pause at the gate; fresh authorization required), `destructive-confirmation` (revoke access / rotate secret / restore backup name the exact consequence, with a match step for the highest-impact actions; emergency stop overrides active approvals), `success` (change applied and audit event recorded). See [STATES.md](STATES.md).

### C.5 Settings / Կարգավորումներ

- **Entry point:** Sidebar → System → **Settings**; also from a profile menu and from context-specific "Settings" links.
- **Primary action:** Configure language, theme, accessibility, behavior, notifications, models, storage, privacy, integrations, and developer controls.
- **Key sub-flows:**
  1. **Preferences.** Language (HY/EN/RU, equal quality), theme (Dark/Light), accessibility (including reduced motion), and behavior. Changes apply immediately with a clear confirmation.
  2. **Notifications.** Per-type channel, quiet hours, and digest — the same model surfaced from B.4.
  3. **Models & providers.** Choose default and per-task models; provider/key management links into Integrations/Security and inherits their approval gates.
  4. **Privacy, storage, developer.** Data retention and privacy controls, storage usage, and developer/advanced toggles. High-impact toggles confirm before applying.
- **States:** `loading`, `empty` (rare — a section with nothing configured yet), `populated` (current values shown; ownership/scope where a setting is shared), `error` (a save failed; retry, prior value preserved), `offline` (settings cached; writes that need the server disabled with reason), `permission-denied` (workspace/system-level settings gated to Owner/Admin, disabled with reason), `awaiting-approval` (settings that change provider keys, permissions, or security posture pause at the gate), `destructive-confirmation` (reset-to-default, wipe local data, or revoke access name the effect), `success` (setting saved and reflected). See [STATES.md](STATES.md).

---

## Coverage note

With this document, every primary workspace in [SCREEN_INVENTORY.md](SCREEN_INVENTORY.md) now has a defined user flow: Home and Command via [USER_FLOWS.md](USER_FLOWS.md); Chat and Group Chat via [CHAT_FLOWS.md](CHAT_FLOWS.md); Projects and Tasks via [PROJECT_TASK_FLOWS.md](PROJECT_TASK_FLOWS.md); Approvals via [DECISION_APPROVAL_FLOWS.md](DECISION_APPROVAL_FLOWS.md); Agents via [AGENT_FLOWS.md](AGENT_FLOWS.md); and the fourteen Intelligence/Operations/System workspaces above. This satisfies Roadmap Phase 1: "every MVP capability has a defined user flow."

---

# Հայերեն

Կարգավիճակ․ Draft canonical

Այս փաստաթուղթը սահմանում է, թե իրականում ինչ է տեսնում և անում օգտատերը մնացած յուրաքանչյուր workspace-ի ներսում։ Այն կոնկրետ է և քայլ առ քայլ, և հենվում է ճշմարտության միակ աղբյուրների վրա․ workspace-ների պատասխանատվությունը գալիս է [WORKSPACES.md](WORKSPACES.md)-ից; այստեղ նշված յուրաքանչյուր վիճակ (`loading`, `empty`՝ իր first-run / no-results / filtered ենթատեսակներով, `populated`, `error`, `offline`, `permission-denied`, `blocked`, `awaiting-approval`, `destructive-confirmation`, `success`) կանոնական օրինաչափությունն է, որ սահմանված է [STATES.md](STATES.md)-ում և ՉՊԵՏՔ Է վերասահմանվի այստեղ՝ միայն հղվի։ Ագենտի status-երը, engine-ները, approval level-երը (`A0–A3`) և delegation պայմանագիրը նույնն են, ինչ [../AI_RUNTIME.md](../AI_RUNTIME.md)-ում։ Պարտադիր approval gate-երն ու permission մոդելը հետևում են [../docs/architecture/NOTIFICATIONS_AND_PERMISSIONS.md](../docs/architecture/NOTIFICATIONS_AND_PERMISSIONS.md)-ին։

Առանձին փաստաթուղթ ունեցող հոսքերն այստեղ շրջանակից դուրս են․ Chat և Group Chat ([CHAT_FLOWS.md](CHAT_FLOWS.md)), Projects և Tasks ([PROJECT_TASK_FLOWS.md](PROJECT_TASK_FLOWS.md)), Decisions-as-approval և Approvals ([DECISION_APPROVAL_FLOWS.md](DECISION_APPROVAL_FLOWS.md)), և Agents ([AGENT_FLOWS.md](AGENT_FLOWS.md))։ Decisions workspace-ի մակերեսն ինքը ներառված է ստորև՝ ամբողջականության համար, և իր approval մեխանիկան փոխանցում է այդ փաստաթղթին։

Համընդհանուր կանոն ([USER_FLOWS.md](USER_FLOWS.md)-ից)․ ոչ մի հոսք չի կարող թաքցնել կատարման վիճակը, հաստատման վիճակը, սեփականությունը, ձախողումը կամ անորոշությունը։

---

## Ա. Intelligence

### Ա.1 Knowledge / Գիտելիք

- **Մուտքի կետ․** Sidebar → Intelligence → **Knowledge**; նաև ցանկացած Bro պատասխանի citation-ից, project-ի Knowledge tab-ից կամ chat հաղորդագրության «Save to knowledge»-ից։
- **Հիմնական գործողություն․** Գտնել և cite անել ստուգված, աղբյուրով հաստատվող գիտելիքի տարր, ինչպես նաև ավելացնել կամ promote անել այն։
- **Հիմնական ենթահոսքեր․**
  1. **Browse / որոնում.** Ձախ facet-ներ (scope, owner, freshness, verification state, sensitivity)։ Կենտրոնի ցանկը ցույց է տալիս աղբյուրը, owner-ը, version-ը, թարմությունը և canonical-vs-draft badge; canonical-ն ու draft-ը մնում են տեսողապես տարբերվող։
  2. **Բացել տարր.** Աջ վահանակը ցույց է տալիս provenance-ը (source id, created/updated), կապված decision-ները, retrieval metadata-ն և supersession state-ը։ Ամեն տարր հետագծվում է աղբյուրին; ոչ մի բան առանց աղբյուրի չէ։
  3. **Ավելացնել / promote.** Import փաստաթուղթ, պահել ստուգված արդյունք, կամ draft-ը promote canonical-ի։ Promote-ը գրանցում է owner և verification state և երբեք ավտոմատ չի override անում առկա approved բովանդակությունը՝ հակասությունները բացահայտվում են, ոչ միաձուլվում։
  4. **Supersede / revoke.** Superseding-ը հղում է նախորդ version-ին; revoke արված կամ ջնջված աղբյուրը դադարում է retrieve լինել և citation-ներում հայտնվել։
- **Վիճակներ․** `loading` (skeleton, owner տեսանելի), `empty` (first-run՝ import հրավեր; no-results vs. filtered տարբերվող), `populated` (verification badge inline), `error` (retry ձախողված index/load), `offline` (cached տարրերը՝ stale, գրելը անջատված), `permission-denied` (scoped/sensitive տարրերը՝ տեսանելի-բայց-անջատված պատճառով), `blocked` (չստուգված կամ հակասող աղբյուրը նշվում է, չի ցուցադրվում որպես վստահելի), `destructive-confirmation` (revoke/delete՝ հետևանքով), `success` (import/promote հաստատված և ցանկում արտացոլված)։ Տես [STATES.md](STATES.md)։

### Ա.2 Memory / Հիշողություն

- **Մուտքի կետ․** Sidebar → Intelligence → **Memory**; նաև ցանկացած պատասխանի «ինչու՞ Bro-ն սա գիտեր» affordance-ից։
- **Հիմնական գործողություն․** Inspect, correct կամ remove ցանկացած մշտական հիշողություն։ Թաքնված հիշողություն չի թույլատրվում։
- **Հիմնական ենթահոսքեր․**
  1. **Browse ըստ դասի.** Խմբավորված ըստ memory class-երի (working, conversation, project, user preference, failure, canonical)։ Ամեն record-ը ցույց է տալիս source, scope, timestamp, confidence և owner։
  2. **Inspect օգտագործումը.** Բացել record՝ տեսնելու որտեղից է եկել և որտեղ է օգտագործվել (համակարգը պետք է երկուսն էլ բացահայտի)։ Sensitive memory-ն նշվում և նվազեցվում է։
  3. **Correct / supersede / expire / delete.** Ցանկացած record կարող է ուղղվել, superseded, expired կամ deleted լինել; ուղղումները պահում են provenance։
  4. **Review write candidate-ներ.** Առաջարկվող հիշողությունների հերթ (`candidate → classify → deduplicate → verify source → approve policy → persist`)՝ Gev-ը accept/reject է անում նախքան persist-ը։
- **Վիճակներ․** `loading`, `empty` (այս class-ում դեռ հիշողություն չկա), `populated` (confidence + scope inline), `error`, `offline` (cached, գրելը անջատված), `permission-denied` (sensitive memory gated), `awaiting-approval` (write candidate-ը owner approval է պահանջում persist-ից առաջ), `destructive-confirmation` (delete/purge՝ ճշգրիտ record-ով), `success` (correction/deletion արտացոլված)։ Տես [STATES.md](STATES.md)։

### Ա.3 Decisions / Որոշումներ

- **Մուտքի կետ․** Sidebar → Intelligence → **Decisions**; նաև chat/room-ի «Create decision»-ից և project-ի Decisions tab-ից։
- **Հիմնական գործողություն․** Գրանցել և հետևել հստակ, վերագրելի որոշմանն իր lifecycle-ով։ Approval մեխանիկան փոխանցվում է [DECISION_APPROVAL_FLOWS.md](DECISION_APPROVAL_FLOWS.md)-ին։
- **Հիմնական ենթահոսքեր․**
  1. **Browse / filter** ըստ state-ի (`proposed → under review → approved | rejected | deferred → superseded`), owner, scope, effective date։
  2. **Բացել որոշում.** Ցույց է տալիս context, դիտարկված option-ներ, ընտրված option, rationale, owner, approver, consequences և rollback/replacement path։
  3. **Propose / փոխել state.** Ստեղծել որոշում (`proposed`); ուղղել review; approver-ը approve/reject/defer է անում։ Լռությունը երբեք approval չէ; chat համաձայնությունը canonical չէ մինչև գրանցումը; ագենտները կարող են recommend անել, բայց չեն կարող approver-ի կերպար ընդունել։
  4. **Supersede.** Superseding որոշումը պետք է հղի նախորդին; շղթան մնում է տեսանելի։
- **Վիճակներ․** `loading`, `empty` (first-run՝ գրանցել առաջին որոշումը), `populated` (state + owner + approver inline), `error`, `offline` (read cached, state չի փոխվում), `permission-denied` (approve-ը gated approver-ին), `blocked` (սպասում upstream dependency-ի կամ չստուգված context-ի), `awaiting-approval` (բարձր ազդեցության որոշումը կասեցված է owner-ի բացահայտ approval-ի), `destructive-confirmation` (reject/supersede՝ էֆեկտով), `success` (approved որոշումը թարմացնում է կապված task/knowledge/policy)։ Տես [STATES.md](STATES.md)։

### Ա.4 Research / Հետազոտություն

- **Մուտքի կետ․** Sidebar → Intelligence → **Research**; նաև command-ի, room-ի կամ project risk-ի «Investigate»-ից։
- **Հիմնական գործողություն․** Կատարել evidence-first հետազոտություն, որ ավարտվում է cite արված findings-ով՝ բացահայտ confidence-ով և բաց gap-երով։
- **Հիմնական ենթահոսքեր․**
  1. **Բացել / սահմանել investigation.** Ձևակերպել հարց(եր)ը, scope-ը և դիտարկվող աղբյուրները։
  2. **Հավաքել evidence.** Bro-ն կամ research agent-ը (օրինակ Probe-class specialist) fan-out է անում աղբյուրները; live run-ը հետևում է ագենտի execution model-ին (`assigned → accepted → running → blocked | completed | failed | cancelled`)՝ ընթացիկ քայլն ու ագենտի անունը միշտ տեսանելի։
  3. **Review findings.** Findings-ը ցույց է տալիս աղբյուրները, բացահայտված (ոչ միաձուլված) հակասությունները, confidence-ը և մնացած gap-երը։ Անորոշությունը ցուցադրվում է որպես անորոշություն։
  4. **Promote.** Ստուգված finding-ը կարող է դառնալ knowledge (Ա.1) կամ decision evidence (Ա.3)՝ provenance-ը փոխանցելով։
- **Վիճակներ․** `loading` (running investigation-ի համար դետերմինիստիկ առաջընթաց + live step label, ոչ bare spinner), `empty` (first-run՝ սկսել investigation), `populated` (findings՝ confidence + citation), `error` (աղբյուր կամ քայլ ձախողվեց; retry), `offline` (cached findings՝ stale, նոր run-երն անջատված), `permission-denied` (restricted աղբյուր կամ investigation), `blocked` (սպասում աղբյուրի, dependency-ի կամ չստուգելի claim-ի — ազնվորեն ցուցադրված, երբեք որպես false success), `awaiting-approval` (high-cost կամ external-fetch run-ը կասեցվում է approval-ի), `success` (investigation ստուգված և փակված)։ Տես [STATES.md](STATES.md)։

### Ա.5 Library / Գրադարան

- **Մուտքի կետ․** Sidebar → Intelligence → **Library**; նաև project, task, room կամ automation ստեղծելիս «Use template»-ից։
- **Հիմնական գործողություն․** Գտնել և կիրառել curated, reusable asset (template, prompt, spec, procedure, approved output)։
- **Հիմնական ենթահոսքեր․**
  1. **Browse / որոնում** ըստ type, owner և tag; ամեն asset ցույց է տալիս owner, version և last-updated։
  2. **Preview.** Կարդալ asset-ը և տեսնել որտեղ է օգտագործվում՝ նախքան կիրառելը։
  3. **Apply.** Instantiate template կամ insert prompt/procedure target մակերեսում; origin asset-ը հղվում է հետ՝ provenance-ի համար։
  4. **Ավելացնել / version.** Պահել նոր asset կամ publish նոր version; superseded version-ները մնում են retrievable և հղված։
- **Վիճակներ․** `loading`, `empty` (first-run՝ ավելացնել առաջին asset-ը; no-results vs. filtered տարբերվող), `populated` (version + owner inline), `error`, `offline` (browse cached, apply/publish անջատված), `permission-denied` (private/team asset-ները gated), `destructive-confirmation` (delete/unpublish՝ էֆեկտով և dependents-ով), `success` (asset կիրառված կամ version հրապարակված, ցանկում արտացոլված)։ Տես [STATES.md](STATES.md)։

---

## Բ. Operations

### Բ.1 Calendar / Օրացույց

- **Մուտքի կետ․** Sidebar → Operations → **Calendar**; նաև task deadline-ից, automation schedule-ից կամ Home-ի calendar-pressure վահանակից։
- **Հիմնական գործողություն․** Տեսնել և կառավարել ժամանակի պարտավորությունները՝ deadline-ներ, focus window-ներ, ագենտների schedule-ներ և automation trigger-ներ՝ մեկ timeline-ում։
- **Հիմնական ենթահոսքեր․**
  1. **Փոխել view** (day / week / month / agenda); filter ըստ source-ի (tasks, events, agent runs, automation triggers)։
  2. **Բացել entry.** Deadline-ներն ու agent/automation entry-ները deep-link են դեպի իրենց task, agent run կամ automation; ownership-ը անվանված է։
  3. **Ստեղծել / reschedule.** Ավելացնել focus window կամ event; քաշել՝ reschedule անելու համար։ Task/automation-ի հետ կապված item-ը reschedule անելն ցույց է տալիս downstream էֆեկտը նախքան պահելը։
  4. **Լուծել pressure.** Ուշացած կամ բախվող պարտավորությունները նշվում են՝ blocker-ի կամ owner-ի ուղով։
- **Վիճակներ․** `loading` (skeleton grid), `empty` (first-run՝ ոչինչ նշանակված չէ), `populated` (ամեն entry ցույց է տալիս source + owner + live run status ըստ կիրառելիության), `error`, `offline` (cached calendar՝ stale, խմբագրումն անջատված), `permission-denied` (ուրիշների կամ restricted schedule-ները gated), `blocked` (upstream item-ի սպասող deadline-ը նշվում է, ոչ լուռ անցնում), `destructive-confirmation` (delete/cancel event՝ անվանելով), `success` (create/reschedule հաստատված և արտացոլված)։ Տես [STATES.md](STATES.md)։

### Բ.2 Automations / Ավտոմատացումներ

- **Մուտքի կետ․** Sidebar → Operations → **Automations**; նաև կրկնվող command-ի կամ task-ի «Automate this»-ից։
- **Հիմնական գործողություն․** Ստեղծել, inspect անել և անվտանգ վերահսկել condition- կամ schedule-based workflow-ները՝ ամեն մեկը տեսանելի owner, trigger, action, permissions, approval policy, run history և disable switch-ով։
- **Հիմնական ենթահոսքեր․**
  1. **Browse.** Ամեն automation ցույց է տալիս owner, trigger, action, enabled/disabled state, approval policy և last-run result։
  2. **Ստեղծել / configure.** Սահմանել trigger (schedule կամ condition), action, target scope, permission scope և approval policy։ External side-effect-ով automation-ի enable-ը պարտադիր approval gate է։
  3. **Run / dry-run.** Preview էֆեկտը; տեսնել run history (`triggered → skipped | completed | failed`)՝ ամեն run-ի evidence-ով։
  4. **Disable / delete.** Disable switch-ը միշտ մեկ գործողություն հեռու է; deletion-ը հաստատում է հետևանքները։
- **Վիճակներ․** `loading`, `empty` (first-run՝ ստեղծել առաջին automation-ը), `populated` (enabled state + last-run result inline), `error` (run ձախողվեց; retry/inspect log), `offline` (history cached; enable/run անջատված), `permission-denied` (ուրիշների automation-ների կառավարումը gated), `blocked` (automation սպասում է չբավարարված condition-ի կամ dependency-ի), `awaiting-approval` (external-side-effect automation-ի enable-ը կամ high-risk run-ը կասեցվում է approval-ի), `destructive-confirmation` (active automation-ի disable/delete՝ էֆեկտով), `success` (enabled/created/run-complete հաստատված)։ Տես [STATES.md](STATES.md)։

### Բ.3 Activity / Գործունեություն

- **Մուտքի կետ․** Sidebar → Operations → **Activity**; նաև ցանկացած object-ի «View activity»-ից և execution-log հղումից։
- **Հիմնական գործողություն․** Կարդալ և filter անել user, agent, tool, system և automation event-երի ժամանակագրական, append-only գրառումը։
- **Հիմնական ենթահոսքեր․**
  1. **Filter / որոնում** ըստ actor type, source, scope, event family, risk level և time range-ի։
  2. **Բացել event.** Ցույց է տալիս event shape-ը (actor, source, correlation/causation, scope, result, risk, approval id ըստ կիրառելիության)։ Ձախողված և մերժված գործողությունները նույնպես այստեղ են։
  3. **Trace correlation.** Հետևել `correlation_id`-ին՝ տեսնելու կապված աշխատանքի ամբողջ շղթան մակերեսների միջով։
  4. **Export.** Export filtered slice (permission-gated; export-ը auditable գործողություն է)։
- **Վիճակներ․** `loading` (skeleton stream), `empty` (այս scope-ում դեռ event չկա), `populated` (ամեն row անվանում է actor + result; append-only, երբեք լուռ չի վերագրվում), `error`, `offline` (cached stream՝ stale, live tail-ը դադարեցված հստակ ցուցիչով), `permission-denied` (restricted-scope event-ները gated), `success` (export ավարտված հղումով)։ Activity-ն read-only է, ուստի իր destructive-confirmation չունի։ Տես [STATES.md](STATES.md)։

### Բ.4 Notifications / Ծանուցումներ

- **Մուտքի կետ․** Shell notification bell / badge → **Notifications** (ամբողջ workspace); նաև notification center մակերեսը։
- **Հիմնական գործողություն․** Triage անել actionable alert-ները մինչև լուծում։ Ամեն ծանուցում կրում է severity, source, object, reason և resolution path։
- **Հիմնական ենթահոսքեր․**
  1. **Triage inbox.** Filter ըստ type-ի (approval required, run completed, run failed, task due, mention, assignment, automation result, security warning, backup status) և severity-ի; deduplicated ըստ key-ի։
  2. **Act.** Ամեն item deep-link է դեպի իր action target՝ approve, բացել ձախողված run, բացել due task, ցատկել mention։ Approval-required item-ները ուղղվում են approval հոսք։
  3. **Manage state.** Mark read, snooze կամ dismiss; created/read timestamp-ները պահվում են։
  4. **Configure delivery.** Per-type channel (in-app, desktop, badge, optional email), quiet hours և digest։
- **Վիճակներ․** `loading`, `empty` (inbox zero — դրական վիճակ, ոչ error), `populated` (severity + source + resolution path inline), `error` (delivery/fetch ձախողվեց; retry), `offline` (cached ցանկ՝ stale, նոր delivery-ները queued/paused՝ տեսանելի), `permission-denied` (restricted object-ների ծանուցումները gated), `awaiting-approval` (approval-required ծանուցումն արտացոլում է pending gate-ը), `destructive-confirmation` (bulk-dismiss/clear՝ էֆեկտով), `success` (item լուծված և արտացոլված)։ Տես [STATES.md](STATES.md)։

---

## Գ. System

### Գ.1 Files / Ֆայլեր

- **Մուտքի կետ․** Sidebar → System → **Files**; նաև project-ի Files tab-ից, chat attachment-ից և File preview-ից։
- **Հիմնական գործողություն․** Կառավարել ֆայլերը preview, provenance, versioning, links, permissions և project association-ներով։
- **Հիմնական ենթահոսքեր․**
  1. **Browse / որոնում.** List կամ grid՝ owner, project association, version և source-ով; preview inline։
  2. **Բացել / preview.** File preview-ն ցույց է տալիս provenance-ը (որտեղից է եկել), version history-ն և կապված object-ները (tasks, decisions, knowledge)։
  3. **Upload / նոր version.** Ավելացնել ֆայլ կամ publish նոր version; association-ներն ու permission-ները սահմանվում են պահելիս։
  4. **Delete / overwrite.** Ֆայլի deletion կամ overwrite-ը պարտադիր approval gate է և միշտ հաստատում է հետևանքները։
- **Վիճակներ․** `loading` (skeleton grid), `empty` (first-run՝ upload առաջին ֆայլը; no-results vs. filtered տարբերվող), `populated` (owner + version + project inline), `error` (upload/preview ձախողվեց; retry), `offline` (cached ֆայլերը՝ stale, upload/delete անջատված), `permission-denied` (restricted ֆայլերը՝ տեսանելի-բայց-անջատված պատճառով), `awaiting-approval` (delete/overwrite-ը կասեցված gate-ում), `destructive-confirmation` (delete/overwrite՝ ճշգրիտ ֆայլ և անշրջելիություն, high-impact-ի համար match step), `success` (upload/version հաստատված և արտացոլված)։ Տես [STATES.md](STATES.md)։

### Գ.2 Integrations / Ինտեգրացիաներ

- **Մուտքի կետ․** Sidebar → System → **Integrations**; նաև Settings → Integrations-ից և դեռ չմիացած ծառայություն պահանջող հոսքից։
- **Հիմնական գործողություն․** Connect, inspect և revoke անել արտաքին ծառայությունները՝ հստակ credential status, granted scopes, health և sync state-ով։
- **Հիմնական ենթահոսքեր․**
  1. **Browse connection-ներ.** Ամեն մեկը ցույց է տալիս connection status, granted scopes, health և last sync։
  2. **Connect.** Կատարել provider authorization հոսքը; վերադարձին granted scope-ները ցուցադրվում են բացահայտ։ Non-interactive/offline համատեքստում հոսքը հայտնում է, որ authorization-ը պետք է ավարտվի այլ տեղ՝ ոչ թե ձևացնի հաջողություն։
  3. **Manage scopes / re-auth.** Կարգավորել granted scope-ները կամ թարմացնել expired credential-ները; provider key-երի փոփոխությունը պարտադիր approval gate է։
  4. **Revoke / disconnect.** Revocation-ը հաստատում է հետևանքները (որ automation-ները, ագենտները կամ project-ները access կկորցնեն) և կանգնեցնում է հետագա sync-ը։
- **Վիճակներ․** `loading`, `empty` (first-run՝ ոչ մի integration միացված չէ), `populated` (status + scopes + health inline), `error` (auth/sync ձախողվեց պարզ պատճառով; retry), `offline` (status cached և stale; connect/revoke անջատված), `permission-denied` (integration-ների կառավարումը gated Owner/Admin-ին, անջատված պատճառով), `blocked` (connection-ը կանգնած՝ սպասելով արտաքին authorization-ի, ազնվորեն ցուցադրված — երբեք որպես connected), `awaiting-approval` (provider-key/secret փոփոխությունները կասեցված gate-ում), `destructive-confirmation` (revoke/disconnect՝ dependents-ով), `success` (connected/scopes-updated հաստատված)։ Տես [STATES.md](STATES.md)։

### Գ.3 Analytics / Վերլուծություն

- **Մուտքի կետ․** Sidebar → System → **Analytics**; նաև Home-ի system-health վահանակից։
- **Հիմնական գործողություն․** Կարդալ operational insight-ը՝ outcomes, throughput, blockers, agent quality, costs, approvals, automation reliability և system health։
- **Հիմնական ենթահոսքեր․**
  1. **Ընտրել scope / range.** Ընտրել workspace/project scope, time range և metric group։
  2. **Read dashboards.** Chart-երն ու KPI tile-ները հետևում են Design System-ին (count-up populate-ի ժամանակ; reduced-motion-ում վերջնական արժեքն անմիջապես)։ Ամեն metric անվանում է իր source-ը և թարմությունը։
  3. **Drill down.** Սեղմել metric-ի վրա՝ դեպի հիմքում ընկած item-ները (օրինակ cost spike → այն run-երը, որ առաջացրին) Activity-ում կամ համապատասխան workspace-ում։
  4. **Export.** Export filtered report (permission-gated, auditable)։
- **Վիճակներ․** `loading` (skeleton tile/chart), `empty` (այս scope-ի համար դեռ բավարար տվյալ չկա — տարբեր ձախողված load-ից), `populated` (metric-ներ՝ source + freshness), `error` (metric/query ձախողվեց; retry այդ tile-ը՝ առանց էջը կոտրելու), `offline` (dashboard-ները cached և stale), `permission-denied` (restricted metric/scope-ները gated), `blocked` (չհաշվարկվող կամ չստուգվող metric-ը ցուցադրվում է որպես անորոշ, ոչ որպես վստահ զրո), `success` (export ավարտված)։ Analytics-ը read-only է; իր destructive-confirmation չունի։ Տես [STATES.md](STATES.md)։

### Գ.4 Security / Անվտանգություն

- **Մուտքի կետ․** Sidebar → System → **Security**; նաև security-warning ծանուցումից և Settings → Privacy-ից։
- **Հիմնական գործողություն․** Կառավարել permissions, secrets, sessions, devices, audit records, protected actions, backups, incidents և recovery — ամենաբարձր վստահության մակերեսը, ուստի ամեն փոփոխություն gated և audited է։
- **Հիմնական ենթահոսքեր․**
  1. **Permissions.** Review անել role-երը (Owner, Admin, Member, Viewer, Agent, Service) և scoped grant-ները; deny-by-default։ Permission փոփոխությունը պարտադիր approval gate է և պահանջում է fresh authorization։
  2. **Secrets & sessions.** Տեսնել secret-ի և provider-key-ի status-ը, active session-ներն ու device-ները; revoke session/device; rotate secret։ Secret access-ը և key փոփոխությունները gated են և երբեք plaintext-ով չեն log-վում։
  3. **Audit & incidents.** Կարդալ security event-ները; acknowledge և resolve warning-ները (`raised → acknowledged → resolved`)։
  4. **Backups & recovery.** Ստուգել backup status; կատարել recovery հոսք dual confirmation-ի ետևում։
- **Վիճակներ․** `loading`, `empty` (օրինակ incident չկա — առողջ, հստակ դրական վիճակ), `populated` (ամեն item անվանում է owner/authority և status), `error`, `offline` (status cached և stale; բոլոր security write-երը անջատված offline-ում), `permission-denied` (ոչ owner/admin-ը տեսնում է հստակ access-restricted մակերես՝ authority-ն անվանելով), `awaiting-approval` (permission փոփոխություն, secret access և key rotation կասեցվում են gate-ում; fresh authorization պահանջվում է), `destructive-confirmation` (revoke access / rotate secret / restore backup՝ ճշգրիտ հետևանքով, ամենաբարձր ազդեցության համար match step; emergency stop-ը override է անում active approval-ները), `success` (փոփոխությունը կիրառված և audit event գրանցված)։ Տես [STATES.md](STATES.md)։

### Գ.5 Settings / Կարգավորումներ

- **Մուտքի կետ․** Sidebar → System → **Settings**; նաև profile menu-ից և համատեքստային «Settings» հղումներից։
- **Հիմնական գործողություն․** Կարգավորել language, theme, accessibility, behavior, notifications, models, storage, privacy, integrations և developer controls։
- **Հիմնական ենթահոսքեր․**
  1. **Preferences.** Language (HY/EN/RU, հավասար որակ), theme (Dark/Light), accessibility (ներառյալ reduced motion) և behavior։ Փոփոխությունները կիրառվում են անմիջապես՝ հստակ հաստատումով։
  2. **Notifications.** Per-type channel, quiet hours և digest — նույն մոդելը՝ Բ.4-ից։
  3. **Models & providers.** Ընտրել default և per-task model-ներ; provider/key management-ը հղվում է Integrations/Security և ժառանգում է իրենց approval gate-երը։
  4. **Privacy, storage, developer.** Data retention և privacy controls, storage usage և developer/advanced toggle-ներ։ High-impact toggle-ները հաստատում են նախքան կիրառելը։
- **Վիճակներ․** `loading`, `empty` (հազվադեպ — դեռ ոչինչ չկարգավորված բաժին), `populated` (ընթացիկ արժեքները ցուցադրված; ownership/scope, երբ setting-ը shared է), `error` (save ձախողվեց; retry, նախորդ արժեքը պահված), `offline` (settings cached; server պահանջող write-երը անջատված պատճառով), `permission-denied` (workspace/system-level settings-ը gated Owner/Admin-ին, անջատված պատճառով), `awaiting-approval` (provider key, permission կամ security posture փոխող setting-ները կասեցվում են gate-ում), `destructive-confirmation` (reset-to-default, wipe local data կամ revoke access՝ էֆեկտով), `success` (setting պահված և արտացոլված)։ Տես [STATES.md](STATES.md)։

---

## Ծածկույթի նշում

Այս փաստաթղթով [SCREEN_INVENTORY.md](SCREEN_INVENTORY.md)-ի յուրաքանչյուր հիմնական workspace այժմ ունի սահմանված user flow․ Home և Command՝ [USER_FLOWS.md](USER_FLOWS.md)-ով; Chat և Group Chat՝ [CHAT_FLOWS.md](CHAT_FLOWS.md)-ով; Projects և Tasks՝ [PROJECT_TASK_FLOWS.md](PROJECT_TASK_FLOWS.md)-ով; Approvals՝ [DECISION_APPROVAL_FLOWS.md](DECISION_APPROVAL_FLOWS.md)-ով; Agents՝ [AGENT_FLOWS.md](AGENT_FLOWS.md)-ով; և վերևի տասնչորս Intelligence/Operations/System workspace-ները։ Սա բավարարում է Roadmap Phase 1-ը․ «every MVP capability has a defined user flow»։
