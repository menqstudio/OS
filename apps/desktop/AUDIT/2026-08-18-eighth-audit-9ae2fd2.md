# Eighth independent audit — `main` @ `9ae2fd2`

**Verdict: RED.**

> **Filed by the Builder, verbatim from the auditor's reply, 2026-08-18.** The only additions are
> this box and the heading structure. Nothing is softened, reordered or answered here — remediation
> is tracked in `AUDIT_LEDGER.md` and `TASKS.md`, not inside the report.
>
> **This round produced the first independent confirmations this ledger has carried since the
> fourth.** 27 of 29 marks earn ✅. Two are REOPENED: `A-06` and `A-09`.

| | |
|---|---|
| Head | `9ae2fd294f91f4aa231b01c2b75d6dd8da1f44cb` |
| Tree | `30b3c9660fc8de1db4ff3610362916fe4655514b` |
| Promotions | **27 ✅ · 2 REOPENED** |
| New findings | **6** — `H-01`…`H-06` (P1 1 · P2 2 · P3 3) |
| P0 | none — all three refusals verified closed |

---

## 1 · Pin proof

```
$ git rev-parse 9ae2fd2
9ae2fd294f91f4aa231b01c2b75d6dd8da1f44cb
$ git rev-parse 9ae2fd2^{tree}
30b3c9660fc8de1db4ff3610362916fe4655514b     ← matches the stated tree exactly
$ git status --porcelain      (empty)
$ git stash list              (empty)
```

The pin is valid. **The checkout is not on it.** HEAD is `2db3f0e` — PR #150, *"Owner decision: one
palette, and it is `--menq-*`"* — the pin's direct child. The brief warned this could happen and
said audit the pin. I did not check out `9ae2fd2`: moving a tree another session may be working in
is not a read-only act. Instead I proved the substitution is safe:

```
$ git diff --name-only 9ae2fd2..2db3f0e
NEXT_CHAT.md   PROJECT_STATE.md   TASKS.md   config/current_state.json   docs/OWNER_ACTION_REQUIRED.md
$ git diff --name-only 9ae2fd2..2db3f0e | grep -E '\.(rs|ts|tsx|py|css|yml)$'
(exit 1 — nothing)
```

No `.rs`, `.ts`, `.tsx`, `.py`, `.css` or `.yml` differs from the pin. Every code, gate, test and
stylesheet measurement below was taken in a tree byte-identical to `9ae2fd2`. The five documents
that differ I read at the pin via `git show 9ae2fd2:<path>`, and every quotation from them is so
marked.

HEAD also moved during setup: my first read found `4bcb3db` on branch `palette-decision`, my second
`2db3f0e` on `main`. I reverted nothing.

## 2 · Mutation hygiene

Four tracked files mutated in place, each restored with `git checkout --` and re-verified:

| file | purpose | state at close |
|---|---|---|
| `apps/desktop/src/theme/contrast-pairs.json` | `G-09` | IDENTICAL to pin |
| `.github/workflows/ci.yml` | `G-08` | IDENTICAL to pin |
| `apps/desktop/src/features/Research.tsx` | §E (×3) | IDENTICAL to pin |
| `apps/desktop/src-tauri/src/governance.rs` | `A-02` | IDENTICAL to pin |

Rust runs printed `Compiling brops v0.1.0` on both the mutant and the restore run. Everything else
ran in scratch roots outside the repository. One probe spec was created, run and deleted. Final:
`git status --porcelain` empty, `git stash list` empty.

Final suites: unit 732/732, browser 298/298, tools 575 Ran / OK. **One transient unit failure**
appeared when I ran all three suites back to back and did not reproduce in isolation — consistent
with `vitest.config.ts:14-16`'s own note. See §E.

`gh` is installed and authenticated, so the live-GitHub checks the brief expected to be unavailable
were run.

## 3 · VERDICT: RED

