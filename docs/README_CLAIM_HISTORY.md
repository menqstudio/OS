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

---

## 4. Corrected on 2026-09-19, at `main` @ `13027bb`

The front page was redesigned — Armenian first, bilingual parity throughout, committed SVG
artwork under `docs/brand/readme/`. Every number on it was re-measured in the worktree at this
head before it was printed. These are the ones that changed, the ones the redesign removed
rather than restated, and the place where a canonical document's numbers turned out to disagree
with `git`.

### 4a. Stale on the front page — re-measured and corrected

| The README said | It now says | Command / evidence |
| :--- | :--- | :--- |
| Engine test suite **2031** tests | **2133** tests, **97** skipped | `PYTHONUTF8=1 BRO_ENV=ci python -m unittest discover -s engine/tests -t engine/tests -q` → `Ran 2133 tests in 189.762s` · `OK (skipped=97)`. Run in this worktree on **Windows**; the skip count is platform-dependent, so the page names the box it was measured on |
| `tools/` — **32** repository gates | **39** | `ls tools/check_*.py \| wc -l` → `39`. The tree line and the Development section both carried the old number |
| Required contexts on `main` — **33** | **34**, plus **5** `deliberately_excluded` | `gh api repos/menqstudio/OS/branches/main/protection --jq '.required_status_checks.contexts\|length'` → `34`; the `deliberately_excluded` object in `config/required-checks.json` has 5 keys. `PROJECT_STATE.md` records the same 34 — protection was restored from that file after the repository went private and back |
| Negative matrix **29** implemented / **12** blocked / **201** unreviewed | **122** / **54** / **66** | `PYTHONUTF8=1 python tools/check_negative_matrix.py` → `GREEN: 242 matrix cases, all bound -- 122 implemented …, 54 blocked …, 66 unreviewed and frozen. No new debt.` The total, 242, is unchanged; what moved is the split, and `unreviewed` fell from 201 to 66 |
| `.claude/` — 262 definitions + **5** coordination hook events | 262 + **6** | The `hooks` keys of `.claude/settings.json` are `PostToolUse, PreToolUse, SessionStart, Stop, SubagentStart, UserPromptSubmit` — **6**. `CLAUDE.md` has said *six* since `T-019`; the README and this file's own row in `1b` both said five, and both were measured before `PostToolUse` was wired |
| `.github/workflows/` — **8** workflows · **33** contexts | **8** workflow files · `ci.yml` alone defines **21** jobs · **34** contexts | `ls .github/workflows/*.yml \| wc -l` → `8`; `yaml.safe_load` of `.github/workflows/ci.yml` gives `len(jobs) == 21`, and `grep -cE '^  [a-z0-9-]+:$'` on the same file agrees on 21 job keys. The job count is new to the page |
| Frontend **758** tests · 80 files, and `# 80 files / 761 tests` in the Development block | **not printed at all** | Two different numbers for the same suite sat forty lines apart in one file. Neither could be settled here: `npx vitest run` needs `node_modules`, and this worktree has none. The page now says the count is unmeasured here and prints nothing, which is the rule this file exists to enforce |

### 4b. New on the front page — measured here, not carried

| Claim | Command | Printed |
| :--- | :--- | :--- |
| Bridge suite **210** tests | `PYTHONUTF8=1 BRO_ENV=ci python -m unittest discover -s bridge/tests -t bridge/tests -q` | `Ran 210 tests in 0.867s` · `OK` — the same as 2026-08-30, re-run rather than carried |
| Rust workspace **10** crates | `cargo metadata --no-deps --manifest-path apps/desktop/src-tauri/Cargo.toml` | 10 packages: `brops`, `brops-audit-signer`, `brops-broker`, `brops-core`, `brops-executor`, `brops-governed-live`, `brops-launcher`, `brops-provision`, `brops-win-broker`, `brops-win-live` |
| **59** declared controls — **45** `check` · **14** `tool` | `collections.Counter(v['kind'] for v in json.load(open('config/control-invocation.json'))['controls'].values())` | `Counter({'check': 45, 'tool': 14})`, 59 keys in total |
| **262** specialist definitions | `ls .claude/agents/*.md \| wc -l` | `262` — re-measured, not carried |
| `engine/.claude/` wired for **9** hook events | the `hooks` keys of `engine/.claude/settings.json` | `InstructionsLoaded, PostToolUse, PostToolUseFailure, PreToolUse, SessionStart, Stop, SubagentStart, SubagentStop, UserPromptSubmit` — 9 |
| `platform_governed_execution_supported()` is absent from the tree | `grep -rn "fn platform_governed_execution_supported" . --include=*.rs --include=*.py` | No hits. The symbol appears only in two `win-broker` doc comments saying it stays `false`, and in `config/spec-conformance.json`, which records the section as `partial` *because* the function does not exist |
| MenQ foundation tokens — **8**, and **no accent hue** | `gh api repos/menqstudio/MenQ-Standard/contents/platforms/design/implementation/packages/design-tokens/source/tokens.json` | `"decision": "D-025"`, 8 tokens: `#ffffff`, `#0b0d10`, `8px`, `12px`, and four semantic/component aliases of those four. No colour token beyond the two neutrals — which is why the page says the blue accent is **this repository's own**, from `apps/desktop/src/theme/tokens.css`, and not MenQ's |

### 4c. The canon disagreed with `git`, and `git` won

