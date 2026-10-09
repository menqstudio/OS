# sync_facts — one source for a fact several documents repeat

A number, a name or a commit written by hand in nine files is wrong in one of them after the
second change. `sync_facts.py` keeps every declared use of a fact equal to its one source.
It knows nothing about this project: the tool is the same file in every repository, and
`config/doc-facts.json` is the only part that differs.

    python3 tools/sync_facts.py --check     # change nothing; exit 1 and name each stale use
    python3 tools/sync_facts.py --write     # bring every stale use to its source

## Declaring a fact

A fact has a name and exactly one source:

    "facts": {
      "release":   {"source": {"value": "2.4.0"}},
      "tests":     {"source": {"json":  {"file": "config/counts.json", "path": "suite.total"}}},
      "round":     {"source": {"regex": {"file": "AUDIT.md", "pattern": "the \\*\\*([A-Z]+)\\*\\* audit"}}},
      "head":      {"source": {"command": ["git", "rev-parse", "--short", "HEAD"]}}
    }

A regex source must match exactly once. A command is a list of arguments, never a shell string.

## Using a fact — two ways

**A marker**, in a Markdown file listed under `"documents"`. Invisible when rendered, usable
mid-sentence; what sits between the two comments belongs to the tool:

    version <!-- fact:release -->2.4.0<!-- /fact -->, <!-- fact:tests|comma -->1,434<!-- /fact --> tests

Filters: `upper`, `lower`, `title`, `comma`.

**A target**, where a marker cannot go — a JSON file, a fenced code block, a file held to a byte
ceiling. The document gains nothing; the configuration says where the fact sits:

    "targets": [{"file": "README.md", "fact": "tests", "pattern": "npm test +# (\\d+) tests"}]

The pattern has exactly one group, that group is the fact, and it must match exactly once in the
file. A pattern that matches twice, or stops matching after an edit, is refused by name.

## What it refuses, changing nothing

An undeclared fact in a marker or target; an unknown filter; a marker that does not close on its
line; a source or target that matches zero times or several; a source that resolves to an empty or
multi-line value; a declared fact nothing uses; a listed file that is not there.

## What it does not do

It writes facts, not prose. It does not find an unmarked, undeclared copy of a fact: a number typed
by hand that no marker and no target covers is invisible to it. Add a fact when it is found in a
second file.

## Taking it to another repository

1. Copy `tools/sync_facts.py` and `tools/test_sync_facts.py` unchanged. Python 3.9+, no packages.
2. Write `config/doc-facts.json`: the facts that repository repeats, and where each one sits.
3. Run `--check` until it is GREEN; every refusal names the file and the reason.
4. Run `--check` in CI. Copy `tools/check_facts.py` too if the repository has a gate loop.

Line endings: a CRLF checkout is worked on as LF and written back as CRLF, so a pattern written
with `\n` matches on Windows; a file that mixes the two keeps every ending. The first Windows CI
run found both that and a test fixture that doubled its own `\r`.
