# README claim history · README-ի պնդումների պատմությունը

**What this file is.** `README.md` is the front page, and every measured number on it has been
wrong at least once. This is the record of what it claimed, what the claim was corrected to, and
**the command that settled it** — so the next person who rewrites the front page can check a
number instead of copying it.

**Why it is here and not in `docs/archive/`.** `CLAUDE.md` defines `docs/archive/` as *history
moved out of the read set*. `README.md` was never in the canonical read set
(`config/canonical-read-manifest.json` lists fourteen paths and it is not one of them), so
nothing was moved out of anything. This is a live reference with a job: it is consulted **before**
the next rewrite, not after. Filing it under `archive/` would describe it wrongly and put it where
nobody looks first.

**Why it is not in `README.md`.** The same reason `NEXT_CHAT.md` is held to 12 KB. A page that
carries both the current statement and every superseded one grows monotonically and stops being
read. The front page states what is true; this file states how it got there.

---

## How to add a row

One row per claim, and a row is only complete with the command. *"It says 32 now"* is not a
correction; *"`ls tools/check_*.py | wc -l` printed 32"* is. If you cannot produce a command that
settles a claim, that claim does not belong on the front page.

---

## 1. Corrected on 2026-08-30, at `main` @ `fe26a78`

The Owner supplied a rewritten `README.md`. Every number in it was re-measured before it landed;
these are the ones that did not survive, plus the ones the previous README carried and the rewrite
replaced silently.

### 1a. Wrong in the Owner's draft — corrected before merge

| Claim in the draft | Measured | Command / evidence |
| :--- | :--- | :--- |
| `contracts/` holds **6** extracted shared schemas (both language blocks) | **5** | `ls contracts/` → `evidence-event`, `execution-lease`, `mode-grant`, `task-contract`, `verifier-receipt` `.schema.json`, plus `README.md` and `index.json`. `tools/check_contracts_single_source.py` prints `GREEN: 5 cross-half contract(s)`. The draft's own list named five — *lease · evidence · receipt · grant · contract* — so the count contradicted the sentence beside it |
| `governed_verification_unconfigured()` "returns `Some(...)` **unconditionally**" | It **measures** five provisioning inputs; all five are compile-time absent, so it returns `Some(...)` on every call in this tree | `apps/desktop/src-tauri/src/commands.rs:1367` calls `governed_provisioning_missing(...)` and returns `None` when nothing is missing. The five inputs at `:1268`–`:1302` are `GOVERNED_TRUSTED_MANIFEST_PROVISIONED = false`, two `absent:` sentinels that `is_lower_hex64` rejects, and two empty rosters. `T-048` made this a measurement; the answer is unchanged and the mechanism is not |
| Rust workspace = **9** crates | **10** — nine `members` plus the root `brops` host package, which is what `--workspace` builds | `cargo metadata --no-deps --manifest-path apps/desktop/src-tauri/Cargo.toml` lists 10 packages: `brops`, `brops-audit-signer`, `brops-broker`, `brops-core`, `brops-executor`, `brops-governed-live`, `brops-launcher`, `brops-provision`, `brops-win-broker`, `brops-win-live` |
| `→ apps/desktop/src-tauri/target/release/brops.exe` | On this Debian box the artifact is **`brops`** | The root package is `name = "brops"`, there is no `[[bin]]` section, and `apps/desktop/src-tauri/tauri.conf.json` sets no `mainBinaryName` (`productName` is `BroPS` and names the *bundle*). `.exe` is the Windows form. Settled from the manifests; `npx tauri build` was **not** run |
| Refusal table cited `src-tauri/src/commands.rs`, `src-tauri/src/governed_turn.rs`, `src-tauri/broker/src/main.rs` | Rewritten to full repo-root paths | Not a factual error — a resolvability one. `tools/check_doc_claims.py` requires a cited path to resolve from the repository root, and three of the five findings it reports today are exactly this shape in `docs/ARCHITECTURE.md` |

### 1b. Right in the Owner's draft — confirmed, not assumed

