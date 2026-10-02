# Shell classifier design verdict

**Status: Architect design before code change.** This document is an independent design decision for the shell command classifier. It does not change the classifier or the execution path.

## Trust boundary

The classifier may decide only a bounded *description* of a proposed shell invocation:

- whether the command is a single supported read-only form;
- which coarse capabilities it requests (`READ_LOCAL`, repository mutation, external write, network/credential use, or unknown);
- which literal path arguments can be subjected to workspace/scope checks; and
- whether a separate approval/work-grant path must be required.

It is not trusted to prove what Bash will execute, to authorize a write, to establish identity, or to grant approval. The actual shell remains an execution boundary. Any syntax the classifier cannot model exactly must be refused before execution. A command classified as read-only still cannot bypass the existing policy, lease, scope, receipt, and recovery gates.

## Current implementation read

`engine/runtime/bro_security.py` implements a hand-written `split_shell()` followed by `shlex.split(..., posix=False)` and executable/argument allowlists. `engine/runtime/bro_authorization.py:_classify_shell()` aggregates those results into capabilities and mutation flags. The parser already refuses redirection, command substitution (`$(...)` and backticks), background `&`, and unterminated quotes, and it has conservative allowlists for `git` and `find`.

## Shell/classifier differences reproduced on this tree

All probes below used the current `analyze_command()`/`classify_tool_action()` and a real `bash -c` with a harmless marker in place of a destructive operation. The classifier result is recorded; no external mutation was performed.

### 1. Comments can hide a second command (R2-0001)

Input:

```text
echo hi # ' \\n echo INJECTED
```

Classifier: one read-only `echo` segment (`READ_LOCAL`, `mutating=False`). Bash: the `#` starts a comment, the quote in the comment has no syntactic effect, and the next line executes as a second command. The classifier has no comment state and therefore lets a later command ride on the first read-only segment. A plain `echo hi # rm -rf src` is also reduced to `echo hi`, but the dangerous case is the newline after a comment containing an unmatched quote.

### 2. ANSI-C and locale quotes are not shell quotes (R2-0002 and adjacent forms)

Input:

```text
echo $'\\'' ; echo INJECTED-RAN ; echo \\'
```

Classifier: one read-only `echo` segment. Bash: `$'...'` is ANSI-C quoting; the quote sequence closes before the semicolon and Bash executes the middle command. The same parser gap exists for Bash's `$"..."` locale-quote form: it is not represented by the hand-written quote state, so separators inside/after it can be classified differently from Bash.

### 3. Expansion changes arguments without changing classifier tokens

Inputs such as:

```text
cat "$FILE"
cat *.json
cat {a,b}.json
```

The classifier records literal token text (`$FILE`, `*.json`, `{a,b}.json`) while Bash performs parameter, pathname, and brace expansion before opening files. The command shape remains `cat`, but the set of files read and the resulting scope targets are not the literal strings the gate sees. This is a containment blind spot for reads, not a reason to call the command a write.

### 4. Newline and line-continuation semantics are only partially modeled

The splitter treats `\\` as an escape and `\\n` as ordinary buffered text while it scans; Bash treats backslash-newline as line continuation and removes both characters before tokenization. A CRLF input is split on `\\n` but leaves `\\r` in the preceding token, whereas Bash treats the line ending as a command separator. These forms were reproduced with harmless `printf` probes and show that the custom lexer is not a Bash lexer even where it reaches the same coarse command in common cases.

### 5. Shell grammar constructs are refused for being unknown, not parsed

`if`, `case`, `for`, function definitions, subshells `( ... )`, brace groups `{ ...; }`, `!`, `time`, and here-documents/compound redirections are not represented as AST nodes. Some are eventually classified as unknown/mutating and denied; others are rejected by the explicit redirection checks. This is conservative, but it means the classifier cannot safely claim read-only semantics for any of these constructs and must continue to refuse them.

### 6. Already-covered constructs remain important regression boundaries

The current lexer rejects command substitution, backticks, `>`, `<`, `|`, `;`, `&&`, `||`, newline separators, and background `&`. I confirmed the current probes for `echo hi & rm -rf src`, `echo hi\\nrm -rf src`, quoted semicolons, `$(...)`, and backticks. These must remain refusal tests after replacement.

## Required design: Shell AST Gate