The gate is shut, the seventh round's fifteen findings survive attack almost without exception —
and branch protection, the round's own headline fix, **leaves 18 pull-request-running jobs outside
the wall with no reason recorded anywhere**, among them secret scanning, action pinning and all
four dependency-advisory gates.

## 4 · P0 — the three refusals, and `AnswerProvenance::Governed`

| refusal | state at the pin |
|---|---|
| `governed_verification_unconfigured()` | `commands.rs:1305-1308` — `Some(...)`, no branch. Four call sites: `:1532`, `:2007`, `:2214`, `:3139`. |
| `connect_broker()` | `governed_turn.rs:230-253` — Linux `AF_UNIX`; `#[cfg(not(target_os="linux"))]` → `Err(UnsupportedPlatform)` at `:251`. |
| `build_governed_executor` | `broker/src/main.rs:268-271` — no/empty `$BROPS_BROKER_CONFIG` → `fail_closed()`. Tree-wide search for `export`/`Environment=`/`set_var` on that name: nothing. |

`AnswerProvenance::Governed` (`commands.rs:186`) is constructed nowhere in production. Its only
occurrence outside the definition is `:2990`, inside `#[cfg(test)]` (which begins at `:2724`). The
two production sites are `:2283` `DevelopmentUntrusted` and `:2328` `Ungoverned`. **No P0.**

## 5 · PROMOTION TABLE — the primary output

✅ = I attacked it and could not refute it. REOPENED = it did not survive. **Every ✅ rests on a
measurement I performed, not on reading a note.**

### The seventh round's fifteen

| # | verdict | what I did to try |
|---|---|---|
| `G-01` | ✅ | `protected → true`. `enforce_admins:true`, `strict:true`, `linear:true`, force:false, deletions:false, 12 contexts, every one mapping to a real job. The finding and the fix are real. **The exclusion list is not** — see `H-01`. |
| `G-02` | ✅ | 3 mutations. Delete `#[test]`, keep the fn → RED. Rename the test away → RED. `#[test]` + intervening `#[should_panic]` → GREEN, so the tolerance clause is not a false positive. |
| `G-03` | ✅ | 6 mutations. Both banners announce SEVENTH with no report → RED. Zero-byte report cited by all documents → RED. 100-byte → RED. Dangling citation → RED. Ledger repointed, OWNER page left behind → RED. 4096-byte report with all three repointed → GREEN. **Stronger than claimed:** it binds three documents, `current_state.json` included. |
| `G-04` | ✅ | 4 orderings of the same clobber — entrance-group first, second, and both interleavings inside one file — all RED. Order-independent. |
| `G-05` | ✅ | Carrier state `""` → RED; `None` → RED; `OPEN` → GREEN (a real no-op). All four `A-11` doors re-attacked, all RED. |
| `G-06` | ✅ | Run live: `--settled` with the snapshot naming a merged #150 → refuses, names `--pr`/`--branch`, and `git status` is clean afterwards, so *"Nothing has been written"* is true. |
| `G-07` | ✅ | **23 pages × 3 states = 69 exactly.** Browser suite 298/298. `unstyledClasses` fires correctly on a page root in all three states. What those 69 pairs cannot reach is §E. |
| `G-08` | ✅ | Removed `test_renderer_broker_schemas` from `ci.yml:773`'s run line, left the comment at `:765` that names it → RED, with the exact message. Baseline and restore GREEN. |
| `G-09` | ✅ | Reverted the three colours → RED with exactly 3 pairs: success 3.49:1, warning 3.46:1, info 4.10:1. `grep -c '"size": *"large"'` → 0. Restore → GREEN 24. **Three files, not two.** |
| `G-10` / `G-11(a)` | deferred, correctly — **but now a live defect** | The round deferred these to `T-034` and called them *"measured and currently clean — a structural gap, not a live defect"*. That was true when written. It is no longer: see `H-03`, a 1.81:1 pair created by the same round's own palette restoration. |
| `G-11(b)` | ✅ | `@media` + `[data-theme]` changing a colour → RED; changing geometry → RED; plain `@media` geometry → GREEN; plain `[data-theme]` colour → GREEN. The intersection rule holds in all four quadrants. |
| `G-12` | ✅ | The same clobber applied through plain `class="…"` (the `markdown.tsx` shape) → RED. |
| `G-13` | ✅ (read, not mutated) | `check_c1_tokens.py:731` now calls `keyframe_name_collisions(all_source_css(texts))`. I did not construct a mutation: the round itself established the defect could not be turned into an escape, and I confirmed no keyframe name in the tree collides with an animation keyword. **Recorded as read rather than run.** |
| `G-14` | ✅ | Ledger cites `commands.rs:1305-1308`; `grep -n` → 1305. |
| `G-15` | ✅ | `count_dead_classes.py` → 785 of 2356, reproducing the corrected numerator **and** denominator exactly. |

