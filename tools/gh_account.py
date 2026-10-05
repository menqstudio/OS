#!/usr/bin/env python3
"""Ask GitHub as the account that OWNS this repository, not as whichever one is active.

`gh` keeps several logins and uses the one marked active. On the Builder's machine two are logged
in -- `menqstudio`, which owns this repository, and a second account with repositories of its
own -- and the second was the active one. While this repository was public that cost nothing.
It went private, and from then every tool here that calls `gh` asked as an account that cannot
see it: `git pull` answered `repository not found`, and `check_repo_state.py` answered
`repository slug unresolved` and went RED on a mirror that was correct (2026-10-05).

Switching the active account is not the fix: it is global, and it breaks the other account's
repositories on the same machine. A session that prefixes every command with a token works until
one command forgets, and the hooks never had the prefix at all -- they run in the harness's
environment, not the command's.

So the tools decide. `use_repo_account()` is called at the start of every tool that calls `gh`:

  * a token already in the environment wins and nothing is touched -- that is CI, and it is a
    person who set one on purpose;
  * otherwise the owner is read from `origin`, and if `gh` holds a login for an account of that
    name, its token is put in THIS process's environment, where the `gh` children inherit it;
  * otherwise nothing changes, and the tool fails as it did, in its own words.

The token is never printed, returned or written anywhere. What is returned is one word about
where the answer came from, for a caller that wants to say so.

Stdlib only. Exit status is not meaningful: this is a library.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Either variable makes `gh` skip its stored logins entirely.
TOKEN_VARIABLES = ("GH_TOKEN", "GITHUB_TOKEN")

#: `https://github.com/OWNER/NAME(.git)`, `git@github.com:OWNER/NAME(.git)` and
#: `ssh://git@github.com/OWNER/NAME(.git)`. Anything else is not a repository this can speak for.
_ORIGIN = re.compile(r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
                     r"([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/[A-Za-z0-9._-]+?(?:\.git)?/?$")


def origin_owner(url: str) -> str | None:
    """The account or organisation an `origin` URL names, or None when it is not GitHub's."""
    match = _ORIGIN.match(url.strip())
    return match.group(1) if match else None


def _run(args: list[str], cwd: pathlib.Path) -> tuple[int, str]:
    try:
        done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                              timeout=20)
    except (subprocess.SubprocessError, OSError):
        return 1, ""
    return done.returncode, done.stdout.strip()


def use_repo_account(root: pathlib.Path = ROOT, environ=None, run=_run) -> str:
    """Make this process ask GitHub as the repository's owner. Returns where the token is from:
    `environment`, `gh login <owner>` or `active account`."""
    environ = os.environ if environ is None else environ
    if any(environ.get(name) for name in TOKEN_VARIABLES):
        return "environment"
    code, url = run(["git", "-C", str(root), "remote", "get-url", "origin"], root)
    owner = origin_owner(url) if code == 0 else None
    if owner is None:
        return "active account"
    code, token = run(["gh", "auth", "token", "--hostname", "github.com", "--user", owner], root)
    if code != 0 or not token or "\n" in token:
        return "active account"
    environ["GH_TOKEN"] = token
    return f"gh login {owner}"