`PROJECT_STATE.md` says, under **Standing risks**: *"**74 pull requests, 240 files and 46,402
inserted lines** have merged since, none independently confirmed — measured `5cf9b8c..main`."*
That sentence was true when it was written, and it is exactly the shape of claim this file exists
for. Measured again at this head:

    git log --format=%s 5cf9b8c..HEAD | grep -oE "\(#[0-9]+\)$" | sort -u | wc -l
    # 75

    git diff --shortstat 5cf9b8c..HEAD
    # 240 files changed, 46471 insertions(+), 13411 deletions(-)

The gap is one commit. `PROJECT_STATE.md` was measured at `7703bde`; `13027bb` — PR #236, which
landed after it — is the 75th pull request and 69 of the inserted lines. Re-measured at the
parent, `git diff --shortstat 5cf9b8c..7703bde` prints exactly `46402`, so the canonical document
is not wrong about the tree it measured. It is one merge behind, and a front page that copied it
would have been wrong about the tree a reader is looking at. **The README prints 75 / 240 /
46,471 and names the head it measured.**

`PROJECT_STATE.md` was deliberately left alone. Editing a canonical document is a change with its
own update law and its own gates, and it belongs to the session that next moves the head — not to
a README redesign. It is named here so that session finds it instead of re-deriving it.

### 4d. One number the redesign could not settle

`ci.yml` **jobs**. The brief for this redesign gave **23**. `yaml.safe_load` of
`.github/workflows/ci.yml` at `13027bb` gives **21**, and `grep -cE '^  [a-z0-9-]+:$'` on the same
file agrees at 21 job keys. Two independent counts of one file say 21, so **21** is what the page
prints, and it is described as *jobs in `ci.yml`* rather than as *checks*. The likeliest source of
23 is a count of reported **contexts** rather than job definitions — `trust-provisioning` is a
two-OS matrix and reports twice — but that reading was not established here, so the page does not
state it. `git show 5cf9b8c:.github/workflows/ci.yml` parses to 18 jobs, which rules out a stale
reading of an older tree.

### 4e. Kept, because it survived the check

The redesign preserves, in substance, every correction-shaped passage the previous README carried:
the design-versus-shipped warning; the absent spec symbol; *"`.claude/` at the repository root is
not the wall"*; the first refusal stated **with its mechanism** and the third **with its
condition**; and `unreviewed` named as *not a pass*. Each was re-read at source — the three
refusals found at `apps/desktop/src-tauri/src/commands.rs:1375`,
`apps/desktop/src-tauri/src/governed_turn.rs:230` and
`apps/desktop/src-tauri/broker/src/main.rs:256` — rather than carried on trust.

What changed is that the honesty is now in the artwork as well as the prose. The banner draws the
last hop barred and the production state locked; the gate figure colours **nothing** green,
because nothing on it is a pass; and the negative-matrix bar hatches `unreviewed` and prints
*unreviewed is not a pass* beside it. A reader who looks only at the pictures still cannot come
away believing this ships.

### 4f. `main` moved while the page was being written, and the page did not chase it

The redesign started with `origin/main` at `13027bb`. By the time the gates were re-run, two more
pull requests had landed and `origin/main` was `c197b97` — `#237` and `#238`, both `T-062`, which
between them rewrote `config/negative-matrix.json` and added `engine/tests/test_governed_acceptance.py`.

Three of the page's rows are therefore already behind the tip. Measured at `c197b97`, from this
worktree, without checking it out:

| Row | At `13027bb`, which the page prints | At `c197b97` | Command |
| :--- | :--- | :--- | :--- |
| Negative matrix | 122 implemented · 54 blocked · 66 unreviewed | **130** · 54 · **58** | `git show c197b97:config/negative-matrix.json`, counting `status` over the 242 cases |
| Pull requests since `5cf9b8c` | 75 | **77** | `git log --format=%s 5cf9b8c..c197b97 \| grep -oE "\(#[0-9]+\)$" \| sort -u \| wc -l` |
| Inserted lines since `5cf9b8c` | 46,471 (240 files) | **46,766** (240 files) | `git diff --shortstat 5cf9b8c..c197b97` |

The engine suite count at `c197b97` was **not** measured: the new acceptance-test file is only in
that tree, and running the suite would have meant checking out a head this branch is not based on.
It is therefore not printed anywhere, here or on the page.

**The page was not updated to the tip, on purpose.** Every number on it is measured at one named
head, `13027bb`, and the page says which head in its metadata block and again above the table. A
page whose rows come from a single commit is internally consistent and a reader can re-run it; a
page that mixes a matrix count from one head with a test count from another cannot be checked
against anything. Whoever lands this should re-measure at the head it lands on — that is the
review trigger the page states — and add the row here rather than replacing this one.

### 4g. The head moved under the page before it merged, and §4f said to re-measure

The six corrections above were measured at `13027bb`. Twenty-one pull requests merged while
this page was being drawn, so at `c197b97` — the head it is opening against — four of its
figures were already stale and one had never been right at any head. Re-measured, with the
command each row prints:

| Claim | Said | Measured at `c197b97` | Command |
| :--- | ---: | ---: | :--- |
| Engine test suite | 2133 | **2141** | `BRO_ENV=ci python -m unittest discover -s engine/tests -t engine/tests -q` |
| `implemented` in the matrix | 122 | **130** | `python -c "import collections,json; print(collections.Counter(c['status'] for c in json.load(open('config/negative-matrix.json',encoding='utf-8'))['cases'].values()))"` |
| `unreviewed` in the matrix | 66 | **58** | the same command — it prints all three |
| Pull requests since `5cf9b8c` | 75 | **77** | `git log --format=%s 5cf9b8c..HEAD \| grep -oE "\(#[0-9]+\)$" \| sort -u \| wc -l` |
| Inserted lines since `5cf9b8c` | 46,471 | **46,766** | `git diff --shortstat 5cf9b8c..HEAD` |
| Declared controls, split | 59 — 45 check · 14 tool | 59 — **39 check · 20 tool** | `ls tools/check_*.py \| wc -l` · `ls engine/tools/*.py \| wc -l` |

The last row is the only one that is not staleness. The total, 59, was right; the split was
not, at `13027bb` or at any other head. `config/control-invocation.json` declares 39 entries
under `tools/` and 20 under `engine/tools/`, and 39 + 20 is 59 — so a wrong split summed to a
right total, which is exactly the shape a reader cannot catch. The row now carries the
commands that print the split rather than asking to be believed — and a glob is a fair
way to print it only because the two halves of that file were measured to be SET-equal
to what the globs list, in both directions, with nothing declared that is not on disk
and nothing on disk that is not declared. Equal counts would not have been enough.

`blocked` (54), `total` (242), the bridge suite (210), the Rust crate count (10), the gate
scripts (39), the workflow files (8), the `ci.yml` job count (21), the required contexts (34,
+5 excluded), the specialist definitions (262), the extracted schemas (5) and both hook-event
counts (9 under `engine/.claude/`, 6 under `.claude/`) were each re-measured at `c197b97` and
were unchanged. They are listed here because "I checked and it had not moved" and "I did not
check" are different statements, and only one of them is written down by default.

The artwork carries the same numbers, so `docs/brand/readme/verification-{light,dark}.svg` was
re-drawn with them. The bar is to scale: 130 / 54 / 58 of 242 across the same 1120px track is
602 / 250 / 268 px, which moved both segment boundaries, the three captions, the plate under
the hatched label, the four explanation columns and the `unreviewed is not a pass` box. The
hatch that marks `unreviewed` as an unknown lost one diagonal, because the band it covers got
narrower. A picture drawn to scale that keeps its old geometry while its labels change is a
lie no reader can see, which is why the geometry is recomputed here and not eyeballed.

**Why this file keeps needing a new section.** No gate reads `README.md`. Measured two ways:
`grep -ln 'README\.md' tools/check_*.py` returns nothing — not one of the 39 gates opens the
page — and `config/canonical-read-manifest.json` names 14 documents, of which `README.md` is not
one, so `check_doc_claims` never sees it. That gate is the one built for exactly this class of
error, and it is not idle: it is red on this box right now over two stale numbers in
`config/toolchain.json`, which is the same defect in a file it does watch. The front page is the
most-read file in this repository and the only widely-read one that nothing refuses to merge.

This document is the manual stand-in for that gate. It is why six numbers were caught today, and
it is also why they had to be caught by a person re-running commands instead of by a check that
goes red on its own — a stand-in that depends on whoever lands the change remembering to look.
The fix is to put the page's countable claims under `check_doc_claims` the way
`config/toolchain.json` already is, which is a gate change with its own tests and its own
mutation proof, not a rider on a redesign. Naming it here is not the same as doing it.

> **Closed.** Everything above stayed as written, because it is the reason the next
> section exists. What changed, and what is still not covered, is §6.

## 5. Re-measured at each landing head

§4f set the rule and §4g named why it is needed: no gate reads `README.md`, so a pull request that
moves a counted thing leaves the front page stale, and only a person re-measuring catches it. Done
as prose, that would add a section per pull request and bury §1–§4 — the corrections that taught
something — under arithmetic. So routine re-measurement lands here, one row per head, and prose
above is kept for a number that was **wrong** rather than merely older.

Read the difference: a row in this table is a figure that moved because the repository moved. A
section above is a figure that was false when written. §4g's control split was the second kind.

| Landed at | What moved | Measured |
| :--- | :--- | :--- |
| `235acc1` | matrix `implemented` 130 → **132**, `unreviewed` 58 → **56** — `NM-CRASH-06` and `NM-TIME-12` bound | `python -c "import collections,json; print(collections.Counter(c['status'] for c in json.load(open('config/negative-matrix.json',encoding='utf-8'))['cases'].values()))"` |
| `235acc1` | engine suite 2141 → **2143** (97 skipped) | `BRO_ENV=ci python -m unittest discover -s engine/tests -t engine/tests -q` |
| `235acc1` | 77 → **79** pull requests, 240 → **248** files, 46,766 → **47,663** inserted lines since `5cf9b8c` | `git log --format=%s 5cf9b8c..HEAD \| grep -oE "\(#[0-9]+\)$" \| sort -u \| wc -l` and `git diff --shortstat 5cf9b8c..HEAD` |

**When to write the row, and it is not the same pull request.** These three rows first went in
naming `45ea71e`, the base their branch was written on, and they landed at `235acc1`. The same
mistake put *Measured at `main` @ `45ea71e`* at the top of a page printing 132 / 54 / 56 and 2143 —
the values at `235acc1`. At `45ea71e` they were 130 / 54 / 58 and 2141, so the page named a head at
which two of its own rows were false, and they were the two a reader would most likely check.

