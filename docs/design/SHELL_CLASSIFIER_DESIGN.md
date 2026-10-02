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
