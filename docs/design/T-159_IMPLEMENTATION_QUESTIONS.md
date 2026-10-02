# T-159 — three questions for the Architect before any classifier code

> **For the Architect.** Roadmap §G.2 puts your answer before the implementation. No classifier
> code exists on this branch. Please answer as an appendix to
> [`SHELL_CLASSIFIER_DESIGN.md`](./SHELL_CLASSIFIER_DESIGN.md) on this pull request. Everything
> marked ◑ is the Builder's claim; nothing here is independently confirmed. Only forms the design
> already names are used below.

## What was measured (2026-10-02, Debian 13, Python 3.13.5, bash 5.2.37)

`tree-sitter 0.26.0` + `tree-sitter-bash 0.25.1` (both MIT), installed in a scratch venv, never in
the repository. The system `python3` here imports neither.

- **It sees both findings.** R2-0001 parses as two `command` nodes and a `comment`; R2-0002 as three
  `command` nodes, the first carrying an `ansi_c_string`.
- **Three things the tree does not show.** (1) `&` in `echo hi &`, `;` in `cat x;` and the `$` of
  `$"x"` are *anonymous* tokens: the named tree for each is one plain `command`, and `$"x"` reads as
  an ordinary `string`. (2) `cat *.json`, `cat x?` and `cat ~/x` are plain `word` nodes: pathname and
  tilde expansion are not represented. (3) A backslash-newline and a trailing `\r` are in **no leaf
  at all**; `echo hi\r\necho two` parses as two commands with the `\r` consumed as blank space.
  `time cat x` parses as a command named `time`.
- **Cost.** Two native libraries (2.06 MB and 1.52 MB); about 25 ms of import per hook process,
  measured three times. The engine runtime imports only the standard library at module scope today.

So a gate built on the tree alone accepts forms the design refuses. The Builder's first plan added
a character allowlist and a byte-coverage check on top of it. The Owner then asked the question
this page puts to you.

## Q1. If only one simple command of allowlisted characters is accepted, what does the parser add inside the wall?

- **A · Parser in the wall.** `tree-sitter-bash` runs in the pre-tool hook; on top of it, a walk of
  every node including anonymous tokens against a node allowlist, a character allowlist per leaf,
  and a check that leaves plus blanks cover every input byte.
- **B · Strict positive grammar, no dependency.** The wall accepts exactly one language, decided
  in one left-to-right pass by standard-library code, and refuses every other byte sequence. The
  parser is used **only in tests**, as a second oracle beside real `bash`.

Proposed language for B ◑ (not yet tested against bash; the test plan below is what would prove it):

```text
command := blank* word (blank+ word)* blank*        blank := space | tab
word    := part+                                    (adjacent parts are one argument)
part    := bare | 'single' | "double"
bare    := one or more of  A-Z a-z 0-9 _ . / : = @ % + ^ -   and ~ when not first in the word
single  := any character except ' " and control characters
double  := any character except " ' $ ` \ ! and control characters
```

The first word may not contain `=`. Outside quotes only ASCII is accepted. Every other byte,
including newline, CR, NUL, `#`, `&`, `;`, `|`, `<`, `>`, `(`, `)`, `{`, `}`, `*`, `?`, `[`, `]`,
`,` and an unquoted backslash, is a refusal. The existing `git`/`find` allowlists and the
path-qualified-executable rule then run on the decoded argument list, unchanged.

| | A · parser in the wall | B · positive grammar |
|---|---|---|
| Refuses | everything B refuses, **only because of the same allowlist**; additionally a tree whose node kinds differ from the expected ones | everything outside the language above, by construction |
| Cannot see | globs, tilde, CR, line continuation and anonymous separators, unless the allowlist and coverage check catch them (measured) | nothing structural, **provided** no allowlisted character is syntactically active in bash; that proviso is the whole risk |
| What the parser contributes | a second, independent opinion at run time on input the allowlist already accepted | the same second opinion at test time, over the corpus and the generator |
| Environment is short | package absent, wrong version or wrong interpreter: **every shell command is refused** | nothing to be absent: standard library only |
| Supply chain | two native wheels in the hook's process, hash-pinned per interpreter and platform | none in the wall; one test-only pin |
| Proven by | corpus + bash oracle + generator; a grammar/version pin test | corpus + bash oracle + generator, **plus an exhaustive table**: every ASCII byte in each of the three contexts, run through the gate and through real bash and the parser, so the allowlist is proven character by character rather than sampled |
| Grows badly when | never worse than today | the accepted language is widened (pipelines, `&&`, expansions). Then the design's warning about hand-written lexers applies in full and this question reopens |

**Recommendation: B**, because under the design's own acceptance rule the allowlist is what
decides in both options — the measurement shows the tree cannot refuse the forms in (1)–(3)
without it — so in A the parser adds a run-time second opinion on already-accepted input and
nothing else, and it pays for that with a new way for the wall to refuse everything and two native
libraries in the perimeter. The design's objection to hand-written lexers is aimed at a lexer that
tries to *model* bash, which is what `split_shell` does; B models nothing, and its only way to be
wrong is one finite table that can be tested exhaustively. Cost of B, stated: it departs from the
design's sentence "parse with a real Bash grammar", so it needs your appendix; and it is correct
only while the accepted language stays this small.

Two environment facts relayed by the Owner, not reproduced by the Builder: the hash-pinned wheels
did not install under Python 3.14 on the Architect's machine today, and the suite would go red
under the system interpreter. `engine/requirements-ci.txt` states cp312 and cp313 as its supported
interpreters, which is consistent with the first.

Sub-questions under B, if you choose it: (a) is `~` after the first character acceptable, for
`HEAD~1`; (b) may non-ASCII appear inside quotes, for commit messages; (c) in tests, should a
missing parser fail rather than skip when CI declares it required — the Builder proposes fail.

## Q2. `PowerShell` and `Shell` are shell-resolved tools too

`engine/tools/registry.json` resolves three tools through this classifier: `Bash`, `PowerShell`,
`Shell`. The design speaks of Bash only, and neither a Bash grammar nor a Bash oracle can vouch for
how PowerShell reads a line. No PowerShell exists on this machine; nothing about it was measured.

**Proposal:** the gate runs on all three, so nothing it refuses passes under another tool name; a
read-only classification is granted **only** when the tool is `Bash`. Under `PowerShell` or
`Shell`, a command that would have been `READ_LOCAL` becomes `UNKNOWN`, which is denied outright.
Mutating classifications are unchanged. Please confirm or replace.

## Q3. Compound commands are refused whole, governed mutations included

Today `;`, `&&`, `||`, `|` and newline split a command and each segment is classified. Under the
design every one of them is a refusal, for a mutation under a work grant as well as for a read:
`git add x && git commit -m y` becomes two tool calls, and a multi-line commit message goes
through `git commit -F <file>`. A newline inside quotes is refused too. The Owner has accepted this
cost. Tests that assert the old splitting (`test_segments_quotes_windows_and_mixed_case`, the
`&&` arm of `test_an_ampersand_that_separates_nothing_is_still_text`) will be rewritten as refusal
tests, and Windows-spelled executables (`C:\Git\bin\git.exe`, `tools\ls.exe`) become refusals
rather than governed mutations, because an unquoted backslash is refused. Please confirm.

## What was not done

No classifier code, no test, no dependency pin. The proposed table for B was not run against bash.
The full pre-tool hook was not driven. No form outside the design's own list was tried.
