# T-159 — the shell classifier, rebuilt to Appendix A: CODE-AUDIT request

> **For the Architect.** Roadmap §G.2 makes your audit mandatory for engine security code. This
> code was written after your design and after your Appendix A, and is **not merged**.
>
> **What the merge gate needs from you.** A report committed on this pull request's branch under
> `apps/desktop/AUDIT/changes/` (not `engine/AUDIT/`: a Markdown file under `engine/` must be
> registered in a manifest that is itself an audit-required path), carrying two lines,
> `Audited-PR: #333` and `Audited-Head: <the 40-hex commit you read>`. Take the
> head from `gh pr view 333 --json headRefOid`. The gate (`tools/check_merge_ready.py`) refuses the
> merge unless that commit is an ancestor of the head being merged and no audit-required path
> differs since it. The gate does not read your verdict; the Builder does, and merges only on GREEN.
> You do not need to touch the pull request body: CI stamps it (T-163).
>
> Everything below marked ◑ is the Builder's claim. Nothing here is independently confirmed.

## Round 2 — what changed after your RED

Your report (`apps/desktop/AUDIT/changes/pr-333-shell-classifier.md`) confirmed A, B and C and was
RED on **E**: the parser pins sat in `engine/requirements-ci.txt`, which the deployment runbook
installs into the service's environment. Corrected as you required, and nothing else in
`engine/runtime/` moved:

- `engine/requirements-ci.txt` is **byte-identical to `main`** again.
- `engine/requirements-test-oracle.txt` is new and holds only the two parser pins. Both engine CI
  jobs install it after the runtime lock; nothing else does. Measured in a fresh venv: after the
  deployment lock alone, no `tree-sitter` package is present; after the oracle lock, exactly two.
- The new lock is a CI supply-chain input, so it is held like the one beside it: added to
  `protected_roots` and `digest_roots` in `engine/config/protected-control-plane.json`, to
  `config/audit-required-paths.json`, and to the `pip-audit` step.
- Three tests hold the separation: the oracle lock pins exactly the two packages at the versions
  the test names; the deployment lock names no parser; the runbook does not install the oracle
  lock. Six mutants, six named deaths.
- Engine suite: **2730** OK (17 skipped without the parser, 13 with both locks installed).

On your point in D — the parser oracle is run on accepted inputs and the two findings, not on
every refused form — that is true and is left as it is: a refused form is not run under any
oracle, by design, and the parser's opinion of one would not change the refusal.

**Because audit-required paths changed after the head you read, the gate needs a new
`Audited-Head`.** Please re-read the diff since that head and update your report in place.

## 1. What changed

`engine/runtime/bro_security.py`: `split_shell` and `_tokens` (a hand-written lexer followed by
`shlex`) are deleted. `parse_simple_command` replaces them: one left-to-right pass that accepts the
language of Appendix A and refuses every other character. `analyze_command` and
`validate_exact_push` call it; the `git`, `find`, executable and path-qualified rules below them are
not edited. `engine/runtime/bro_authorization.py`: a would-be `READ_LOCAL` under `PowerShell` or
`Shell` becomes `UNKNOWN`. Nothing under `runtime/` or `tools/` imports a parser.

## 2. What is accepted now that was refused before

**One class, measured.** 17,807 distinct generated commands were classified by `main`'s classifier
and by this one. In **220** the new one grants `READ_LOCAL` where the old one answered `UNKNOWN`,
and every one of them is a read-only verb whose NAME carries quotes: `ec'ho' x`, `c"a"t 'a b'`,
`''cat`. The old code looked up the name with its quotes still inside it; the new one looks up the
decoded name, which is the name Bash runs. In **0** cases does the new classifier accept anything
the old one refused outright. **This is the first thing to attack.**

## 3. What is refused now that was accepted before

In the same comparison, 1,232 commands the old classifier called a read, 591 it called a governed
mutation and 4,260 it called unknown are now refused before classification. By kind:

- an unquoted `#` (R2-0001), `$'...'` and `$"..."` (R2-0002);
- every separator: `;`, `&&`, `||`, `|`, newline. They used to split the command and each segment
  was classified; the command is refused whole, for a governed mutation as for a read;
- `$`, `*`, `?`, `[`, `]`, `{`, `}`, `,`, `(`, `)`, `!` outside quotes; a backslash anywhere but
  inside single quotes, which includes an unquoted Windows path;
- `~` first in a word, **and after a bare `=` or `:`** (see §5);
- CR, NUL, every other control character, a newline inside quotes, non-ASCII outside quotes;
- a command name containing `=`;
- a read under `PowerShell` or `Shell` (`UNKNOWN`, denied by the capability gate).

## 4. One reading of Appendix A the Builder made, to confirm or overturn

The "must be refused" list names *path-qualified executable*, *nested shell*, `time`, `eval`,
`exec`, `source` and `env`-style wrappers. "Required design" says to *apply the existing executable
rules*. The grammar accepts each of these, because each is one command made of letters. The Builder
left the existing rules as they are and pinned, in a test that drives the whole wall, **which gate
denies each**: a nested shell at the scope gate (*mutation targets could not be determined*), a
path-qualified executable at the workspace gate, the rest at the capability gate as `UNKNOWN`. If
you meant a refusal by the classifier itself, say so and it is a small change.