That is a rule, not a slip. **A change that moves a counted number cannot name a head where its own
numbers hold, because that head does not exist until it merges.** Naming the base is wrong for
exactly the rows the change touched. So the page is re-trued in the pull request AFTER the one that
moved the number, against the head that actually landed — which is what this column has always
said, and what it was not filled with. `Landed at` means landed.

| Landed at | What moved | Measured |
| :--- | :--- | :--- |
| `235acc1` | the three rows above were re-headed from `45ea71e`, and the page's own *Measured at* with them; PRs since `5cf9b8c` 78 → **79**, inserted lines 47,550 → **47,663** | `git rev-parse --short HEAD` on `main`, and `git diff --shortstat 5cf9b8c..HEAD` |
| `a57fd86` | matrix `implemented` 132 → **133**, `unreviewed` 56 → **55** — `NM-CRASH-01` bound | the `collections.Counter` one-liner above |
| `a57fd86` | engine suite 2143 → **2144** (97 skipped) | `BRO_ENV=ci python -m unittest discover -s engine/tests -t engine/tests -q` |
| `a57fd86` | 79 → **81** pull requests, 47,663 → **48,103** inserted lines since `5cf9b8c`; 248 files unchanged | `git diff --shortstat 5cf9b8c..HEAD` |
| `6c59a67` | matrix `implemented` 133 → **144**, `unreviewed` 55 → **44** — `NM-CRASH-12/13/14`, `NM-TCB-01/03/08/21`, `NM-TERM-02`, `NM-SCOPE-06/08`, `NM-MAN-12` bound across three landings | the `collections.Counter` one-liner above |
| `6c59a67` | engine suite 2144 → **2148** (97 skipped) | `BRO_ENV=ci python -m unittest discover -s engine/tests -t engine/tests -q` |
| `6c59a67` | 81 → **85** pull requests, 248 → **249** files, 48,103 → **48,768** inserted lines since `5cf9b8c` | `git diff --shortstat 5cf9b8c..HEAD` |
| `830fcec` | matrix `implemented` 144 → **150**, `unreviewed` 44 → **38** — `NM-SCOPE-04/06`, `NM-TERM-02/04/08`, `NM-MAN-12`, `NM-FS-05`, `NM-CONC-07`, `NM-XBIND-03` bound across four landings; **more than half the matrix is now bound** | the `collections.Counter` one-liner above |
| `830fcec` | engine suite 2148 → **2152** (97 skipped) | `BRO_ENV=ci python -m unittest discover -s engine/tests -t engine/tests -q` |
| `830fcec` | 85 → **89** pull requests, 249 → **257** files, 48,768 → **49,977** inserted lines since `5cf9b8c` | `git diff --shortstat 5cf9b8c..HEAD` |
| `75fca65` | gate scripts 39 → **40**, declared controls 59 → **60** (40 check · 20 tool) — `tools/check_artwork_geometry.py`, the gate §9 said did not exist | `ls tools/check_*.py \| wc -l` and `ls engine/tools/*.py \| wc -l`, each set-equal to its half of `config/control-invocation.json` (60 entries) |
| `75fca65` | 89 → **91** pull requests, 257 → **261** files, 49,977 → **50,787** inserted lines since `5cf9b8c` | `git diff --shortstat 5cf9b8c..HEAD` |
| `a94513e` | **Phase 2 closed, 11/11** — the roadmap figure said *"PHASES 1–10 — ALL PARTLY BUILT"* and seven of eleven now have every box ticked; the sheet draws each phase's own count and its alt text was re-written with it | `grep -c '^- \[x\]' docs/roadmap/phase-*.md` against `grep -c '^- \[ \]'` |
| `a94513e` | 91 → **96** pull requests, 261 → **281** files, 50,787 → **53,749** inserted lines since `5cf9b8c` | `git diff --shortstat 5cf9b8c..HEAD` |
| `9cc4d2c` | engine suite 2205 → **2243**, and the SKIP COUNT taken out of four documents rather than re-guessed — one head skips **14 / 82 / 97** in three environments, so it is not a property of the code or even of the platform | `BRO_ENV=ci python -m unittest discover -s engine/tests -t engine/tests -q`, run on the ubuntu runner, the windows runner and the Builder's box |
| `9cc4d2c` | frontend 781 → **794** tests, 82 → **84** files. `CLAUDE.md` was further behind still, at 764 / 80, and its engine line at 2124 / 10 skipped | `cd apps/desktop && npm ci && npm test` |
| `9cc4d2c` | the counted claims are **declared** now — `config/counted-claims.json`, ten of them | `python tools/check_doc_claims.py` |

**Half of this table is now a gate, and the half that is not says why.** §4g named the gap and this
section was the workaround: no gate read the counted claims, so a person had to re-measure. That
lasted four audit rounds. `config/counted-claims.json` closes the half a gate can close — five claims
are RECOUNTED from the tree on every run (gate scripts, workflow files, specialist definitions,
frontend test FILES, `ci.yml` jobs), and a wrong number in a cited document is RED by name. The other
five need a suite to RUN, which a gate must not do, so what is enforced for them is provenance: an
environment, a date and a head. `check_doc_claims`'s own docstring had asked for exactly this file,
while carrying two stale numbers inside the sentence that asked.

This row is also the rule above working as intended. The numbers moved across `#272`–`#276`; none of
those pull requests could name a head at which its own figures held, so the front page was left alone
and re-trued here, against `9cc4d2c` — the head that actually landed.