Implement one design: **Shell AST Gate — parse with a real Bash grammar, then apply a fail-closed AST allowlist.**

Use a maintained Bash grammar/parser (for example a pinned tree-sitter-bash parser, or an equivalently complete maintained parser already approved by the repository) in a dedicated security boundary. Parse the complete command into an AST without executing it. Reject parse errors and every node type not explicitly allowed. Apply policy to the AST, not to token spelling:

1. reject comments that contain a command boundary or any syntactically active continuation ambiguity;
2. reject ANSI-C/locale quotes, expansions, command substitutions, process substitutions, arithmetic substitutions, here-docs, functions, loops, conditionals, groups, pipelines, asynchronous lists, and redirections unless a future policy explicitly models them;
3. allow only a small, named read-only grammar for the existing built-ins and the existing per-command `git`/`find` allowlists;
4. resolve expansions before producing path targets, or refuse any expansion in a path-bearing argument;
5. preserve the existing path-qualified executable rule and capability/approval mapping;
6. return `UNKNOWN`/deny on parser-version errors, unsupported node kinds, non-UTF-8 input, or ambiguous encoding.

This is stronger than adding more regex/character checks because the shell grammar, quoting, comments, continuations, and compound-command boundaries are interpreted by the same class of parser that defines the language. A growing hand-written lexer will continue to miss grammar features and dialect extensions. The parser version and grammar hash must be pinned and upgraded only with adversarial corpus review.

The AST gate does not execute a shell to “discover” what it would do. Execution remains separately governed, and the gate never grants a write or approval.

## Commands that must be refused

At minimum:

- any parse error or unsupported AST node;
- comments/continuations that create an additional command boundary;
- ANSI-C or locale quoting (`$'...'`, `$"..."`);
- parameter, pathname, brace, arithmetic, command, or process substitution in a path/capability-bearing position;
- redirection, here-doc/here-string, pipeline, `&`, `&&`, `||`, `;`, subshell/group, function, loop, conditional, `!`, `time`, `eval`, `source`, `exec`, `env`-style wrappers, and nested shells;
- an executable reached through a path when it would otherwise be a recognized read-only builtin;
- unknown git options, config keys, find predicates/actions, or path arguments outside the existing allowlists;
- any command whose parser result and policy result cannot be deterministically reproduced.

## Test plan

The replacement must have behavior tests, not source-string checks:

1. A corpus of every current refusal plus the two R2 forms, each run through the AST gate and a real Bash oracle; the gate must refuse whenever Bash can form more than one command or perform a side effect.
2. Property/fuzz tests generating quote, comment, newline, CRLF, escape, expansion, redirection, and compound-command combinations; no generated input may be classified `READ_LOCAL` unless the AST contains only the named read-only grammar.
3. Differential tests for safe commands (`cat`, `ls`, `git status`, approved `git diff`, approved `find`) asserting stable capabilities and path targets.
4. Mutation tests that remove each refusal rule, each unsupported-node default, and each expansion/path check, then require the adversarial corpus to go red.
5. Integration tests through `bro_authorization.classify_tool_action()` and the real pre-tool wall, proving an accepted read cannot execute an unclassified second command and a proposed write still reaches the existing task/work/approval gates.
6. Parser upgrade tests: record grammar/parser version and rerun the full corpus before accepting an upgrade.

## Out of scope

This design does not change Action Runtime authority, task/work grants, approval tokens, workspace binding, OS sandboxing, the shell executable itself, or the product's decision about whether shell access exists. It does not make arbitrary shell commands safe, does not grant network or credential use, and does not replace the existing external-write governance. It also does not attempt to support the full Bash language: unsupported language remains a deliberate refusal.

## Appendix A — implementation rulings (T-159, PR #331)

### Q1 — parser inside the wall or strict positive grammar

**Ruling: choose B: use a dependency-free strict positive grammar inside the security wall, and use the pinned Bash parser only as a mandatory test-time second oracle.**

The parser adds no acceptance guarantee that the proposed wall can rely on here: the measured tree does not expose several security-relevant separators and expansions, so the byte-coverage and character/structure rules would still decide every accepted input. Keeping that parser in the wall would add a native runtime dependency and a fail-all-shells failure mode without removing the need for the same strict table. A small language that accepts one simple command and accounts for every input byte is the smaller, auditable security boundary; it must not grow into a partial Bash implementation.

