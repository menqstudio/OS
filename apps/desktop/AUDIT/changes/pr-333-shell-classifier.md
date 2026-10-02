Audited-PR: #333
Audited-Head: 2c95395edbc0ddfc607810b2999b5fd2471943df
VERDICT: RED — the classifier implementation is conservative and its required CI evidence is green, but test-only parser wheels are included in the production service installation lock; separate the test oracle dependency from the deployment lock before merge.

# Scope and environment

I confirmed the pull-request head with `gh pr view 333 --json headRefOid` and `git rev-parse HEAD`; both reported `2c95395edbc0ddfc607810b2999b5fd2471943df`. The audit ran in a fresh clone on Debian with CPython 3.14.4. The hash-pinned requirements do not support this interpreter, and the parser packages were not installed locally:

```text
PARSER_UNAVAILABLE ModuleNotFoundError No module named 'tree_sitter'
```

I read the design and Appendix A, the audit request, `bro_security.py`, `bro_authorization.py`, `test_shell_grammar.py`, and the five shell wall tests in `test_full_execution_transaction_e2e.py` in the requested order.

# A — Appendix A conformance

## Core language

`parse_simple_command` at `engine/runtime/bro_security.py:219-272` implements the requested single-command positive grammar: only space/tab separators, adjacent bare/single/double parts, no separators, expansion, escape, comments, or partial acceptance. `analyze_command` and `validate_exact_push` call it at lines 437-456. No runtime or tool module imports tree-sitter. This is compliant with Appendix A's chosen design B.

The implementation is deliberately stricter in the two places described by the Builder:

1. `engine/runtime/bro_security.py:257-260` rejects bare `~` immediately after a bare `=` or `:` as well as at word start. Appendix A allowed `~` after the first character generally; this stricter rule is justified by Bash tilde expansion in those assignment-shaped argument positions. The test suite explicitly covers `x=~`, `x=~/x`, `x:a=~`, and accepted `HEAD~1`/`a~` forms.
2. `engine/runtime/bro_security.py:205-212` defines control characters by code-point ranges (C0, DEL/C1, surrogates, U+2028/U+2029), rather than an implementation-dependent Unicode category. This is stricter and deterministic, and the tests cover the ranges.

The quote-name widening is also present: quote parts are decoded into one argument before lookup (`parse_simple_command:241-252`), so `ec'ho'`, `c"a"t`, and `''cat` are looked up as the command Bash actually invokes. This is not an expansion: only literal quote concatenation is accepted, every byte remains covered, and no additional command can be introduced. The Bash/model/grammar tests pass for these forms. I found no looser acceptance than Appendix A's language.

# B — path-qualified executables and wrappers

I accept the Builder's reading of Appendix A. The required design says to preserve the existing executable rules; it does not require `parse_simple_command` itself to throw for every named wrapper. The whole authorization wall denies each form through the existing gates, and the wall-level test pins the gate:

- `bash -c 'rm docs/x'` and `sh -c 'cat docs/x'` → `scope gate RED: mutation targets could not be determined`.
- `/usr/bin/git status` → `workspace scope gate RED`.
- `time cat docs/x`, `eval cat docs/x`, `exec cat docs/x`, `env cat docs/x`, and `source docs/x` → `tool capability gate RED: unknown tool/action`.
- `cat /etc/passwd` → `workspace scope gate RED`.

These classifications are produced by `bro_security._analyze_named/_reached_by_path` and then enforced by `_classify_shell`/the downstream gates. They are not parser-level `SecurityError`s, but the security boundary refuses them before execution, which is the existing-rule interpretation requested in §4. The five E2E tests at `engine/tests/test_full_execution_transaction_e2e.py:480-498` exercise this exact behavior.

# C — quoted command names

The widening is safe and correct. Bash concatenates quoted and unquoted literal parts before command lookup; decoding `ec'ho'` to `echo` therefore matches execution. The accepted language still rejects all expansions, separators, control characters, and path-qualified read executables. `test_shell_grammar.py` covers `'probe'`, `pr"ob"e`, and the generated quoted-name cases; no new bypass form was introduced.