**Three landings paid at once, which is what the rule is for.** #244, #245 and #246 each moved a counted number and each deliberately left the page alone. Re-truing after every one would have meant three pull requests whose only content was arithmetic; the rule says name the head the numbers hold at, and `6c59a67` is the head all three hold at. The artwork in §8 landed in the same commit because it belongs to the same page.

**The cadence rule, followed on purpose this time.** T-075 moved the matrix split and the engine
count and deliberately left the page alone, because a change that moves a counted number cannot name
a head where its own numbers hold. This change re-trues the page against `a57fd86` — the head T-075
actually landed at — and the three rows above are what that produced. The rule now has one clean
pass behind it rather than only the mistake that wrote it.

Unchanged at this head, and checked rather than assumed: `blocked` 54, total 242, bridge 210,
Rust crates 10, gate scripts 39, declared controls 59 (39 check · 20 tool), workflow files 8,
`ci.yml` jobs 21, required contexts 34 (+5 excluded), specialist definitions 262, extracted
schemas 5, hook events 9 under `engine/.claude/` and 6 under `.claude/`.

The artwork moved with the numbers, because the bar is to scale: 132 / 54 / 56 of 242 over the
same 1120px track is 611 / 250 / 259 px, against 602 / 250 / 268 at the previous head. Both
segment boundaries, the three captions, the plate under the hatched label, four explanation
columns and the `unreviewed is not a pass` box were placed from that arithmetic rather than by
eye. The hatch kept nine diagonals: its band narrowed by 9px, not enough to drop one.

## 6. The gate §4g asked for

`check_doc_claims` now reads `README.md` and this file. It did not have to learn a new kind of
claim to do it — the three it already settles are the three the front page makes, so this is a
question of SCOPE, and the scope was the defect.

**How.** Being *checked* and being *canonical* were one property, and the front page fell between
them. `config/canonical-read-manifest.json` answers "what must every session read before it can
start" and carries a byte ceiling per path, because that text is pasted into a session. Nobody
needs the README to start, and it is 33 KB. So it was in no list, and therefore in no gate. The
two properties are now separate: `ALSO_CHECKED` in `tools/check_doc_claims.py` names documents
whose checkable claims are checked and which no session reads. Adding one costs a session nothing.

**Measured, at `235acc1`.** The gate's own verdict line, before and after:

```
before   GREEN: canonical claims check out; 145 paths, 42 shas, 107 tickets, 8 versions
after    GREEN: canonical claims check out; 204 paths, 49 shas, 118 tickets, 8 versions;
                2 of 2 also-checked document(s) read
```

+59 paths, +7 commit hashes, +11 ticket ids: 77 referents that resolved on trust yesterday and are
resolved by a check today. Versions stayed at 8 — neither document claims a toolchain version.

**Proved by breaking it, not by the green.** A gate that is green the moment it is wired proves
nothing, so one claim of each kind was broken in the real `README.md` and the real gate was run:

| Mutation in `README.md` | Verdict |
| :--- | :--- |
| `./docs/brand/` → `./docs/no-such-directory/` | RED — "README.md: references `./docs/no-such-directory/`, which does not exist" |
| `5cf9b8c` → a 40-hex string that resolves to nothing | RED — "README.md: names … which is not an object in this repository" |
| `T-048` → a ticket id on no board | RED — "README.md: names …, which is in no task board, ledger or archive" |

And the control, which matters more than the three: with `ALSO_CHECKED` emptied and the same
`README.md` still broken, the gate goes back to naming nothing in it. The red was arriving from
this change and not from somewhere else.

**One asymmetry, deliberate.** An absent `ALSO_CHECKED` document is not RED, while a path the read
manifest names and the disk lacks is. The manifest is a contract about the session read set; this
tuple is not a contract, it is a scope. `main(root)` also runs over synthetic roots in this gate's
own tests, where a missing README is a defect of nothing — requiring it there reported
"README.md: not on disk" in thirteen tests whose subject was something else. Absence is not
*silent*, though: the verdict prints `2 of 2 also-checked document(s) read`, and
`test_the_real_repository_has_every_also_checked_document` fails by name if either file leaves the
tree. A silent skip would hand back the guarantee this section is about.

**What this still does not check.** The countable claims — 2143 engine tests, 39 gate scripts, 262
specialist definitions, 132 / 54 / 56 — remain unchecked by any gate. Those need a declaration
mapping each claim to the command that prints it, and a runner willing to execute suites inside a
gate; that is a larger design than this, and §5 is still the place routine drift gets recorded by
hand. So: the class that produced §4g's *false* row — a path, a hash, a ticket — is closed. The
class that produced its five *stale* rows is not.

## 7. Three suites the page said it had not measured

This is not a §5 row and the difference matters. §5 is for a figure that moved because the repository
moved; §1–§4 are for a figure that was false. These three were neither — they were **absent**, and
the page said so in a note:

> The cockpit frontend (`vitest`) count is **not measured here**, so it is not printed.
> `npx vitest run` needs `node_modules`, which this checkout does not have, and copying a number
> you did not measure is exactly what `docs/README_CLAIM_HISTORY.md` exists to stop.

That was correct, and it stayed correct for as long as nobody did the install. `npm ci` then ran from
the committed `package-lock.json` (221 packages, 33 seconds) and `npx playwright install chromium`
fetched the browser, so all three suites were run at `a57fd86`:

| Suite | Measured | Command |
| :--- | ---: | :--- |
| Cockpit frontend (jsdom) | **764** tests, 80 files | `cd apps/desktop && npm ci && npm test` |
| Cockpit accessibility (axe) | **59** tests, 3 files | `cd apps/desktop && npm ci && npm run test:a11y` |
| Cockpit in real Chromium | **433** tests, 6 files | `cd apps/desktop && npm ci && npx playwright install chromium && npm run test:browser` |

Each command **includes the install**, and that is deliberate rather than verbose. A fresh checkout
has no `node_modules` — it is not committed and should not be — so a command without the install is
one a reader cannot run, and "run the command rather than trusting the number" is the only rule this
page has. The old note was right that an unmeasured number must not be printed; it did not follow
that the measurement was impossible, only that nobody had paid for it.

## 8. Three figures added, and a verification claim that was not true

Four sections of this page had artwork and six did not. Three of the six now do — *Bro, and who may do
what*, *What OS is*, and *Roadmap* — and **nothing was removed to make room**: each figure sits above
the prose it illustrates, in the same `<picture>` + `prefers-color-scheme` shape as the existing four,
and every paragraph, table and sentence that was there still is. That was checked mechanically, not
assumed: no line present before the edit is absent after it.

**What the figures are allowed to say.** Only what the section already says. Two designers worked each
section from the section's own text, and the brief put one rule above aesthetics: where the text says
something is not enforced or does not exist, the picture must say so at least as loudly as it says the
parts that work. That is why *Bro, and who may do what* has three different visual grammars for three
different answers — nested rings for the capability tier that is enforced, a severed link for the path
that travels as text, and an empty slot outside the bracket for the network axis that does not exist —
and why the *What OS is* sheet carries no green at all, with a footer saying why: the section makes no
verified claim, only a required one.

**A false verification claim, caught inside the submission.** The brief required a light/dark pair.
Neither designer shipped a dark sheet. One of them then wrote, in the field reserved for its own
honesty check:

> Verified: both sheets parse with `xml.dom.minidom`, are byte-identical apart from colour literals
> and the desc line … both were rendered at 1200×672 and read correctly in each theme.

There was no second sheet to parse, to compare, or to render. Its other measured claims did check out
— every coordinate a multiple of four, the widest text run ending near x=1103 — which is what makes the
false one worth recording rather than dismissing: it arrived beside true ones, in a submission whose
whole subject was not overstating things. The judging pass caught it, named it as the failure mode this
repository is built around, and produced the missing pairs.

**And then nothing was trusted anyway.** Every sheet that landed was checked here, at `6c59a67`, on nine
properties: it parses; its header carries `viewBox 0 0 1200 H` with a matching `height`; every colour
literal is on the token table; the light and dark sheets differ **only** in colour literals and the one
`<desc>` line; every light colour maps to exactly one dark colour by that table; no `id` is referenced
that is not defined; no content geometry passes x=1160; no text run passes x=1160 under a deliberately
pessimistic advance table (Armenian counted wider than Latin, since these sheets are bilingual
everywhere and Armenian is what a Latin-only estimate would under-count); and the bytes are LF with no
control characters.

Two of those checks flagged something and both were **my** error, not the sheets': a `url(#…)` fragment
reference to a `clipPath` defined in the same file is not an external reference, and the full-bleed
ground rect is supposed to span all 1200px. Recorded because a checker that cries wolf is the fastest
way to teach someone to ignore it.

What none of that establishes: whether the pictures are *good*. Nine mechanical properties and a traced
fact-for-fact reading say they are true, on-palette, and legible at the sizes they will be read at.
Whether they are worth looking at is a judgement, and it is the Owner's.

## 9. Four landings paid at once, and the prose under the bar was still tied to the bar

§5's rule is that a change which *moves* a counted number cannot name a head where its own numbers hold,
because that head does not exist until it merges. So the page is re-trued in the pull request **after**,
against the head that actually landed, and several landings can be paid at once. Four were owed here:
`#247`, `#248`, `#249` and `#250` each moved a number and each deliberately deferred the page. They are
paid in §5 against `830fcec` — matrix `implemented` 144 → **150** and `unreviewed` 44 → **38**, the
engine suite 2148 → **2152**, and 85 → **89** pull requests / 249 → **257** files / 48,768 → **49,977**
inserted lines since the ninth audit's head.

**The board hit its ceiling on the way.** Adding T-084's own row took `TASKS.md` to 7,111 bytes against
a 7,000 ceiling, and `check_canon_budget`'s remedy text says which number moves: not the ceiling. `T-072`
— merged in `#232`, never independently confirmed — is now verbatim in
[`docs/archive/TASKS_ARCHIVE_2026-09.md`](archive/TASKS_ARCHIVE_2026-09.md) as its thirteenth row, and
the live one-line statement on the board names it with the other twelve. The board is 6,920 bytes.

### 9a. Two defects in the figure, one of them mine today and one older than this pull request

The verification sheet's bar is drawn to scale, so its segment edges move every time a row is bound. Two
things beside the bar were positioned *from* those edges, and both broke when `unreviewed` fell to 38:

| What | How it was placed | What that did at a 176 px band |
| :--- | :--- | :--- |
| the label plate behind `unreviewed · չստուգված` | a fixed **200 px**, centred on the band | 972 → 1172 against a band of 984 → 1160: 12 px past the rounded end, and 12 px into the amber band beside it |
| the four-line `unreviewed` paragraph | left-aligned at the band's **left edge** | two lines ended at **1204.2** and **1227.8** — past the 1200 canvas, so clipped |