The proposed character table is accepted with these precise rulings:

- Outside quotes, accept only the listed ASCII characters and space/tab separators. Every other byte or code point is refused, including control characters, CR, LF, NUL, `#`, shell operators, glob characters, braces, commas, parentheses, and an unquoted backslash.
- A bare `~` is accepted only after the first character of a word, as the table specifies. That permits literal revision/path forms such as `HEAD~1`; a bare leading `~` is refused because it is a Bash tilde-expansion position. A quoted `~` is literal data and is allowed by the selected quote rule.
- Valid non-ASCII UTF-8 is allowed only inside a quoted part, so quoted Armenian or other human text can be passed as data. Non-ASCII outside quotes, malformed UTF-8, and control characters in either quote form are refused.
- A missing or unusable parser in a CI job that declares the parser oracle is a test failure, never a skip. The runtime wall itself has no parser import and therefore does not become unavailable when the test-only parser is absent.

**Required design (changed from the body):** implement a standard-library-only, left-to-right positive grammar for exactly `blank* word (blank+ word)* blank*`, with the stated `bare`, `single`, and `double` parts; account for every input byte; decode and validate arguments only after the grammar succeeds; then apply the existing executable, `git`, `find`, path, capability, and approval rules. The Bash grammar/parser is test-only, pinned, and used as an independent oracle; it is not part of the pre-tool wall.

**Commands that must be refused (changed from the body):** refuse every byte sequence outside that one-simple-command language, including parse/coverage failure, unsupported characters, leading unquoted `~`, comments, continuations, ANSI-C or locale quotes, parameter/pathname/brace/arithmetic/command/process substitution, redirection, here-doc/here-string, pipeline, `&`, `&&`, `||`, `;`, newline, CR, subshell/group, function, loop, conditional, `!`, `time`, `eval`, `source`, `exec`, `env`-style wrapper, nested shell, path-qualified executable, unknown `git`/`find` option or predicate, and any path/capability target outside the existing allowlists. A quoted non-ASCII payload is allowed only as literal data under the quote rules above.

**Test plan (changed from the body):** retain the current refusal corpus and real-Bash differential corpus, but make the test-only parser oracle a required CI dependency for that test job: absence, import failure, grammar-version mismatch, or parser error fails the job. Add exhaustive byte-table tests for every ASCII byte in bare, single-quoted, and double-quoted contexts; valid and malformed UTF-8 tests; `~` at word start versus after the first character; and full byte-coverage assertions. Keep generated quote/comment/CRLF/escape/expansion/compound inputs, safe-command differential tests, mutation tests for each refusal/default, authorization-wall integration tests, and parser-version corpus review. The runtime acceptance decision must be reproducible without the parser package.

### Q2 — Bash, PowerShell, and Shell

**Ruling: run the gate for Bash, PowerShell, and Shell, but grant `READ_LOCAL` only when the resolved tool is Bash; a would-be read under PowerShell or Shell is `UNKNOWN` and is denied, while mutating classifications remain subject to their existing governance.**

The accepted grammar and oracle are Bash-specific, and the current registry resolves all three names through the shell classifier. Without a separately specified and tested grammar for PowerShell and the generic Shell resolver, the classifier cannot prove that a command has the same parse, expansion, quoting, or redirection semantics there. Applying the wall to all three prevents an alternate tool name from bypassing inspection; withholding the read-only capability outside Bash is the fail-closed result. This ruling does not grant any new write authority.

### Q3 — compound commands

**Ruling: refuse compound commands as a whole for both reads and governed mutations; use `git commit -F <file>` for multi-line commit messages.**

A separator, pipeline, asynchronous list, or newline creates more than one shell operation and makes one capability/approval decision ambiguous; splitting it into separately classified segments is not an acceptable substitute. A commit message supplied by `-F` is file data consumed by one simple `git` invocation, so it does not reintroduce shell grammar into the command boundary. Mutating simple commands still follow the existing task, scope, work-grant, exact approval, execution, and verification gates.

### Verification limits

I verified the requested PR head and inspected the design, implementation-questions document, `bro_security.py`, and `bro_authorization.py`. I did not independently install or run tree-sitter, reproduce the Builder's parser measurements or import timings, execute PowerShell, run the full pre-tool hook, or implement the classifier/tests in this design-only pass. Those claims remain implementation-audit work for the follow-up code pull request.