# D — test evidence

The targeted shell grammar suite on this host was:

```text
Ran 31 tests in 1.500s
OK (skipped=4)
```

The four skips were the parser-oracle tests because tree-sitter was not installed locally; the test's required-oracle mode would fail rather than skip. The Bash oracle and regex model portions all passed locally.

The full requested suite on CPython 3.14.4 was:

```text
Ran 2728 tests in 101.160s
FAILED (failures=5, errors=1, skipped=19)
```

The failures/errors were environment or pre-existing runtime issues, not shell-grammar assertions:

- `test_env_health.CheckEnvironmentTests.test_live_required_dependencies_resolve` — `EnvHealthError: required runtime dependency RED: cryptography (imported)`.
- `test_bytecode_shadow.HookInterpreterFlagTests.test_the_wired_interpreter_really_disables_bytecode_writing` — wired `python` not on PATH.
- `test_live_hook_deny.LiveHookWiringTests.test_wired_command_denies_out_of_scope` — wired interpreter does not resolve on PATH.
- `test_live_hook_deny.LiveHookWiringTests.test_wired_interpreter_resolves_on_path` — wired `python` does not resolve on PATH.
- `test_live_sudoers_install.FragmentTextTests.test_the_real_visudo_accepts_all_three_and_rejects_a_broken_one_through_the_block` (`run_ladder_turn.sh`, `PYSUDO`) — real `visudo` rejected wildcards in command arguments.
- The same sudoers test (`run_live_turn.sh`, `PYSUDO`) — real `visudo` rejected wildcards in command arguments.

The independent CI logs for this exact head show the supported Python 3.12.14 jobs installed both parser wheels with `BRO_SHELL_PARSER_ORACLE=required` and completed:

```text
Linux:   Ran 2728 tests in 59.339s;  OK (skipped=13)
Windows: Ran 2728 tests in 261.110s; OK (skipped=239)
```

The CI logs show successful installation of `tree-sitter==0.26.0` and `tree-sitter-bash==0.25.1`, and the required-oracle environment variable. Thus the required parser-oracle job evidence exists in CI, although I did not reproduce it locally on 3.14.

The three opinions are not fully independent:

- The regex model is a separately written implementation, but it deliberately duplicates the same accepted-language table and therefore shares the design assumption with the code under test.
- Real Bash is an independent execution oracle and is the strongest evidence for expansion, quoting, and command-count behavior.
- Tree-sitter is an independent parser implementation, but the parser tests exercise accepted inputs plus the two known findings, not every refused form. The request's measured anonymous-token gaps are why byte coverage and Bash remain necessary.

The evidence is strong for the accepted language and the listed regressions, but it is not a proof that every refused form is represented by every oracle. The 52-mutant report is corroborating evidence; I did not independently rerun the mutation sweep.

# E — dependency placement

`engine/requirements-ci.txt:60-72` labels tree-sitter and tree-sitter-bash `TEST-ONLY`, but `docs/DEBIAN_DEPLOYMENT.md:251` installs that same file into the production service virtualenv. The runtime does not import the parser, which prevents a runtime bypass, but the deployment nevertheless receives two unnecessary native parser packages and their supply-chain pins. That contradicts the declared test-only boundary and can make a production install depend on artifacts that production does not need.

**Required correction:** move the two parser pins and their hashes into a dedicated test-oracle lock installed by the engine test jobs, while the deployment lock contains only runtime dependencies; keep the runtime parser-import prohibition and the mandatory CI oracle. Until that separation is made (or deployment is explicitly changed to install a runtime-only lock), this audit remains RED.

# What I did not verify

I did not run the suite under CPython 3.12 locally because only CPython 3.14.4 is available here. I did not independently install tree-sitter under 3.14, execute PowerShell, drive a real pre-tool subprocess hook, rerun the 52 mutation sweep, or reproduce the Builder's 17,807-command comparison. I did independently inspect the code and targeted tests, run the Bash oracle-backed shell suite, and retrieve the exact-head Linux and Windows CI job logs.