The plate is mine, today: a fixed width is correct only while the band is wider than it, and the band had
never been narrower than 200 px before. The paragraph is older. At the head this page last named it
already ended at **1176.2** and **1199.8** against a 1160 track — overhanging, but inside the canvas, so
nothing looked broken. This re-true turned a pre-existing overhang into an actual clip.

**Why §8's nine checks did not catch it.** They were run on the sheets that *landed* in `#247` — the three
pairs that pull request added. The verification pair is older than `#247`, so the text-advance check had
never been pointed at it. It is now: all **14** sheets in `docs/brand/readme/` measure `0 text run(s)
past x=1160` under the pessimistic advance table.

### 9b. The first fix was correct and lasted two rows, which is how the layout changed

Anchoring the paragraph to the track's right edge — 1160 whatever the numbers do — fixed the clipping.
Then the gap to the *blocked* column was measured rather than eyeballed: **31.3 px**, and the blocked
column marches right at ~4.6 px per bound row, because it is left-aligned at a band whose left edge is
`40 + round(implemented / 242 × 1120)`. Two more bound rows and the two columns touch. A layout with two
rows of headroom is not a fix.

So the prose came off the bar entirely. The three paragraphs now sit on a **fixed grid** at 40 / 440 /
800, each indented 16 px behind a 4 px rule in its own band's colour, and the `unreviewed is not a pass`
chip follows its column. **Nothing was removed**: every line is verbatim where it was, the bar is still
to scale, and the tie between a paragraph and its segment is a colour instead of an x coordinate that has
to keep up with the numbers.

**Measured, four ways:**

- `plate()` walked over every band width from 40 to 600 px — **no plate escapes its band**. At 204 px, the
  width the sheet shipped with, it returns exactly the hand-drawn `958 / 200`: the helper agrees with the
  drawing where the drawing was right, which is the only reason to trust it where the drawing was wrong.
- the tightest column gap is **183.3 px** and it is now *independent of the split* — drawing 120 / 54 / 68
  moves the green band from 694 px to 555 px and the gap prints 183.3 px at both. That is the property the
  old layout lacked, stated as a number rather than as an intention.
- both sheets survive a **byte-for-byte round trip**: driven to 120 / 54 / 68 and back to 150 / 54 / 38,
  7,643 → 8,127 → 7,643 bytes, identical. An idempotent run prints "already at 150 / 54 / 38" and proves
  nothing; this covers the bar paths, the dividers, the plate, the hatch and the in-band numbers.
- the pair still differs **only** in colour literals and the one `<desc>` line, and every rule colour was
  already in its own sheet — the palette gained nothing.

The generator refuses to write a sheet whose columns come within 24 px of each other, or whose paragraph
lines have drifted back onto the bands, and it checks both on every run — including the runs where no
number moved, which is when a layout regression would otherwise pass unseen.

**What none of this is.** A committed gate. Everything above is a scratchpad tool of mine; no
`tools/check_*.py` reads these sheets, so the next re-true is protected by a script that lives outside
the repository. A gate under `tools/` that reads them — parse, palette, pair
parity, right edges, column gaps — is the honest follow-up. It does not exist yet, and until it does the
front page's artwork is checked by me rather than by the repository — **§10 is that gate, and it found a defect on its first run.** Naming it here as a filename was
itself refused by `check_doc_claims`: *"references … which does not exist. A citation to a file nobody
filed is how `A-06` happened — twice"*. The gate was right, so the sentence changed.

### 9c. The gate self-test that carried the count it was checking

Carrying `T-072` off the board turned `Coordination · docs consistency gate` **red** on the first run of
this pull request, in a test written one pull request earlier:

```
FAIL: test_the_archive_holds_the_rows_and_not_a_summary_of_them
AssertionError: 13 != 12 : the archive does not hold twelve rows
```

`self.assertEqual(len(rows), 12)`. The archive was right, the board was right, and the test held a
constant — the same defect shape as §5's cadence rule, one directory over: **a number written in two
places agrees only until one of them moves.** The remedy is not a 13.

Both tests in that class now read the count and the ids off the board's own one-line statement, so the
line that *replaced* the rows is checked against the rows it replaced — in both directions. That is
strictly more than the constant could do, and it is proved by breaking the real files rather than by the
green:

| Mutation | Which named test died, by assertion |
| :--- | :--- |
| the board claims **14** merged rows and lists 13 | `test_the_board_line_names_as_many_rows_as_it_claims` |
| the board drops an id it carried off | the count test **and** `test_the_archive_holds_the_rows_and_not_a_summary_of_them` |
| the archive holds a row the board does not name | `test_the_archive_holds_the_rows_and_not_a_summary_of_them` |

The third is the one the constant never had: an archive that grows a row nobody carried off is now a
failure, not a silence. And the catch is recorded here rather than amended away — the first commit on
this branch is the one that broke it.

## 10. The gate §9 said did not exist

§9 ended by naming the gap rather than a filename: *"A gate under `tools/` that reads them — parse,
palette, pair parity, right edges, column gaps — is the honest follow-up. It does not exist yet, and
until it does the front page's artwork is checked by me rather than by the repository."*
`tools/check_artwork_geometry.py` is that gate, wired into `Cockpit · design tokens (drift + contrast)`
— a **required** context that already owns the four colour gates — and registered in
`config/control-invocation.json`, which refused it on arrival: *"exists on disk and has no entry …
The population is DERIVED, so a new control cannot be added without saying what its failure prevents"*.

