# BroPS — User Guide

> **Հայերեն նշում / Note on language.** BroPS is **trilingual at runtime** — Հայերեն (hy),
> English (en), Ռուսերեն (ru) — with first-class **Dark** and **Light** themes. Switch language
> and theme in **Settings**. Այս ուղեցույցը անգլերեն է, բայց հավելվածն ինքը ամբողջությամբ
> հայերեն է աշխատում։ This guide is in English; the app itself runs fully in Armenian.

BroPS (*Bro's Personal Space*) is a command-first desktop cockpit for working with Bro and a team
of specialist AI agents across conversations, projects, tasks, knowledge, files, and more. It is a
single-user local desktop app; your data lives in a local database on your machine.

This guide describes **what the app actually does today**. Screens still waiting on their backend
are called out as **Not yet connected**, and the governed "Verified" AI path is called out as
**fail-closed** — both are honest, current states, not marketing.

---

## 1. The window at a glance

BroPS opens to a shell with a left **navigation sidebar** grouped into four sections, a main
workspace pane, a **global search / command palette**, and a language + theme switch in Settings.

The sidebar groups (from `nav.ts`):

- **Core:** Home · Command · Chat · Group Chat · Projects · Tasks · Agents
- **Intelligence:** Knowledge · Memory · Decisions · Research\* · Library\*
- **Operations:** Calendar · Automations · Approvals · Activity · Notifications
- **System:** Files · Integrations · Analytics · Security · Settings

\* **Research** and **Library** are **Not yet connected** — see §14.

---

## 2. Chat (Direct)

Talk to a single agent. Features that exist:

- **Streaming replies** — the agent's answer appears token-by-token as live Markdown.
- **Agent picker** — choose which agent answers.
- **Conversation management** — create, rename, and delete conversations.
- **Ask Bro (one-shot)** — stream an answer to a single prompt without saving it, then optionally
  **save the finished answer to a chat**.

### Governed replies are fail-closed (important)

BroPS distinguishes **ungoverned** providers (your local `claude` CLI, the Anthropic API, or
Ollama — these answer normally) from **governed** execution (a turn routed through the engine's
security wall to earn a cryptographically **verified** receipt).

The governed "Verified" path is **not finished** and is deliberately **fail-closed**: a governed
turn is **Blocked** and shows a transient notice — *"Governed reply blocked (unverified)"* — with
**no message saved**. This is by design: BroPS refuses to show a governed answer it cannot verify.
For everyday use, use an ungoverned provider; governed "Verified" mode will light up when the
signed-receipt signer work lands.

---

## 3. Group Chat

A first-class multi-agent conversation. You can `@mention` specific agents, pick who replies, and
read live Markdown as each agent streams. Rename and delete group conversations like direct ones.
(Agent messages are always minted server-side — the app never lets the UI forge an "agent" message.)

---

## 4. Command (agent runs)

**Command** turns an intent + plan into a **run** made of ordered **steps**, executed one at a time
by the AI. What works:

- Create a run (intent + plan) and add steps.
- **Execute the next runnable step** via the AI provider, streaming its output.
- **Approval gating** — a step marked *requires approval* **cannot run until it is approved**.
  If it is **rejected, that is terminal** — the step will not run.
- Advance the run step-by-step; watch status change per step.

Approvals raised here appear in the **Approvals** screen (§9).

---

## 5. Projects

- Create projects; open a **detail** view with **Overview** and **Tasks** tabs.
- Edit a project's name, description, and priority; change its **status**.
- See the project's tasks inline.

---

## 6. Tasks

- A **kanban board** — drag a task between status columns to change its status.
- Create and edit tasks (title, description, priority).
- **Dependencies / blockers** — mark a task as blocked by another. The app guards against a task
  depending on itself (self-edge) and against dependency **cycles**.

---

## 7. Agents

Browse the roster of specialist agents available to Chat, Group Chat, and Command runs.

---

## 8. Knowledge & Memory

- **Knowledge** — create notes and **full-text search** across them.
- **Memory** — durable entries you can **pin** (keep at the top) and delete, optionally scoped.

Both are backed by real storage and feed the global search (§13).

---

## 9. Approvals & Decisions

- **Approvals** — the human gate for gated agent-run steps. **Approving uses a native OS
  confirmation dialog** driven by the app's backend, not a webview button — so an approval can't be
  forged by page content. **Rejecting** is a dedicated, fail-safe action. You cannot approve your
  own request (self-approval is refused, even across app restarts).
- **Decisions** — record decisions with a title and rationale, and review the log.

---

## 10. Calendar, Automations, Activity, Notifications

- **Calendar** — a **month view**; create and delete events.
- **Automations** — create trigger→action automations and toggle them **enabled/disabled** (this is
  the record-and-manage surface; automations are stored, not yet a background scheduler).
- **Activity** — a feed of what has happened in the app.
- **Notifications** — your notifications list; **mark as read**.

---

## 11. Files

A filesystem browser confined to one **workspace root** (`~/BroPS` by default):

- Browse directories.
- **View and edit** text files (guarded: files over ~2 MB and binary files are refused).
- Edits are limited to **existing** files (no create), saved atomically.
- **Sensitive paths are hidden and blocked** — things like `.ssh`, `.env*`, `*.pem`, credential
  files, and other secrets can't be listed, read, or written, even inside a broad root. Paths that
  try to escape the root (via `..` or symlinks) are rejected.

---

## 12. Analytics, Security, Integrations, Settings

- **Analytics** — computed metrics and charts over your data (read-only).
- **Security** — a summary: pending vs. decided approvals, audit-event count, and recent
  sensitive events.
- **Integrations** — the list of integrations and their status (enable/disable state is stored;
  this is the management surface).
- **Settings** — switch **language** (hy/en/ru) and **theme** (Dark/Light), and view the resolved
  **AI provider** (read-only — it's set by the environment, not editable in-app; the governed vs.
  ungoverned label is shown here).

---

## 13. Global search & command palette

Open the **command palette** to search **everything at once** — projects, tasks, knowledge,
decisions, agents, chats, and memory — powered by full-text search. Results are **deep links**:
selecting one opens the *specific* project / task / note / conversation, not just its screen.

---

## 14. Screens that are "Not yet connected"

BroPS is honest about unfinished surfaces. **Research** and **Library** currently show a plain
*"Not yet connected to the backend"* placeholder — no fake data — until their backend lands
(Roadmap Phase 4). Everything else in the sidebar is backed by real commands and your local
database.

---

## 15. Offline / preview mode

If you open the frontend outside the desktop runtime (e.g. a plain browser preview), there is no
backend: the app shows an honest **"Backend unavailable / Preview mode"** banner and disables data
actions. In the installed desktop app this does not apply — the Rust + SQLite backend is always
present.

---

## 16. Your data & privacy

- Everything lives in **one local SQLite database** on your machine — no cloud account, no server.
- **API keys are never stored** in the database; they come only from your environment.
- Chat with the local `claude` CLI uses **your own Claude Code subscription** (no separate API
  key). By default the AI runs as a plain, tool-free text completion — a message can't make it read
  your files or run commands.
- **One setting changes that completely.** Started with `BROPS_PROJECT_DIR` pointing at a real
  folder, Bro becomes the conductor: he gets file access, a bounded shell, and the ability to hand
  work to specialists inside that folder. That is the mode where he can actually *do* things for
  you — and it is genuinely file and shell access, so point it at a project you meant to give him.
  Without it, he can only talk.

To back up your work, quit BroPS and copy the app-data folder (see the Operator Guide, §8).