| Claim | Command | Printed |
| :--- | :--- | :--- |
| Engine suite **2031** tests | `BRO_ENV=ci python3 -m unittest discover -s engine/tests -t engine/tests -q` | `Ran 2031 tests in 28.057s` · `OK (skipped=10)` |
| Bridge suite **210** tests | `BRO_ENV=ci python3 -m unittest discover -s bridge/tests -t bridge/tests -q` | `Ran 210 tests in 0.324s` · `OK` |
| Frontend **758** tests / **80** files | `cd apps/desktop && npx vitest run` | `Test Files 80 passed (80)` · `Tests 758 passed (758)` |
| Negative matrix 29 / 12 / 201 / **242** | `python3 tools/check_negative_matrix.py` | `GREEN: 242 matrix cases, all bound -- 29 implemented …, 12 blocked …, 201 unreviewed and frozen` |
| **32** repository gates | `ls tools/check_*.py \| wc -l` | `32` |
| **8** workflows | `ls .github/workflows/*.yml \| wc -l` | `8` |
| **33** required contexts on `main` | `gh api repos/menqstudio/OS/branches/main/protection --jq '.required_status_checks.contexts\|length'` | `33` |
| **262** specialist definitions | `ls .claude/agents/*.md \| wc -l` | `262`; and `python3 tools/generate_agent_definitions.py --check` → `GREEN: 262 agent definitions match the pack + authority registries` |
| `engine/.claude/` wired for **9** hook events | read the `hooks` keys of `engine/.claude/settings.json` | `InstructionsLoaded, PostToolUse, PostToolUseFailure, PreToolUse, SessionStart, Stop, SubagentStart, SubagentStop, UserPromptSubmit` — 9 |
| root `.claude/` wired for **5** hook events | read the `hooks` keys of `.claude/settings.json` | `PreToolUse, SessionStart, Stop, SubagentStart, UserPromptSubmit` — 5 |
| Workspace member **list** (core · launcher · executor · broker · proof · win-broker · win-live · provision · audit-signer) | `head apps/desktop/src-tauri/Cargo.toml` | `members = ["core", "launcher", "executor", "broker", "proof", "win-broker", "win-live", "provision", "audit-signer"]` — exact, and in that order |
| Three tiers: `reader` / `runner` / `builder` | `TIERS` in `tools/generate_agent_definitions.py` | `reader` = Read, Grep, Glob · `runner` = + Bash · `builder` = + Edit, Write |
| `USE_NETWORK` is in the lease schema and no task class permits it | `engine/schemas/execution-lease.schema.json:54` and `engine/runtime/bro_execution_lease.py:24` | Both `standard-builder` and `security-maintenance` map to `frozenset({"EXECUTE_CODE", "WRITE_FILESYSTEM", "WRITE_REPOSITORY"})`; a lease naming `USE_NETWORK` raises `LeaseError: execution lease grants capabilities beyond its class` |
| The three refusals are at the files named | `grep -n` in each file | `commands.rs:1367`, `governed_turn.rs:230`, `broker/src/main.rs:256`. The pre-flight block returns at `commands.rs:1605`, **before** `crate::ai::governed_turn(&prepared).await` — so "fires before the model is called" holds |

### 1c. Carried by the previous README and replaced by the rewrite

These were true when written. Recorded because a number that is silently replaced teaches nobody
anything, and because the gap between each pair is how long a front-page claim survives unchecked.

| The previous README said | It now says | Note |
| :--- | :--- | :--- |
| `contracts/` — *"Reserved for shared schemas — a README only, nothing extracted yet"* | 5 extracted schemas | Closed by the ninth audit's `I-13`. `contracts/` is the **source**; `tools/check_contracts_single_source.py` fails on drift against the vendored copies in `engine/schemas/` |
| `tools/` — **15** repository gates | **32** | Wrong twice in a row before this: the ninth audit filed the stale counts as `I-10`, and `START_HERE.md` said 19/18 while `docs/ARCHITECTURE.md` said 18 |
| `.github/workflows/` — **7** workflows, **31** checks per PR, *"none **required** — see below"* | **8** workflows, **33** required contexts | Two defects in one cell. Branch protection was turned on 2026-08-17 after the seventh audit's `G-01` and no document was updated; the eighth audit's `H-04` found seven places still saying enforcement was off. And *"see below"* pointed at a section that did not exist in the file |
| `.claude/` — 262 definitions *"+ one coordination Stop guard"* | 262 definitions + **5** hook events | `.claude/settings.json` wires five events. Saying "one Stop hook" tells a reader they are less governed than they are — `CLAUDE.md` §5 records the same correction |
| `npx vitest run  # 68 files / 627 tests` | 80 files / 758 tests | — |
| Rust workspace *"(core, broker, win-broker, win-live, proof, launcher)"* — six | Nine members plus the root host crate | `executor`, `provision` and `audit-signer` were missing from the list |
| `→ …/target/release/brops.exe` | `brops` on Linux, `brops.exe` on Windows | The `.exe` predates the move to Debian. Five canonical documents called this a Windows box until `T-045` |

### 1d. Kept from the previous README because it survived the check