**Eleven rules, and the reason each one is a rule** is in the gate's own docstring. The short form: the
sheet parses; the canvas is 1200 wide with a `height` that agrees with the `viewBox`; every light sheet
has its dark twin; the twins are identical apart from colour literals and the one `<desc>` line; every
light→dark colour pair is declared; every literal is on the token table; every `url(#…)` resolves; no
text run passes x=1160; no two runs sharing a baseline overlap; LF bytes with no BOM and no C0
controls; and no sheet is an orphan the README never shows.

### 10a. It found a defect on its first run, by counting what nobody had counted

Across the seven pairs there are **13** distinct light→dark colour pairs. Ten are exactly one token's
light and dark value in `apps/desktop/src/theme/tokens.css`. Two are the sheets' own, declared in the
gate with their reasons — the MenQ grounds `#ffffff → #0b0d10` (decision `D-025`, 51 uses) and the
sheets' panel `#f5f6f8 → #14171f` (61 uses).

The thirteenth was `#f5f6f8 → #1b1f2a`, used **once**, on the closing banner of `authority-dark.svg`,
where every other panel in all seven pairs uses `#14171f`. In light that banner is the same colour as
every other panel; in dark it was a step lighter. So the dark sheet made a distinction the light sheet
does not — which is exactly the asymmetry the twin rule exists to catch, one element below the
resolution the twin rule works at. Counting found it in a second; the sheet had been looked at by two
designers, a judging pass and nine mechanical checks. It is a one-literal fix in this change, and the
gate goes red again if it is reverted — measured, both directions.

### 10b. Two rules were wrong before they were right, and the synthetic tests are why

The first version of the colour rule demanded a **bijection**: one light literal, one dark literal. It
reported two sheets, and both reports were wrong. A light theme may legitimately use white for both the
page ground and an elevated card, and the dark theme then separates them — that is
`--menq-color-elevated` working, and `architecture-*.svg` does exactly it. The rule now asks whether
each pair is **declared**, which catches what the bijection was reaching for and nothing it was wrong
about.

The second was found by the gate's own self-test rather than by the repository: colour literals inside
`<desc>` were feeding the positional pairing. The `<desc>` line is the one line the twin rule *allows*
to differ, and both sheets name their ground in it — so rewording it in one theme would have shifted
every pair after it and reported drift that was not there. The synthetic test that reworded a dark
`<desc>` failed, which is the only reason that is not a defect shipping today. §8's lesson, earned a
second time: a checker that cries wolf is the fastest way to teach someone to ignore it.

### 10c. What this gate still does not do, stated rather than implied

It does not judge whether a figure is *good*, or whether it says what its section says — §8's
fact-for-fact reading was a person's work and stays a person's work. It does not check the **numbers**
inside a drawing: the verification sheet draws `40 gate scripts` because this change counted them, and
nothing would refuse a `39` there tomorrow. And its text metrics are an **estimate** — a deliberately
pessimistic advance table, not a font engine — so it can only ever be wrong in the safe direction.

Rule 9's floor is **zero**, and that is measured rather than chosen: across the 14 sheets the tightest
gap between two runs on one baseline is 3.9 px, in the roadmap pair where the mono advance is
over-estimated most. Any floor above zero would be red on arrival on artwork nobody has complained
about. Overlap is a defect; breathing room is a judgement, and a gate that argues about judgement gets
ignored.

**Owed, by §5's own rule.** This change moves two counted claims — gate scripts 39 → **40** and declared
controls 59 → **60** (`40 check · 20 tool`) — so the page cannot name a head where its own numbers hold.
The front page carries the new numbers; its *Measured at* line and §5's rows are paid in the pull
request after this one, against the head this one lands at.

### 10d. The gate's first CI run failed, on the gate

`Tools · gate self-tests on Windows (python)` went red on this branch's first run, in the gate's own
real-repository test:

```
FAIL: test_the_sheets_this_repository_ships_pass_every_rule
AssertionError: Lists differ: ['docs/brand/readme/architecture-dark.svg: …'] != []
```

Fourteen sheets, all reported for rule 10 — CRLF line endings. Every one of them is LF in this
repository, and green locally, twice. **The rule was measuring git's configuration rather than the
commit.** `.gitattributes` pinned `*.sh` and the hooks to LF and nothing else; this box has
`core.autocrlf=input`, so a checkout leaves LF alone, and `windows-latest` defaults to `true`, so its
checkout converts every text file on the way to disk. The gate reads the bytes it finds in the working
tree, so on that runner it found CRLF and said so — correctly, about the wrong thing.

Reproduced locally rather than reasoned about, by cloning the pushed head the way the runner does:

```
git -c core.autocrlf=true clone -b t085/artwork-geometry-gate …
  hero-light.svg in that clone: CRLF pairs = 49
```

**The fix is not to drop the rule.** `.gitattributes` now carries `*.svg text eol=lf`, with the
measurement above as its reason, so the working tree is LF wherever it is checked out and the property
the gate checks is true rather than local. The committed bytes were already LF, so nothing's content
changed. The gate's message names the attribute, so a reader who deletes the line is told where the
red came from.

The order here is the point: a gate whose first run is also its first green run has not been tested on
the platform it will fail on. This one failed on arrival, on a job that is **not** a required context —
which is exactly what that job is for, and the reason `config/required-checks.json` still keeps it out
of `contexts` with a written reason.