### The sixth round's fourteen

| # | verdict | what I did to try |
|---|---|---|
| `A-01` | ✅ | Re-ran the round-six Chromium probe. Every measurement inverted: scrim `fixed`/`z-60`/`rgba(0,0,0,.5)`, rect = viewport, covers viewport **true**; panel 620px with border; list `max-height:340px overflow-y:auto`; active row distinct **true**; background clickable **false**, `elementFromPoint` returns the scrim. |
| `A-02` | ✅ | The decisive mutation with rebuild proof: delete `parse_evidence_event`'s comparison → gate RED **and** 1 cargo test failed. In round six the same mutation left both green. 29 → 30 tests. **Residual:** `validates()` still returns True for a bare `let _ = o.get("schema");`; `has_negative_test` is what actually carries the weight. |
| `A-03` | ✅ | `animation-name: sigbreathe` → RED. |
| `A-04` | ✅ | An entrance class that is not `.reveal`/`.rise` → RED. A clobber via `cx('a','b','reveal')` → RED. |
| `A-05` | ✅ | Three-state enum carried from the producing site; `Governed` unreachable (§4); the ungoverned path prints `UNGOVERNED research (no governed turn, no receipt)`. |
| `A-06` | **REOPENED** | The gate exists and is strong (`G-03` ✅). **The defect recurred anyway.** See `H-02`. |
| `A-07` | ✅ | `GroupChat.tsx:309` — one `figure(n)` for all three cells; callers pass `null` on failure. A measured zero and a failed read are no longer the same glyph. |
| `A-08` | ✅ | The false *"All 11 are fixed"* sentence is gone, correction recorded at `OWNER_ACTION_REQUIRED.md:43`. |
| `A-09` | **REOPENED** | **Untouched.** `FORBIDDEN` is byte-identical; `flatten` is still `typeof value === 'string'` only; no test mentions a non-string leaf. All three smuggle routes remain open. |
| `A-10` | ✅ | All three of my round-six misses now caught: `--azure`, `--t-body`, `--r-pill` in a plain `@media :root` → RED, RED, RED; a legitimate `[data-theme]` colour override stays GREEN. |
| `A-11` | ✅ | All four doors RED, plus the two residuals I left open: absent `mergeCommit` → RED, unresolvable `first_parent()` → RED. |
| `A-12` | ✅ | On `ci.yml:773`, and `G-08`'s gate prevents the regression. |
| `A-13` | ✅ | Backtick parity in the P0 row is balanced. |
| `A-14` | ✅ | Corrected, and the correction recorded in place. |

**Score: 27 of the 29 marks earn ✅.** Two are REOPENED — `A-06` and `A-09`. `G-10`/`G-11(a)` were
never claimed fixed and I am not promoting them; they have become live (`H-03`).

## 6 · New findings

### H-01 · P1 · 18 pull-request-running jobs sit outside branch protection with no reason recorded

**Measurement.** 35 named jobs across 8 workflows. 12 are required. Of the 23 excluded, **22 run on
`pull_request`** — only `release.yml`'s single job does not, which is correct. The #148 commit
message documents four and says *"the exclusions are written down rather than left as an absence"*.
**The remaining 18 appear in no document in the tree.**