The rewrite preserves all four of the previous README's correction-shaped passages, in substance:
the design-versus-shipped warning; *"do not go looking for `platform_governed_execution_supported()`"*;
*"`.claude/` at the repository root is not the wall"*; and the statement of the third refusal **with
its condition**. Each was re-read at source rather than carried on trust — the third refusal's
condition at `apps/desktop/src-tauri/broker/src/main.rs:256`, and the missing spec symbol confirmed
absent from the tree while `config/spec-conformance.json` records §0.1 as `partial` saying so.

---

## 2. Claims this file does **not** settle

Stated so that a reader does not mistake the tables above for completeness.

- **"The governed chain is proven end to end on Linux and on Windows."** Carried from
  `docs/ARCHITECTURE.md`, which cites the Linux kit (7 services, real uids, a setuid launcher)
  and the Windows one (named pipes, cross-account, distinct service accounts). Not re-measured
  when this file was written.
- **`bridge/` — "one op dispatch (governed turn · governance.read)".** `_OPS` in
  `bridge/engine_sidecar.py` holds exactly one op (`governance.read`) beside the
  `bridge.task-request` envelope; two further §4.10 frames
  (`bridge.governed-turn-output-read.v1`, `bridge.governed-turn-submit.v1`) are dispatched by
  protocol rather than by `op`. The README line is a summary, not an inventory.
- **The desktop binary name** was read out of `Cargo.toml` and `tauri.conf.json`.
  `npx tauri build` was not run.

## 3. Open, and named rather than left to be found

- **Fourteen live files still say `governed_verification_unconfigured()` returns `Some(...)`
  "unconditionally".** Measured by scanning every `.md`/`.json`/`.rs`/`.py` outside
  `node_modules` for the symbol with `unconditional` within 220 characters: 21 hits, of which
  four are in `docs/archive/`, one is a test fixture, one is a dated audit report and one is
  this file. The fourteen that are live statements: `CLAUDE.md`, `START_HERE.md`,
  `NEXT_CHAT.md`, `OWNERS.md`, `MASTER_EXECUTION_ROADMAP.md`, `docs/ARCHITECTURE.md`,
  `docs/SECURITY_MODEL.md`, `docs/OWNER_ACTION_REQUIRED.md`, `docs/OPERATOR_GUIDE.md`,
  `docs/TROUBLESHOOTING.md`, `config/spec-conformance.json`, `config/current_state.json`,
  `config/reachability-declarations.json` — **and `apps/desktop/src-tauri/src/commands.rs`
  itself**, whose doc comment at `:182` says "unconditionally" about a function forty lines
  below it that is a measurement. `T-048` made the change and `PROJECT_STATE.md`'s Phase-1 row
  records it ("the desktop pre-flight MEASURES its five missing inputs now rather than asserting
  them"), so the canon disagrees with itself in fourteen places and with the source in one. The
  README is corrected; those are not, and correcting them was outside the change that produced
  this file.
- **`tools/check_doc_claims.py` is RED when run from inside `.claude/worktrees/<agent>/`** and
  GREEN on the same tree from the main checkout — verified by calling its `main()` with each
  root. The subtree-relative fallback near `:254` keeps a candidate only when
  `"/.claude/worktrees/" not in q.as_posix()`, and `q.as_posix()` is **absolute**, so when the
  root itself is a worktree every candidate is excluded and no citation can resolve. The gate's
  own comment three lines above says it was fixed once for producing "a verdict that depended on
  the machine, not the code"; this is the same defect from the other side. The fix is to test the
  path **relative to `root`**.

---

<div align="center"><sub>menqstudio · OS · a number on the front page is a measurement or it is nothing</sub></div>

## A gate that works in both directions

2026-08-30, at the end of the night that produced this file. `T-055`'s row was written citing
`docs/design/PRODUCTION_HALF_DESIGN.md`, a document that exists on an unmerged branch.
`tools/check_doc_claims.py` refused it:

    RED: TASKS.md references `docs/design/PRODUCTION_HALF_DESIGN.md`, which does not exist.
         A citation to a file nobody filed is how `A-06` happened — twice

Every earlier finding in this file is a claim that was true once and had gone stale. This one is
the opposite: a claim that would become true later. **They are the same defect.** A reader cannot
tell a forward reference from a rotted one — both name a path that does not resolve, and both
teach the reader that citations in this repository need not be checked.

The remedy is the vocabulary the repository already has. `config/negative-matrix.json` says
`blocked_on: <what must exist first>` rather than pointing at what does not exist yet, and the
`T-055` row now says the same thing in prose: the design is *written, not merged; cite it in the
commit that merges it, not before.*

No waiver was written, and none should be. The gate was not weakened, given an exception, or
taught that a forward reference is acceptable — the citation was removed instead. This
repository has waived one of its own rules once before, on 2026-08-14, and three red merges
followed; a second waiver on the same night would have been the worse defect of the two.
