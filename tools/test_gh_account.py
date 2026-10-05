"""tools/gh_account.py: which GitHub account a tool asks as.

On 2026-10-05 every `gh`-calling tool here went RED on a correct mirror because the active `gh`
login was not the account that owns this repository, and the repository had gone private. These
tests hold the rule that replaced "remember to prefix a token": the owner of `origin` decides,
and a token already in the environment decides before that.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gh_account  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOKEN = "gho_" + "x" * 36


class FakeRun:
    """`git remote get-url origin` and `gh auth token --user <owner>`, answered from a table."""

    def __init__(self, origin="https://github.com/menqstudio/OS.git", logins=None):
        self.origin, self.logins, self.calls = origin, dict(logins or {}), []

    def __call__(self, args, cwd):
        self.calls.append(list(args))
        if args[0] == "git":
            return (0, self.origin) if self.origin is not None else (1, "")
        owner = args[args.index("--user") + 1]
        return (0, self.logins[owner]) if owner in self.logins else (1, "")


class OriginOwnerTests(unittest.TestCase):
    def test_the_three_spellings_of_a_github_origin_name_the_same_owner(self):
        for url in ("https://github.com/menqstudio/OS.git", "https://github.com/menqstudio/OS",
                    "git@github.com:menqstudio/OS.git", "ssh://git@github.com/menqstudio/OS.git",
                    "https://github.com/menqstudio/OS.git/\n"):
            self.assertEqual(gh_account.origin_owner(url), "menqstudio", url)

    def test_an_origin_that_is_not_githubs_names_nobody(self):
        for url in ("", "https://gitlab.com/menqstudio/OS.git", "/srv/git/OS.git",
                    "https://github.com.evil.example/menqstudio/OS.git",
                    "https://evil.example/github.com/menqstudio/OS.git",
                    "https://github.com/menqstudio", "https://github.com//OS.git",
                    "https://github.com/a b/OS.git"):
            self.assertIsNone(gh_account.origin_owner(url), url)


class UseRepoAccountTests(unittest.TestCase):
    def test_the_owners_login_is_used_when_the_environment_has_no_token(self):
        environ, run = {}, FakeRun(logins={"menqstudio": TOKEN, "someone-else": "gho_other"})
        self.assertEqual(gh_account.use_repo_account(ROOT, environ, run), "gh login menqstudio")
        self.assertEqual(environ, {"GH_TOKEN": TOKEN})
        self.assertEqual(run.calls[1][-2:], ["--user", "menqstudio"])

    def test_a_token_already_in_the_environment_wins_and_nothing_is_asked(self):
        """CI sets one, and so does a person who means it. Neither is overridden."""
        for name in gh_account.TOKEN_VARIABLES:
            environ, run = {name: "set-on-purpose"}, FakeRun(logins={"menqstudio": TOKEN})
            self.assertEqual(gh_account.use_repo_account(ROOT, environ, run), "environment")
            self.assertEqual(environ, {name: "set-on-purpose"})
            self.assertEqual(run.calls, [])

    def test_an_empty_token_variable_is_not_a_token(self):
        environ, run = {"GH_TOKEN": ""}, FakeRun(logins={"menqstudio": TOKEN})
        self.assertEqual(gh_account.use_repo_account(ROOT, environ, run), "gh login menqstudio")
        self.assertEqual(environ["GH_TOKEN"], TOKEN)

    def test_no_login_for_the_owner_changes_nothing(self):
        environ, run = {}, FakeRun(logins={"someone-else": "gho_other"})
        self.assertEqual(gh_account.use_repo_account(ROOT, environ, run), "active account")
        self.assertEqual(environ, {})

    def test_an_origin_that_cannot_be_read_or_is_not_githubs_changes_nothing(self):
        for origin in (None, "https://gitlab.com/menqstudio/OS.git"):
            environ, run = {}, FakeRun(origin=origin, logins={"menqstudio": TOKEN})
            self.assertEqual(gh_account.use_repo_account(ROOT, environ, run), "active account")
            self.assertEqual(environ, {})
            self.assertEqual(len(run.calls), 1, "gh was asked about an owner nobody established")

    def test_an_answer_that_is_not_one_token_is_not_used(self):
        for answer in ("", "two\nlines"):
            environ, run = {}, FakeRun(logins={"menqstudio": answer})
            self.assertEqual(gh_account.use_repo_account(ROOT, environ, run), "active account")
            self.assertEqual(environ, {})

    def test_what_is_returned_never_carries_the_token(self):
        environ, run = {}, FakeRun(logins={"menqstudio": TOKEN})
        self.assertNotIn(TOKEN, gh_account.use_repo_account(ROOT, environ, run))


class EveryGhToolAsksTests(unittest.TestCase):
    """The rule lives in one module; this is what stops a fifth tool from skipping it."""

    def test_every_tool_that_calls_gh_asks_as_the_owner_before_it_runs(self):
        tools = pathlib.Path(__file__).resolve().parent
        callers = sorted(path.name for path in tools.glob("*.py")
                         if not path.name.startswith("test_") and path.name != "gh_account.py"
                         and '["gh",' in path.read_text(encoding="utf-8"))
        self.assertEqual(callers, ["check_merge_ready.py", "check_repo_state.py",
                                   "stamp_pr_head.py", "sync_active_pr.py"])
        for name in callers:
            text = (tools / name).read_text(encoding="utf-8")
            entry = text[text.rindex('if __name__ == "__main__":'):]
            self.assertIn("gh_account.use_repo_account()", entry, name)
            self.assertLess(entry.index("gh_account.use_repo_account()"), entry.index("(main())"),
                            f"{name} runs before it has chosen an account")


if __name__ == "__main__":
    unittest.main()