## 5. Where the code is stricter than the table you accepted

- **`~` after a bare `=` or `:`.** Your ruling accepts a bare `~` anywhere but first in a word. Bash
  expands it in any ARGUMENT shaped like an assignment: measured here, `echo x=~` prints `x=`
  followed by the home directory and so does `echo x=a:~` after its colon, while `--x=~` and `x:y=~` stay as typed. The code refuses
  `~` straight after either character. With that rule removed, the Bash oracle goes red.
- **Control characters** are C0, DEL, C1, a lone surrogate (what invalid UTF-8 becomes on the way
  in) and U+2028/U+2029, decided by code-point range and not by `unicodedata`, so the answer does
  not depend on the interpreter's Unicode tables.

## 6. Tests, against your test plan

| Plan item | Where | What it holds |
|---|---|---|
| 1 corpus + Bash oracle | `tests/test_shell_grammar.py` | 83 refused forms; an accepted command is run with a probe as its executable and Bash must hand it the gate's argument list, in one command. A control test proves the oracle sees two commands in R2-0001 and three in R2-0002 |
| 2 generated inputs | same | 4,000 seeded combinations: gate against a second, regex statement of the language; each of the 252 it accepts against Bash |
| exhaustive byte table | same | every ASCII byte in four places (512 cases) against a table typed in the test, and each of the 331 it accepts against Bash |
| 3 stable classification | same | `cat`, `ls`, `git status`, `git diff`, `git log`, `find`, `echo`: capability and targets |
| 4 mutation | §7 | 52 mutants, 52 killed |
| 5 the wall | `tests/test_full_execution_transaction_e2e.py` | five tests through `authorize_tool` with a full valid bundle: a second command cannot ride a read; a write still reaches the scope and transaction gates |
| 6 parser pin | `tests/test_shell_grammar.py` | tree-sitter 0.26.0 + tree-sitter-bash 0.25.1; versions equal the lockfile's; required in both engine CI jobs (`BRO_SHELL_PARSER_ORACLE=required`), where a parser that cannot load **fails** |

## 7. Mutation sweep ◑

52 mutants: each refused character added to the bare set (23), each `~` rule, each quote rule,
each control-character range, the unterminated quote, the assignment prefix, newline and CR as
blanks, the empty command, the path-qualified rule, the Bash-only read rule (5), the push length.
All 52 were killed by named tests and both files were byte-identical afterwards.

**One survivor on the first pass, and it was not this change's:** `validate_exact_push` requires
exactly four words and no test defended that. With the check removed, `git push origin HEAD:b
--force` passed every other condition. A test now holds it.

**What each oracle catches alone.** The parser oracle by itself kills 37 of the 52. It does not see
CR treated as a blank, or `~` after `=`. Bash does. That is the measurement behind keeping the
parser as a second opinion and not the first.

## 8. Files

| File | What |
|---|---|
| `engine/runtime/bro_security.py` | `parse_simple_command`; `split_shell`, `_tokens` and the `shlex` import removed |
| `engine/runtime/bro_authorization.py` | `READ_ONLY_SHELL_TOOLS`, the demotion in `_classify_shell` |
| `engine/tests/test_shell_grammar.py` | new, 33 tests |
| `engine/tests/test_security_v2.py` | four tests rewritten: they asserted the old splitting |
| `engine/tests/test_full_execution_transaction_e2e.py` | five wall-level tests |
| `engine/tests/catalog.json` | the new module |
| `engine/requirements-test-oracle.txt` | new: the two test-only pins, PyPI's published hashes. `requirements-ci.txt` is unchanged from `main` |
| `engine/config/protected-control-plane.json`, `config/audit-required-paths.json`, `.github/workflows/supply-chain.yml` | the new lock is protected, digested, audit-required and audited by `pip-audit` |
| `.github/workflows/ci.yml` | `BRO_SHELL_PARSER_ORACLE: required` on both engine jobs, which install the oracle lock |

## 9. What the Builder ran ◑

- Engine suite, `BRO_ENV=ci`, Debian 13, non-root: **2730 tests, OK**, 17 skipped under the system
  interpreter (4 are the parser oracle, not installed there) and 13 skipped in a fresh venv built
  from both locks with `pip install --require-hashes`, oracle required. It was 2692 on `main`.
- Both locks install with hash checking on CPython 3.13.

## 10. What was NOT done

- **Nothing on Windows.** The Bash oracle skips there; the parser oracle is declared required
  there and has never run there. The proof is the `windows-latest` job on this pull request.
- **Nothing about PowerShell was measured.** Q2 is implemented as ruled, on your reasoning.
- **The hook subprocess was not driven.** `authorize_tool`, the function `bro_hook.py pre-tool`
  calls, was driven in-process with the suite's existing bundle fixture.
- **Python 3.14 is not supported by the lockfile**, before or after this change.
- Nothing removes the oracle install from a CI job except CI itself: with the step deleted, the
  job fails because the oracle is declared required there. No local test reads the workflow.
- The findings pages still list R2-0001 and R2-0002 as open; they belong to T-145.
- Seen and not fixed: `test_live_tcb_pin_manifest` uses one shared `/tmp/source-tree`, so two
  engine suites run at once fail each other.
