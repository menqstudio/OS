#!/usr/bin/env python3
"""One source for a fact that several documents repeat.

A fact written by hand in nine files is wrong in one of them after the second change. This tool
knows nothing about any project: it reads `config/doc-facts.json`, resolves each declared fact from
its ONE source, and keeps every marked span in the listed documents equal to it.

    python3 tools/sync_facts.py --check     # change nothing; exit 1 and name each stale span
    python3 tools/sync_facts.py --write     # rewrite the stale spans

THE MARKER. In Markdown, an HTML comment pair, invisible when rendered and usable mid-sentence:

    the <!-- fact:audit_round|upper -->ELEVENTH<!-- /fact --> round

What sits between the two comments belongs to the tool. `|upper`, `|lower`, `|title` and `|comma`
(1434 -> 1,434) are the only filters. A span never crosses a line.

WHERE A MARKER CANNOT GO -- a JSON file, a fenced code block, a document held to a byte ceiling --
a fact reaches the text through a declared target instead, and the document gains no bytes:

    "targets": [{"file": "CLAUDE.md", "fact": "rust_tests",
                 "pattern": "cargo test --workspace +# (\\d+) passed"}]

The pattern has exactly one group and must match exactly once in the file; the group is the fact.

A SOURCE is exactly one of:
    {"value": "..."}                                   a literal, declared once
    {"json":  {"file": F, "path": "a.b.0.c"}}          a field of a JSON file
    {"regex": {"file": F, "pattern": "...(group)..."}}  group 1 of the ONLY match in a file
    {"command": ["git", "rev-parse", "--short", "HEAD"]}  argv, never a shell string

WHAT IT REFUSES, by name, changing nothing: a marker naming an undeclared fact; an unknown filter;
an opening marker with no close on its line; a regex source that matches zero times or more than
once; a target pattern that does the same, or has no group or several; a source that resolves to
an empty or multi-line value; a declared fact that nothing uses; a listed document that is absent.

WHAT IT DOES NOT DO. It does not write prose and it does not find unmarked copies of a fact: a
number typed by hand outside a marker is invisible to it. It does not reach inside a fenced code
block's meaning either -- a marker there is rewritten like any other, and shows as literal text.
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib
import re
import subprocess
import sys

CONFIG = "config/doc-facts.json"
SPAN = re.compile(r"<!-- fact:([A-Za-z0-9_.-]+)((?:\|[a-z]+)*) -->(.*?)<!-- /fact -->")
OPEN = re.compile(r"<!-- fact:")
COMMAND_TIMEOUT_S = 30

FILTERS = {
    "upper": str.upper,
    "lower": str.lower,
    "title": str.title,
    "comma": lambda s: f"{int(s):,}",
}


class Refusal(Exception):
    """A configuration or document error. Nothing is written once one is raised."""


def _json_path(data, path: str, where: str):
    cur = data
    for part in path.split("."):
        try:
            cur = cur[int(part)] if isinstance(cur, list) else cur[part]
        except (KeyError, IndexError, ValueError, TypeError):
            raise Refusal(f"{where}: path `{path}` does not resolve (stopped at `{part}`)")
    return cur


def resolve(name: str, source: dict, root: pathlib.Path) -> str:
    """The value of one fact, from its one source."""
    if not isinstance(source, dict) or len(source) != 1:
        raise Refusal(f"fact `{name}`: a source is exactly one of value / json / regex / command")
    kind, spec = next(iter(source.items()))
    if kind == "value":
        value = spec
    elif kind == "json":
        f = root / spec["file"]
        if not f.is_file():
            raise Refusal(f"fact `{name}`: {spec['file']} does not exist")
        value = _json_path(json.loads(f.read_text(encoding="utf-8")), spec["path"],
                           f"fact `{name}`, {spec['file']}")
    elif kind == "regex":
        f = root / spec["file"]
        if not f.is_file():
            raise Refusal(f"fact `{name}`: {spec['file']} does not exist")
        found = re.findall(spec["pattern"], f.read_text(encoding="utf-8"))
        if len(found) != 1:
            raise Refusal(f"fact `{name}`: the pattern matches {len(found)} time(s) in "
                          f"{spec['file']}; a source is one match, not {len(found)}")
        value = found[0] if isinstance(found[0], str) else found[0][0]
    elif kind == "command":
        if not (isinstance(spec, list) and spec and all(isinstance(a, str) for a in spec)):
            raise Refusal(f"fact `{name}`: a command is a list of arguments, never a shell string")
        try:
            done = subprocess.run(spec, cwd=root, capture_output=True, text=True,
                                  timeout=COMMAND_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Refusal(f"fact `{name}`: `{' '.join(spec)}` did not run: {exc}")
        if done.returncode != 0:
            raise Refusal(f"fact `{name}`: `{' '.join(spec)}` exited {done.returncode}")
        value = done.stdout.strip()
    else:
        raise Refusal(f"fact `{name}`: unknown source kind `{kind}`")
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise Refusal(f"fact `{name}`: resolved to {type(value).__name__}, not text or a whole number")
    text = str(value)
    if not text.strip() or "\n" in text or "-->" in text:
        raise Refusal(f"fact `{name}`: resolved to an empty, multi-line or comment-closing value")
    return text


def render(value: str, filters: str, where: str) -> str:
    for f in [x for x in filters.split("|") if x]:
        if f not in FILTERS:
            raise Refusal(f"{where}: unknown filter `{f}` (known: {', '.join(sorted(FILTERS))})")
        try:
            value = FILTERS[f](value)
        except ValueError:
            raise Refusal(f"{where}: filter `{f}` cannot be applied to `{value}`")
    return value


def plan(root: pathlib.Path):
    """Everything that would change. Returns (edits, counts) or raises Refusal.

    edits: {path: (new_text, [(line_no, fact, old, new)])} for each file with a stale use.
    """
    cfg_file = root / CONFIG
    if not cfg_file.is_file():
        raise Refusal(f"{CONFIG} does not exist; there is nothing declared to keep in step")
    cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    facts = cfg.get("facts") or {}
    if not facts:
        raise Refusal(f"{CONFIG} declares no facts")
    values = {name: resolve(name, spec.get("source"), root) for name, spec in facts.items()}

    paths: list[pathlib.Path] = []
    for pattern in cfg.get("documents") or []:
        hits = sorted(glob.glob(str(root / pattern), recursive=True))
        if not hits:
            raise Refusal(f"{CONFIG}: document `{pattern}` matches no file")
        paths.extend(pathlib.Path(h) for h in hits if pathlib.Path(h).is_file())
    targets = cfg.get("targets") or []
    for target in targets:
        if not (root / target["file"]).is_file():
            raise Refusal(f"{CONFIG}: target file {target['file']} does not exist")
        paths.append(root / target["file"])

    used: set[str] = set()
    uses = 0
    edits = {}
    marked = {pathlib.Path(h) for pattern in cfg.get("documents") or []
              for h in glob.glob(str(root / pattern), recursive=True)}
    for path in dict.fromkeys(paths):
        rel = path.relative_to(root).as_posix()
        # newline="" on both sides: universal-newline translation would turn a CRLF checkout into
        # LF on the way back, and a one-word fix would arrive as a whole-file diff on Windows.
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
        stale = []
        if path in marked:
            out = []
            for no, line in enumerate(text.splitlines(keepends=True), 1):
                if len(OPEN.findall(line)) != len(SPAN.findall(line)):
                    raise Refusal(f"{rel}:{no}: a fact marker opens and does not close on its line")

                def fix(m, no=no):
                    nonlocal uses
                    name, filters, old = m.group(1), m.group(2), m.group(3)
                    if name not in values:
                        raise Refusal(f"{rel}:{no}: marker names `{name}`, which {CONFIG} does not declare")
                    used.add(name)
                    uses += 1
                    new = render(values[name], filters, f"{rel}:{no}")
                    if old != new:
                        stale.append((no, name, old, new))
                    return f"<!-- fact:{name}{filters} -->{new}<!-- /fact -->"

                out.append(SPAN.sub(fix, line))
            text = "".join(out)
        for target in targets:
            if root / target["file"] != path:
                continue
            name = target["fact"]
            if name not in values:
                raise Refusal(f"{CONFIG}: a target in {rel} names `{name}`, which is not declared")
            try:
                rx = re.compile(target["pattern"])
            except re.error as exc:
                raise Refusal(f"{CONFIG}: the `{name}` pattern for {rel} is not a regular expression: {exc}")
            if rx.groups != 1:
                raise Refusal(f"{CONFIG}: the `{name}` pattern for {rel} has {rx.groups} group(s); "
                              f"it needs exactly one, and that group is the fact")
            found = list(rx.finditer(text))
            if len(found) != 1:
                raise Refusal(f"{CONFIG}: the `{name}` pattern matches {len(found)} time(s) in {rel}; "
                              f"a target is one place, not {len(found)}")
            used.add(name)
            uses += 1
            m = found[0]
            new = render(values[name], "|" + target["filter"] if target.get("filter") else "", rel)
            if m.group(1) != new:
                stale.append((text.count("\n", 0, m.start(1)) + 1, name, m.group(1), new))
                text = text[:m.start(1)] + new + text[m.end(1):]
        if stale:
            edits[path] = (text, stale)

    unused = sorted(set(values) - used)
    if unused:
        raise Refusal(f"{CONFIG} declares {', '.join('`'+u+'`' for u in unused)} and nothing uses "
                      f"{'it' if len(unused) == 1 else 'them'}; a fact with no reader is not kept")
    return edits, (len(values), uses, len(dict.fromkeys(paths)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="change nothing; exit 1 if anything is stale")
    mode.add_argument("--write", action="store_true", help="rewrite the stale spans")
    ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root).resolve()
    try:
        edits, (n_facts, n_uses, n_docs) = plan(root)
    except Refusal as exc:
        print(f"RED: {exc}. Nothing has been written.")
        return 2
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        print(f"RED: {CONFIG} or a file it names could not be read: {exc!r}. Nothing has been written.")
        return 2

    stale = [(p.relative_to(root).as_posix(), no, name, old, new)
             for p, (_, rows) in edits.items() for (no, name, old, new) in rows]
    summary = f"{n_facts} fact(s), {n_uses} use(s) in {n_docs} file(s)"
    if not stale:
        print(f"GREEN: every use of a declared fact equals its source; {summary}.")
        return 0
    for rel, no, name, old, new in stale:
        print(f"  {rel}:{no}: `{name}` says `{old}`, the source says `{new}`")
    if args.check:
        print(f"RED: {len(stale)} stale use(s); {summary}. Run:  python3 tools/sync_facts.py --write")
        return 1
    for path, (text, _) in edits.items():
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    print(f"WROTE: {len(stale)} use(s) brought to their source; {summary}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
