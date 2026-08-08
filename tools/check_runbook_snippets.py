#!/usr/bin/env python3
"""Check that the Python the runbooks tell you to paste actually matches the code it calls.

`docs/DEBIAN_DEPLOYMENT.md` embeds `python3 -c "..."` snippets. Twice now one of them has been
wrong in a way no reader could have caught: a call with the wrong number of arguments, discovered
by a person running it on a real box rather than by anyone reading it. A wrong snippet is worse
than a missing one — it looks authoritative and it fails at the point where the reader has already
mounted something.

This parses every snippet with `ast` and, for each call to a module the repository owns, compares
the call against the real signature. It is a syntax and arity check, not a semantic one: it cannot
tell you the snippet does the right thing, only that it will not die on the first line.

Run it in CI so this cannot rot the way the snippets themselves did.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine" / "runtime"))

DOCS = ("docs/DEBIAN_DEPLOYMENT.md", "docs/OWNER_CEREMONY.md")
# module name in the snippet -> importable module
CHECKED_MODULES = ("bro_protected", "bro_signature", "bro_audit_log", "bro_completion")

# A shell double-quoted string runs to the next unescaped `"`. Anchoring on end-of-line
# instead — as the first version did — mis-parses any snippet inside a $(...) substitution.
# to the next double quote, not to end-of-line: a snippet may sit inside $(...)
SNIPPET = re.compile(r'python3\s+(?:-\w+\s+)*-c\s+"([^"]*)"', re.S)


def snippets(text: str):
    """Every `python3 -c "..."` payload, with the line it starts on."""
    for m in SNIPPET.finditer(text):
        yield text[: m.start()].count("\n") + 1, m.group(1)


def resolve(node: ast.AST, aliases: dict[str, str]) -> str | None:
    """Return the owned-module function a Call refers to, as 'module.func', or None."""
    fn = node.func
    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
        mod = aliases.get(fn.value.id, fn.value.id)
        return f"{mod}.{fn.attr}" if mod in CHECKED_MODULES else None
    if isinstance(fn, ast.Name):
        return aliases.get(f"::{fn.id}")          # from bro_protected import X
    return None


def arity_problem(dotted: str, node: ast.Call) -> str | None:
    mod_name, _, func_name = dotted.partition(".")
    try:
        mod = __import__(mod_name)
    except Exception as exc:                       # noqa: BLE001 — report, do not crash the gate
        return f"cannot import {mod_name}: {exc}"
    fn = getattr(mod, func_name, None)
    if fn is None:
        return f"{mod_name} has no {func_name}"
    if not callable(fn):
        return None
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    positional = [p for p in sig.parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    required = [p for p in positional if p.default is inspect.Parameter.empty]
    given = len(node.args)
    kw = {k.arg for k in node.keywords if k.arg}
    supplied = given + len(kw & set(sig.parameters))
    if supplied < len(required):
        return (f"called with {supplied} argument(s); needs {len(required)} "
                f"({', '.join(p.name for p in required)})")
    if not any(p.kind is p.VAR_POSITIONAL for p in sig.parameters.values()) and given > len(positional):
        return f"called with {given} positional argument(s); takes at most {len(positional)}"
    return None


def check(path: pathlib.Path) -> list[str]:
    problems, checked = [], 0
    for line, code in snippets(path.read_text(encoding="utf-8")):
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            problems.append(f"{path}:{line}: snippet does not parse: {exc}")
            continue
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    aliases[a.asname or a.name] = a.name
            elif isinstance(node, ast.ImportFrom) and node.module in CHECKED_MODULES:
                for a in node.names:
                    aliases[f"::{a.asname or a.name}"] = f"{node.module}.{a.name}"
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            dotted = resolve(node, aliases)
            if not dotted:
                continue
            checked += 1
            problem = arity_problem(dotted, node)
            if problem:
                problems.append(f"{path}:{line}: {dotted} {problem}")
    print(f"  {path}: {checked} call(s) checked against the real signatures")
    return problems


#: A repo-relative path the runbooks cite. Runtime paths (/etc/brops, /opt/brops, /media/usb)
#: cannot be checked from here and are deliberately not matched.
#: Anchored on the top-level directories this repository actually has, so a path is
#: recognised wherever it appears -- inside a bash block, in prose, backticked or not.
#: The first version required backticks and found ONE path in a document that cites a
#: dozen, then reported GREEN. A checker that under-reports is the defect it is meant
#: to catch, one level up.
_TOP = 'engine|docs|tools|apps|bridge|config|schemas|laws|scripts'
CITED_PATH = re.compile(r'(?<![\w/.-])(?:' + _TOP + r')(?:/[A-Za-z0-9_.-]+)+\.[A-Za-z]{1,4}(?![\w-])')


def check_paths(path: pathlib.Path) -> list[str]:
    """Every repo-relative file the runbook names must exist.

    Three times this week a runbook cited a path that was not there: a key file named after the
    key id instead of the authority, a tool invoked from a directory that does not contain it,
    and a registry read from /etc when the step that writes it writes into the tree. Each was
    found by somebody following the document on a real machine, at the point where the wrong
    path costs them the most. A wrong path is the cheapest possible defect to catch and the most
    expensive to hit.
    """
    problems = []
    text = path.read_text(encoding="utf-8")
    seen = set()
    for match in CITED_PATH.finditer(text):
        rel = match.group(0)
        if rel in seen:
            continue
        seen.add(rel)
        if not (ROOT / rel).exists():
            line = text[: match.start()].count("\n") + 1
            problems.append(f"{path}:{line}: cites `{rel}`, which does not exist in the tree")
    print(f"  {path}: {len(seen)} repo-relative path(s) checked "
          f"(runtime paths under /etc, /opt and /media are NOT checked and cannot be "
          f"from here -- two of the three wrong paths this week were of that kind)")
    return problems


def main() -> int:
    problems: list[str] = []
    for rel in DOCS:
        p = ROOT / rel
        if not p.exists():
            problems.append(f"{rel}: listed here but missing from the tree")
            continue
        problems += check(p)
        problems += check_paths(p)
    if problems:
        print("\nRED: runbook snippets disagree with the code they call:")
        for prob in problems:
            print(f"  {prob}")
        return 1
    print("GREEN: every runbook snippet parses, every owned call matches its real signature,")
    print("       and every repo-relative path the runbooks cite exists.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