They include the whole of `supply-chain.yml`: `Secrets - gitleaks`, `Action pins - consistency gate
(F-46)`, `Rust - cargo-audit`, `Rust - cargo-deny`, `Python - pip-audit`, `Node - npm audit`, `SBOM
- CycloneDX`, `Release signing + updater`, `Residual engine items O-1..O-5`, `Runbooks` — and from
`ci.yml`: `Capability · inventory gate (T-010)`, `Supervisor · durable-ledger DDL single-source gate
(F-01)`, `Spec · every § reference`, `Engine · signer isolation proof`, `Windows · §0.W broker
syscall proof`, `Engine · governance runtime on Windows`, `Bridge · engine adapter`, `AI-surface
inventory gate`.

**Failure scenario.** A PR adds a dependency carrying a RustSec advisory, or repoints an Action from
a pinned SHA to a mutable tag, or commits a credential. `cargo-audit`, `F-46` and `gitleaks` all go
red. All 12 required contexts are green. **The PR merges into main with protection on and
`enforce_admins: true`.** `F-46` is a numbered finding whose entire purpose is action pinning; `F-01`
was the round-two P0.

**Remedy** — add the 18, or record a reason per exclusion.
**Verified satisfiable.** Every excluded workflow's latest run on `main` at `2db3f0e` concluded
success. Requiring them today would not wedge main.
**Cost.** Merge latency rises to the slowest required job; `ai-surface.yml` carries a `paths:`
filter, and GitHub treats a skipped required context as pending — that one needs the filter removed
or a no-op guard job first, and I did not verify which.
**Failure mode.** A required job that becomes flaky closes main for everyone; bundle-budget's stated
exclusion reason (*"RED locally"*) is already contradicted by CI, so the reasons need re-deriving
from measurement rather than carrying over.

### H-02 · P2 · the seventh round produced no report, and the gate built to prevent that is GREEN by construction

**Measurement.** `git log --all --diff-filter=A --name-only -- apps/desktop/AUDIT/` lists every file
ever added: six reports, first through sixth. **No seventh-audit report has existed in any commit on
any branch.** `AUDIT_LEDGER.md:11` reads *"Authoritative current assessment:
`2026-08-17-sixth-audit-b16e572.md` — the SIXTH independent audit."* `grep -c` for `G-01`…`G-15` in
the ledger returns 1, a parenthetical about `G-14` inside the third audit's promotions table. `G-09`
and `G-11` appear nowhere in the tree at all. **The complete account of the round exists only in the
commit message of `4d55527`.**

`check_audit_reports.py` → GREEN, correctly: it binds announcement to report, and nothing announces
a seventh. Its docstring says so honestly — *"not whether a round happened at all — nothing in a
repository can know that a conversation took place."*

**Failure scenario.** A reader opens the ledger — which the OWNER page calls "the index" and which is
on the canonical read manifest — to check what the last audit found. It tells them the sixth round is
current. Fifteen findings, eleven fixes and a new security boundary are invisible. Every `(G-05,
seventh audit)` citation now embedded in seven source files points at a document that does not
exist. **This is `A-06` verbatim, one round later, with the gate for it already in the tree and
green.**

**Remedy** — make the ledger's newest findings section the binding, not the banner. Extend
`check_audit_reports.py` to fail when the newest report's ordinal is older than the highest ordinal
named anywhere in `AUDIT_LEDGER.md`, `TASKS.md` or a source comment matching
`\b(fifth|sixth|seventh|eighth) (independent )?audit\b`.
**Verified satisfiable.** The citation strings already exist and are greppable — I extracted the
full `G`-list from them. The gate already parses ordinals and already walks the directory.
**Cost.** One more RED that only the Builder can clear, and it fires after the auditor has gone —
which is the right time, since filing is the Builder's step.
**Failure mode.** A source comment citing a future round would wedge it; the pattern must bind to
rounds that have a head, not to prose.

### H-03 · P2 · the restored palette's active row is 1.81:1 in the light theme

`apps/desktop/src/components/layout.css:120` · `apps/desktop/src/theme/tokens.css:41,72`

```css
.palette-item.active { background: var(--menq-color-selected); color: var(--brops-accent); font-weight: 600; }
```

**Measurement**, using the repository's own `check_contrast.contrast_ratio`:

| theme | fg | effective bg | ratio | AA normal |
|---|---|---|---|---|
| light | `#38bdf8` | `#e8ebff` (12% `#3d5afe` over `#ffffff`) | **1.81:1** | fails 4.50 |
| dark | `#38bdf8` | `#272c47` | 6.38:1 | passes |

The inactive row is 18.58:1. **The selected row — the one `aria-activedescendant` names and Enter
will take — is the least readable row in the list, by a factor of ten.**

The cause is the two-palette collision `T-034` names: `--brops-accent: var(--cyan, #38bdf8)` (the
aios palette) painted on `--menq-color-selected` (the menq palette) in one rule. `check_contrast.py`
is GREEN over 24 pairs because `.palette-item.active` is not among its 12, and because the
manifest's accent is `#3d5afe` — not the token the rule actually paints. **The rule landed in
`12bf733` (PR #138), the fix for my own `A-01`.**

**Remedy** — change `color: var(--brops-accent)` to `--menq-color-accent`, and add
`palette-active-label` to `contrast-pairs.json`.
**UNVERIFIED REMEDY.** I computed that `#3d5afe` on `#e8ebff` is above 4.5:1 and that
`link-on-surface` already passes, but I did not run the gate against a manifest carrying the new
pair, and I did not check the dark-theme selected value.
**Cost.** The highlight stops being cyan — a visual decision inside the `--menq-*` migration `T-034`
already owns.
**Failure mode.** Adding the pair could turn the gate RED on dark too, which would be correct and
would enlarge the change. Doing the token swap without the manifest pair fixes the pixel and leaves
the gate still unable to see the rule — the same shape as the finding.

### H-04 · P3 · seven canonical documents still say main has no branch protection

`docs/ARCHITECTURE.md:46` and `:156` · `QUEUE_MANIFEST.md:60` · `MASTER_EXECUTION_ROADMAP.md:709` ·
`NEXT_CHAT.md:2423` · `PROJECT_STATE.md:2423` · `TASKS.md:2423` — all quoted at the pin.

**Measurement.** Live: `protected → true`. At the pin, `ARCHITECTURE.md:46` reads: *"None of them is
a required check. `main` carries no branch protection and no rulesets: `gh api …/protection` returns
`404 Branch not protected` … (verified 2026-08-09)."* **It states the command, the output and a
verification date.** The Armenian half at `:156` says the same. `QUEUE_MANIFEST.md:60` builds an
argument on it.

**Failure scenario.** A contributor reads `ARCHITECTURE.md` — the file that describes CI — concludes
enforcement is convention, and merges on that understanding; or an auditor reads it and does not
check, which is precisely how `G-01` went six rounds undiscovered.

**Remedy** — correct all seven, and make the claim checkable rather than prose. `check_repo_state.py`
already shells to `gh` and already runs in a required job; a ten-line arm comparing
`branches/main/protection` against a committed expectation turns the next drift RED instead of stale.
**Verified satisfiable** for the checkable half.
**Cost.** The required-context list becomes a committed artefact that must move in the same PR as any
protection change — which is the point.
**Failure mode.** It reads live GitHub, so it inherits the outage class PR #149 was written for; it
must use the same two-road fallback and the same refusal, or it becomes the fifth fail-open door.

### H-05 · P3 · the REST fallback addresses a hardcoded repository, and one line of its pagination is inert

`tools/check_repo_state.py:448` (`_REPO`) · `:560` (`.replace("][", "],[")`)

**Measurement.** Driving the parser with the two shapes `gh api --paginate` emits:

| stdout shape | result |
|---|---|
| single page (this repo today) | 100 numbers, complete |
| two pages, newline-separated | 150 numbers, complete |
| two pages, concatenated | `JSONDecodeError` → caught → `None` → caller refuses |

So the docstring's contract — *"a partial answer here is worse than no answer"* — **holds**. But
`.replace("][", "],[")` cannot help in either shape. The multi-page path is exercised only as a
refusal, and never at all in a repository with fewer than 100 open PRs.

The vocabulary map is correct in all six cases I drove, including `state:null → ''`, which fails
closed. Both roads spawn the same `gh` binary against the same host, and the docstring claims only
v4-outage survival — **the claim is exact, not overstated.**

**Failure scenario.** `gh pr view` infers the repository from the git remote; `gh api` uses the
literal `menqstudio/OS`. In a fork, a v4 hiccup sends `fetch_live(112)` down the REST road, which
returns **upstream's** PR #112. `compare_external_prs` fails closed, but the message names the wrong
repository.

**Remedy** — derive the slug: `gh repo view --json nameWithOwner`, cached once per run, literal as
last resort; and either delete the `.replace` or add the bracket-wrap that would make concatenated
pages parse.
**Verified satisfiable** for the slug. **UNVERIFIED REMEDY** for the pagination — no >100-open-PR
repository was available, and fixing a parser against a shape I have not observed is how the third
version of a check turns out to be the wrong one.

### H-06 · P3 · a load-flaky suite is required; a flaky suite was excluded for being flaky

**Measurement.** Running the unit, browser and tools suites in one command produced `1 failed | 731
passed`; re-run in isolation, 732/732. `vitest.config.ts:14-16` documents exactly this. **That suite
is behind the required context `Cockpit · frontend (typecheck + build + test)`.** Meanwhile `T-023`'s
known-flaky custody job was excluded *because it is flaky*, with the reasoning that a flaky custody
refusal trains everyone to rerun.

**Failure scenario.** The frontend job goes red under CI load on an unrelated PR. Because it is
required, main is closed until someone reruns — **and the rerun is the same reflex `T-023` argues is
dangerous**, now applied to a required gate rather than an advisory one. The two decisions were taken
the same day and point opposite ways.

**Remedy** — pick one rule and apply it to both.
**UNVERIFIED REMEDY.** I observed the flake once in three runs and did not characterise it.
Prescribing a pool setting from one observation is a heuristic dressed as a fix, which is what this
section is supposed to refuse. **The honest first step is to record the failing test name when it
next happens, which nothing currently does.**

## 7 · Ledger and roadmap rows stale or false

| row | problem |
|---|---|
| `AUDIT_LEDGER.md:11` | Stale. Names the sixth audit authoritative; a seventh has run (`H-02`). |
| `AUDIT_LEDGER.md` (whole file) | Structurally incomplete. No seventh-round findings section, no promotions table, no `G-*` rows. |
| `docs/ARCHITECTURE.md:46`, `:156` | **False, with a command and a verification date attached** (`H-04`). |
| `QUEUE_MANIFEST.md:60` · `MASTER_EXECUTION_ROADMAP.md:709` · `NEXT_CHAT.md`/`PROJECT_STATE.md`/`TASKS.md:2423` | False — all five assert no branch protection. |
| `4d55527` commit message, `G-01` paragraph | *"the exclusions are written down rather than left as an absence"* — 4 of 22 are (`H-01`). |
| `4d55527` commit message, `G-01` paragraph | Excludes bundle-budget as *"RED locally for a documented reason"*; the job is green on main. |
| `TASKS.md` `T-034` / `G-10` note | *"Measured and currently clean — a structural gap, not a live defect."* True when written, false now (`H-03`). |
| `tools/check_schema_mirrors.py:200-204` | Says `cargo test -p brops --lib` *"is a required status check on main"*. The required context is `Cockpit · Tauri host (cargo check + ai tests)`; whether that job runs `--lib governance::` I did not confirm — **flagged, not asserted**. |

## 8 · §E — what nothing here can see

**The browser suite measures 16.1% of the styled design system, and none of the state the product
actually ships in.**

`pages.browser.spec.tsx:142` — `STATES = ['pending', 'settled', 'unreachable']`. §D's five states are
`default`, `loading`, `empty`, `error`, `blocked`. The suite covers `loading`, `error` and `empty`.
It covers **neither `default`** — a page with data in it — **nor `blocked`**, which is the state
every governed surface is permanently in on a shipped install, because the gate is shut.

Proven by mutation, with a positive control:

| mutant | browser suite |
|---|---|
| unstyled class on Research's `blocked` branch (`Research.tsx:167`) | 298 passed — **survived** |
| same class on the always-rendered run panel inside the detail view | 298 passed — **survived** |
| same class on the page root (`.v-research`) | RED in all three states, named exactly |

The detector is sound. **What it cannot do is reach the DOM.** Nothing is ever selected, because
every list resolves to `[]`; so every detail pane, every per-row control and every selection-gated
panel is never mounted. Research's `running`/`held`/`saved`/`blocked`/`failed` branches are doubly
unreachable — they also need a `StreamEvent`, and `Channel` is mocked as `class { onmessage = null }`,
so `streamAsk` can never emit.

Quantified, by unioning every class token the 69 pairs mount:

```
tokens SELECTED BY A RULE = 2249
tokens the 69 pairs MOUNT =  363
styled tokens REACHED     =  363  (16.1% of the styled system)
styled tokens NEVER shown = 1886
```

Set beside `count_dead_classes.py`'s 785 of 2356: **roughly 1 200 class tokens are referenced by
shipped code and mounted by no test at all.** `T-024` is recorded as closed; what it closed is the
ability to measure, over a sixth of the surface.

Three further things nothing looked at:

1. **The seventh round's own record is a commit message.** Eleven of its fifteen findings survive
   only as `(G-0n, seventh audit)` inside source comments. `G-09` and `G-11` have no trace in the
   tree. If `git log` is ever squashed or the branch pruned, the reasoning behind eleven live checks
   is gone. `H-02`'s remedy addresses the report; nothing addresses the reasoning.
2. **Nine PRs merged in one day, all by the same session**, five of them before branch protection
   existed. Between `4d55527` and `9ae2fd2` the only code change is PR #149's REST fallback, and it
   is **the one piece of new code in this round that no gate covers** — `grep -c "_rest_"
   tools/test_check_repo_state.py` → **0**. The fallback written during an outage, merged the same
   day, has no test of its own; I supplied the first measurements of it in `H-05`.
3. **`enforce_admins: true` is doing less than it appears.** It prevents an admin bypassing the
   required contexts. It does nothing about the 18 that are not required, **which is where the supply
   chain lives.**

## 9 · What I could not check, and why

- **I did not check out the pin.** The checkout was one commit ahead and another session had been
  active in it minutes earlier. I proved instead that no code file differs, and read the five
  differing documents via `git show`.
- Any **runtime** behaviour of the Linux broker, supervisor, signer or ladder — Linux-only; this host
  is Windows. The three refusals were verified by reading, by tree-wide absence of a setter, and by
  the compiled test suite.
- **The engine (Python) suite and the Windows LIVE jobs** — not run; their conclusions are carried
  from CI, not measured by me.
- **`G-13`** — verified by reading the call site and confirming no keyframe name collides. I did not
  construct a mutation, and I say so rather than counting it as re-run.
- **Whether `Cockpit · Tauri host` runs `cargo test -p brops --lib`** — I did not open the job body,
  so the `has_negative_test` docstring's claim is flagged rather than judged.
- **Which `gh api --paginate` output shape this `gh` version emits** — no repository with >100 open
  PRs was available, so `H-05`'s pagination half is a reading of the parser, not a measurement of the
  transport.
- **The one transient unit-test failure** — it did not reproduce and nothing records which test it
  was.
- `check_read_receipt.py` / `check_roadmap_order.py` — read only, per the standing instruction.

`gh auth` was available, so nothing in this report is blocked on it.
