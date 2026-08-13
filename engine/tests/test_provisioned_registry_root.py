"""O-3: the engine reads the registry the deployment provisioned, or it refuses.

`load_trusted_keys` read `<root>/config/trusted-keys.json` and every engine caller
passed the engine's OWN tree — `bro_hook` hands `authorize_conductor_stop` the module's
`ROOT`, and that reaches `bro_policy.verify_conductor_session_token`. So an install that
mints its trust material somewhere else was invisible: the minted conductor-session
artifact verified perfectly against a registry nothing consulted, while the development
registry committed at `engine/config/trusted-keys.json` — signed by a different operator
key — answered for everything. That is the whole of O-3.

`BRO_TRUSTED_REGISTRY_ROOT` names the deployment's registry root. Four properties are
pinned here, and each is the reason the redirect is not simply a new attack surface.

**Unset changes nothing.** The default path is one dictionary lookup and returns the
caller's root; no existing deployment moves.

**The anchor does not move with the registry.** "The registry payload is never the pin"
is what makes writing the registry insufficient to introduce a key. A redirect that
could also select its own pin would hand over the registry, the anchor that
authenticates it and the floor that keeps it current in one variable. So the pin and the
anti-rollback floor are refused inside the redirected root, in every spelling — and the
tests below prove the two cannot be satisfied by the same file.

**The redirect is all-or-nothing.** A redirect half the callers honour is worse than
none: it produces a deployment where the hook consults the provisioned trust and the
supervisor consults the stale committed one, with nothing saying so. When the override
is set, a caller asking for the engine's own tree gets the override and a caller asking
for a different root is REFUSED by name.

**O-3 closes in both directions.** `verify_conductor_session_token` accepts a token
minted against a provisioned registry when the override points there, and refuses the
same token when the override is unset or points elsewhere.
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import shutil
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import bro_signature
from bro_signature import (
    ENV_PIN_FILE,
    ENV_PIN_SELF_OWNED_ACK,
    ENV_PIN_SELF_OWNED_ACK_FILE,
    ENV_REGISTRY_MIN_FILE,
    ENV_REGISTRY_ROOT,
    PIN_SELF_OWNED_ACK_VALUE,
    REGISTRY_REL,
    SignatureError,
    load_trusted_keys,
    resolve_registry_root,
)
from bro_policy import (CANONICAL_CONDUCTOR_ID, CONDUCTOR_ROLE,
                        CONDUCTOR_SESSION_ARTIFACT, CONDUCTOR_SESSION_TOKEN_ENV,
                        State, verify_conductor_session_token)
from broctl import build_registry, generate_key, sign_payload
from _operator_pin import use_operator_pin
import _self_owned_ack

SESSION = "s-conductor-provisioned"


def _outside(test_case, prefix: str) -> pathlib.Path:
    """A fresh directory outside the repository, resolved.

    Resolved so that an incidental symlink parent — `/tmp` is one on macOS — does not
    trip the every-component symlink rejection in the cases that are meant to pass.
    """
    directory = pathlib.Path(tempfile.mkdtemp(prefix=prefix)).resolve()
    test_case.addCleanup(shutil.rmtree, directory, ignore_errors=True)
    return directory


def _acknowledge_no_principal_separation(test_case) -> None:
    """State what a test harness is: one account, no second principal to offer.

    The redirected registry root is a directory this process just created, so the
    custody rule refuses it — correctly, and `CustodyTests` pins that default. A test
    process has no second principal, which is exactly the case the acknowledgement
    exists for, so it says so rather than being silently exempt.

    Declared through the FILE form: the raw variable is honoured only under `BRO_ENV=ci`
    now, because an ungated environment variable that short-circuits every custody rule in
    the runtime cost the pin's own named adversary one extra `export`. A test host is not
    CI, so it declares the posture the way a production single-principal deployment does.
    """
    patcher = _self_owned_ack.patch(tempfile.mkdtemp(prefix="bro-ack-"))
    patcher.start()
    test_case.addCleanup(patcher.stop)


def _provision(directory: pathlib.Path, label: str) -> dict:
    """Mint an operator-signed registry under `directory`, the shape an install writes.

    Returns the key material, so a test can sign artifacts with the same operator key
    the registry names — which is the only way to prove that the engine read THIS
    registry rather than some other one that happens to verify.
    """
    keys = {authority: generate_key(authority, f"{label}-{authority}", False)
            for authority in ("operator-root", "builder")}
    now = int(time.time())
    (directory / "config").mkdir(parents=True, exist_ok=True)
    (directory / REGISTRY_REL).write_text(
        json.dumps(build_registry(list(keys.values()), now - 60, 86_400)),
        encoding="utf-8")
    return keys


class OverrideUnsetTests(unittest.TestCase):
    """The default: one dictionary lookup, the caller's root, nothing else touched."""

    def test_an_unset_override_returns_the_callers_root_unchanged(self) -> None:
        for root in (ROOT, pathlib.Path("relative/root"),
                     pathlib.Path("/does/not/exist")):
            with self.subTest(root=root):
                self.assertEqual(resolve_registry_root(root, env={}), root)

    def test_a_blank_override_is_the_same_as_unset(self) -> None:
        # A variable exported empty by a shell wrapper must not mean "redirect to the
        # current directory", and must not mean "refuse": it means unset.
        for blank in ("", "   ", "\t\n"):
            with self.subTest(blank=repr(blank)):
                self.assertEqual(
                    resolve_registry_root(ROOT, env={ENV_REGISTRY_ROOT: blank}), ROOT)

    def test_the_committed_registry_still_answers_when_nothing_is_set(self) -> None:
        """The behaviour every deployment has today, unchanged by this work."""
        committed = json.loads((ROOT / REGISTRY_REL).read_text(encoding="utf-8"))
        pin = committed["payload"]["operator_public_key"]
        keys = load_trusted_keys(
            ROOT, env={"BRO_OPERATOR_ROOT_PUBKEY": pin, "BRO_ENV": "ci"})
        self.assertIn("gev-operator-root-1", keys)


class ShapeTests(unittest.TestCase):
    """What may be named as a registry root at all, before custody is asked about."""

    def setUp(self) -> None:
        self.provisioned = _outside(self, "bro-prov-")
        _provision(self.provisioned, "prov")
        _acknowledge_no_principal_separation(self)

    def resolve(self, value) -> pathlib.Path:
        return resolve_registry_root(ROOT, env={ENV_REGISTRY_ROOT: str(value)})

    def test_a_well_formed_root_resolves(self) -> None:
        self.assertEqual(self.resolve(self.provisioned), self.provisioned)

    def test_a_relative_root_is_refused(self) -> None:
        with self.assertRaises(SignatureError) as caught:
            self.resolve("config")
        self.assertIn("absolute", str(caught.exception))

    def test_a_root_that_does_not_exist_is_refused(self) -> None:
        with self.assertRaises(SignatureError) as caught:
            self.resolve(self.provisioned / "nowhere")
        self.assertIn(ENV_REGISTRY_ROOT, str(caught.exception))

    def test_a_file_named_as_the_root_is_refused(self) -> None:
        with self.assertRaises(SignatureError) as caught:
            self.resolve(self.provisioned / REGISTRY_REL)
        self.assertIn("must be a directory", str(caught.exception))

    def test_a_root_holding_no_registry_is_refused_by_name(self) -> None:
        """A typo must say which file is missing, not surface later as an unreadable
        registry — the message a reader gets decides whether they fix the variable or
        start suspecting the trust chain."""
        empty = _outside(self, "bro-empty-")
        with self.assertRaises(SignatureError) as caught:
            self.resolve(empty)
        message = str(caught.exception)
        self.assertIn(REGISTRY_REL, message)
        self.assertIn("holds no", message)

    def test_a_symlinked_root_component_is_refused(self) -> None:
        external = _outside(self, "bro-linktarget-")
        _provision(external, "link")
        holder = _outside(self, "bro-linkholder-")
        link = holder / "registry"
        try:
            link.symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation not permitted: {exc}")
        with self.assertRaises(SignatureError) as caught:
            self.resolve(link)
        self.assertIn("symlink", str(caught.exception))

    def test_a_symlinked_registry_file_is_refused(self) -> None:
        """The directory can be sound while the file inside it points anywhere."""
        target = _outside(self, "bro-realreg-")
        _provision(target, "real")
        shell = _outside(self, "bro-shell-")
        (shell / "config").mkdir()
        try:
            (shell / REGISTRY_REL).symlink_to(target / REGISTRY_REL)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation not permitted: {exc}")
        with self.assertRaises(SignatureError) as caught:
            self.resolve(shell)
        self.assertIn("symlink", str(caught.exception))

    def test_the_symlink_walk_covers_every_component_on_any_host(self) -> None:
        """The walk, asked without the privilege to create a link.

        Creating a symlink needs SeCreateSymbolicLinkPrivilege on Windows, so the
        real-link tests above skip on an unelevated host — which would leave the walk
        unexercised on the platform the desktop app ships on, exactly where the
        redirect is aimed. Here the question the walk asks is answered True for one
        ANCESTOR, which also pins the property a final-component check would not have:
        an intermediate link is a redirect inside the redirect.
        """
        real = pathlib.Path.is_symlink
        marked = self.provisioned.parent

        def fake(path: pathlib.Path) -> bool:
            return path == marked or real(path)

        with patch.object(pathlib.Path, "is_symlink", fake):
            with self.assertRaises(SignatureError) as caught:
                self.resolve(self.provisioned)
        message = str(caught.exception)
        self.assertIn("symlink", message)
        self.assertIn(str(marked), message)

    def test_the_registry_file_symlink_check_is_asked_on_any_host(self) -> None:
        """Same, for the file: the registry itself is not one of the root's components,
        so a sound directory holding a linked registry needs its own question."""
        real = pathlib.Path.is_symlink
        marked = self.provisioned / REGISTRY_REL

        def fake(path: pathlib.Path) -> bool:
            return path == marked or real(path)

        with patch.object(pathlib.Path, "is_symlink", fake):
            with self.assertRaises(SignatureError) as caught:
                self.resolve(self.provisioned)
        message = str(caught.exception)
        self.assertIn("symlink", message)
        self.assertIn("may not redirect elsewhere", message)

    def test_a_directory_where_the_registry_should_be_is_refused(self) -> None:
        shell = _outside(self, "bro-dirreg-")
        (shell / REGISTRY_REL).mkdir(parents=True)
        with self.assertRaises(SignatureError) as caught:
            self.resolve(shell)
        self.assertIn("regular file", str(caught.exception))


class CustodyTests(unittest.TestCase):
    """A trust store the reading account can replace is not a trust store.

    Same verdict on both platforms, through the same `bro_custody` decision the operator
    pin (F-06) and the evidence floor (R-06) use: the directory this process just
    created is one it can rewrite, so the default REFUSES and the deployment must say
    out loud that it has no principal separation.
    """

    def setUp(self) -> None:
        self.provisioned = _outside(self, "bro-custody-")
        _provision(self.provisioned, "custody")

    def resolve(self, env_extra=None) -> pathlib.Path:
        env = {ENV_REGISTRY_ROOT: str(self.provisioned)}
        env.update(env_extra or {})
        return resolve_registry_root(ROOT, env=env)

    def test_a_root_this_account_can_rewrite_is_refused_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            for _name in _self_owned_ack.NAMES:
                os.environ.pop(_name, None)
            if os.name not in {"posix", "nt"}:
                self.skipTest(
                    f"no custody model on os.name={os.name!r}; the code refuses there "
                    "too, but for a different reason than this test asserts")
            with self.assertRaises(SignatureError) as caught:
                self.resolve()
        message = str(caught.exception)
        self.assertIn(ENV_REGISTRY_ROOT, message)
        self.assertIn(ENV_PIN_SELF_OWNED_ACK, message)
        # The refusal must name a route the reader can act on, not merely refuse.
        if os.name == "nt":
            self.assertRegex(message, r"(granted (FILE_ADD_FILE|FILE_ADD_SUBDIRECTORY|"
                                      r"FILE_DELETE_CHILD|DELETE|WRITE_DAC|WRITE_OWNER) "
                                      r"on it through .+|holds Se\w+Privilege|"
                                      r"must not be writable by non-owner principals)")
        else:
            self.assertRegex(message, r"(owned by the very account reading it|"
                                      r"has write permission on it anyway|"
                                      r"is writable by the account reading it)")

    def test_the_acknowledgement_admits_it_and_does_not_pretend_otherwise(self) -> None:
        with _self_owned_ack.patch(tempfile.mkdtemp(prefix="bro-ack-")):
            self.assertEqual(self.resolve(), self.provisioned)

    def test_the_raw_acknowledgement_is_refused_outside_ci(self) -> None:
        """The gate the two sibling anchors always had, applied to the one that escaped it.

        `BRO_OPERATOR_ROOT_PIN_SELF_OWNED` used to be an ungated read of the ambient
        environment. The adversary the pin exists to stop is one who can set the verifying
        process's environment — that is the capability the original F-06 attack already
        needed — so the fix cost it a single extra `export`. It is now honoured only when the
        CI system marked the environment, exactly like the raw operator-root pin and the raw
        registry floor, and the refusal says which form to use instead.
        """
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV_PIN_SELF_OWNED_ACK_FILE, None)
            os.environ["BRO_ENV"] = "not-ci"
            with patch.dict(os.environ,
                            {ENV_PIN_SELF_OWNED_ACK: PIN_SELF_OWNED_ACK_VALUE}):
                with self.assertRaises(SignatureError) as caught:
                    self.resolve()
        message = str(caught.exception)
        self.assertIn("honoured only in CI", message)
        self.assertIn(ENV_PIN_SELF_OWNED_ACK_FILE, message)

    def test_the_raw_acknowledgement_is_honoured_when_ci_marked_the_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV_PIN_SELF_OWNED_ACK_FILE, None)
            with patch.dict(os.environ, {ENV_PIN_SELF_OWNED_ACK: PIN_SELF_OWNED_ACK_VALUE,
                                         "BRO_ENV": "ci"}):
                self.assertEqual(self.resolve(), self.provisioned)

    def test_a_declaration_file_that_says_something_else_is_not_a_declaration(self) -> None:
        # The posture is stated in full, or not at all. Accepting any non-empty file would
        # make an unrelated file the operator happens to point at switch off every custody
        # rule in the runtime.
        declaration = pathlib.Path(tempfile.mkdtemp(prefix="bro-ack-")) / "ack"
        declaration.write_text("yes please", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV_PIN_SELF_OWNED_ACK, None)
            with patch.dict(os.environ,
                            {ENV_PIN_SELF_OWNED_ACK_FILE: str(declaration)}):
                with self.assertRaises(SignatureError) as caught:
                    self.resolve()
        self.assertIn("is not exactly", str(caught.exception))

    def test_an_unreadable_declaration_file_refuses_rather_than_reading_as_absent(self) -> None:
        # Fail closed: "the declaration cannot be read" must not silently become "there is
        # no declaration", which would surface three frames away as an unrelated custody
        # refusal about the directory.
        missing = pathlib.Path(tempfile.mkdtemp(prefix="bro-ack-")) / "never-written"
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV_PIN_SELF_OWNED_ACK, None)
            with patch.dict(os.environ, {ENV_PIN_SELF_OWNED_ACK_FILE: str(missing)}):
                with self.assertRaises(SignatureError) as caught:
                    self.resolve()
        self.assertIn("cannot be read", str(caught.exception))

    def test_a_caller_that_curates_its_mapping_can_suppress_the_acknowledgement(self) -> None:
        """The asymmetry the audit named: `_env_is_ci` took the caller's mapping, so a
        hardened caller could curate it; the acknowledgement read `os.environ` by deliberate
        design and no caller could suppress it at all."""
        import bro_custody
        with _self_owned_ack.patch(tempfile.mkdtemp(prefix="bro-ack-")):
            self.assertTrue(bro_custody.self_owned_acknowledged())
            self.assertFalse(bro_custody.self_owned_acknowledged(env={}))

    def test_a_platform_with_no_custody_model_refuses(self) -> None:
        """"No permission model here" is not "no permission requirement".

        Neither branch is reachable on posix or nt, so the refusal is asked of a
        substituted platform name rather than left as a branch nobody has ever
        executed — which is how the evidence floor's Windows no-op survived (R-06).
        """
        with patch.dict(os.environ, {}, clear=False):
            for _name in _self_owned_ack.NAMES:
                os.environ.pop(_name, None)
            with patch.object(bro_signature, "platform_name", lambda: "riscos"):
                with self.assertRaises(SignatureError) as caught:
                    self.resolve()
        message = str(caught.exception)
        self.assertIn("riscos", message)
        self.assertIn(ENV_REGISTRY_ROOT, message)
        self.assertIn(ENV_PIN_SELF_OWNED_ACK, message)

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits")
    def test_a_group_or_other_writable_root_is_refused(self) -> None:
        shared = _outside(self, "bro-shared-")
        _provision(shared, "shared")
        os.chmod(shared, 0o777)
        with patch.dict(os.environ, {}, clear=False):
            for _name in _self_owned_ack.NAMES:
                os.environ.pop(_name, None)
            with self.assertRaises(SignatureError) as caught:
                resolve_registry_root(ROOT, env={ENV_REGISTRY_ROOT: str(shared)})
        self.assertIn("writable", str(caught.exception))


class AnchorIndependenceTests(unittest.TestCase):
    """The redirect may not select its own anchor.

    The pin and the registry are two things exactly because one of them has to survive
    an attacker who can write the other. If `BRO_TRUSTED_REGISTRY_ROOT` could point at
    a tree that also contains `BRO_OPERATOR_ROOT_PUBKEY_FILE`, one variable would hand
    over both and "the registry payload is never the pin" would be decorative.
    """

    def setUp(self) -> None:
        self.provisioned = _outside(self, "bro-anchor-reg-")
        self.keys = _provision(self.provisioned, "anchor")
        self.pin = self.keys["operator-root"]["public_key"]
        _acknowledge_no_principal_separation(self)

    def resolve(self, **env_extra) -> pathlib.Path:
        env = {ENV_REGISTRY_ROOT: str(self.provisioned)}
        env.update(env_extra)
        return resolve_registry_root(ROOT, env=env)

    def test_the_pin_and_the_registry_root_cannot_be_the_same_file(self) -> None:
        """The strongest form: the pin IS the registry the redirect selects."""
        with self.assertRaises(SignatureError) as caught:
            self.resolve(**{ENV_PIN_FILE: str(self.provisioned / REGISTRY_REL)})
        message = str(caught.exception)
        self.assertIn(ENV_PIN_FILE, message)
        self.assertIn(ENV_REGISTRY_ROOT, message)
        self.assertIn("may not name its own trust anchor", message)

    def test_a_pin_anywhere_inside_the_redirected_root_is_refused(self) -> None:
        for relative in ("operator-root.pub", "config/operator-root.pub",
                         "keys/nested/operator-root.pub"):
            with self.subTest(relative=relative):
                inside = self.provisioned / relative
                inside.parent.mkdir(parents=True, exist_ok=True)
                inside.write_text(self.pin + "\n", encoding="utf-8")
                with self.assertRaises(SignatureError) as caught:
                    self.resolve(**{ENV_PIN_FILE: str(inside)})
                self.assertIn(ENV_PIN_FILE, str(caught.exception))

    def test_dot_dot_cannot_launder_a_pin_into_the_redirected_root(self) -> None:
        """A path that LEAVES the root and comes back in still lands inside it.

        `<somewhere-else>/../<root>/operator-root.pub` names a file in the redirected
        root, but none of its `parents` is the root — only normalising the path first
        reveals where it actually points. This is the form that fails without the
        normalisation, which is why it is the one asserted.
        """
        (self.provisioned / "operator-root.pub").write_text(self.pin, encoding="utf-8")
        sibling = self.provisioned.parent / (self.provisioned.name + "-sibling")
        laundered = sibling / ".." / self.provisioned.name / "operator-root.pub"
        self.assertNotIn(
            self.provisioned, pathlib.Path(str(laundered)).parents,
            "the un-normalised path was already caught; this test would then prove "
            "nothing about the normalisation it exists to pin")
        with self.assertRaises(SignatureError) as caught:
            self.resolve(**{ENV_PIN_FILE: str(laundered)})
        self.assertIn(ENV_PIN_FILE, str(caught.exception))

    def test_a_symlinked_pin_that_lands_inside_the_root_is_refused(self) -> None:
        target = self.provisioned / "operator-root.pub"
        target.write_text(self.pin + "\n", encoding="utf-8")
        elsewhere = _outside(self, "bro-anchor-link-")
        link = elsewhere / "operator-root.pub"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation not permitted: {exc}")
        with self.assertRaises(SignatureError) as caught:
            self.resolve(**{ENV_PIN_FILE: str(link)})
        self.assertIn(ENV_PIN_FILE, str(caught.exception))

    def test_the_anti_rollback_floor_may_not_live_there_either(self) -> None:
        """The floor is the other half of "this registry is the current one"."""
        floor = self.provisioned / "registry-floor.txt"
        floor.write_text("2", encoding="utf-8")
        with self.assertRaises(SignatureError) as caught:
            self.resolve(**{ENV_REGISTRY_MIN_FILE: str(floor)})
        self.assertIn(ENV_REGISTRY_MIN_FILE, str(caught.exception))

    def test_a_pin_outside_the_redirected_root_is_exactly_what_is_wanted(self) -> None:
        """The positive case, so the rule above is a boundary and not a blanket ban.

        This is the shape a provisioning install writes: the registry under one
        directory, the operator pin beside it rather than inside it.
        """
        beside = _outside(self, "bro-anchor-pin-")
        pin_file = beside / "operator-root.pub"
        pin_file.write_text(self.pin + "\n", encoding="utf-8")
        self.assertEqual(self.resolve(**{ENV_PIN_FILE: str(pin_file)}),
                         self.provisioned)


class AllCallersOrNoneTests(unittest.TestCase):
    """A redirect half the callers honour is worse than none."""

    def setUp(self) -> None:
        self.provisioned = _outside(self, "bro-allornone-")
        self.keys = _provision(self.provisioned, "allornone")
        _acknowledge_no_principal_separation(self)
        self.env = {ENV_REGISTRY_ROOT: str(self.provisioned),
                    "BRO_OPERATOR_ROOT_PUBKEY": self.keys["operator-root"]["public_key"],
                    "BRO_ENV": "ci"}

    def test_a_caller_asking_for_the_engines_own_tree_gets_the_provisioned_root(self) -> None:
        self.assertEqual(resolve_registry_root(ROOT, env=self.env), self.provisioned)
        keys = load_trusted_keys(ROOT, env=self.env)
        self.assertIn("allornone-operator-root", keys)
        self.assertNotIn("gev-operator-root-1", keys,
                         "the committed development registry answered instead")

    def test_the_default_argument_reaches_the_same_store(self) -> None:
        keys = load_trusted_keys(env=self.env)
        self.assertIn("allornone-operator-root", keys)

    def test_a_caller_naming_the_same_root_is_accepted(self) -> None:
        self.assertEqual(resolve_registry_root(self.provisioned, env=self.env),
                         self.provisioned)

    def test_a_caller_naming_a_different_root_is_refused_not_quietly_redirected(self) -> None:
        """The split-brain refusal.

        `bro_supervisor --registry`, `BROPS_REGISTRY_ROOT` and the sidecar's governance
        mirror all name a registry root of their own. In a deployment that has set the
        override, serving them a different registry from the one the hook verifies
        against — in either direction — is the failure this refusal exists to prevent.
        """
        other = _outside(self, "bro-other-")
        _provision(other, "other")
        with self.assertRaises(SignatureError) as caught:
            resolve_registry_root(other, env=self.env)
        message = str(caught.exception)
        self.assertIn(str(self.provisioned), message)
        self.assertIn(str(other), message)
        self.assertIn(ENV_REGISTRY_ROOT, message)
        # and the refusal reaches the real entry point, not only the resolver
        with self.assertRaises(SignatureError):
            load_trusted_keys(other, env=self.env)

    def test_no_module_holds_a_private_copy_of_the_loader(self) -> None:
        """Module-level `from bro_signature import load_trusted_keys` binds a reference.

        Rebinding is how a redirect silently stops applying to half the tree, so the
        modules that bind it at import time are checked to be holding the real one.
        """
        import bro_control_plane
        import bro_completion
        import bro_workspace

        for module in (bro_workspace, bro_control_plane, bro_completion):
            with self.subTest(module=module.__name__):
                self.assertIs(module.load_trusted_keys,
                              bro_signature.load_trusted_keys)


class CallSiteInventoryTests(unittest.TestCase):
    """Every place that resolves a registry root, enumerated from the source.

    The point is not the count. It is that a NEW call site cannot appear without a
    decision being recorded here about which registry it reads — which is exactly how a
    deployment ends up half-trusting two registries with nothing saying so.
    """

    # Call sites that pass the engine's own tree (`ROOT`, a `root` parameter defaulting
    # to it, or nothing at all). These honour the override automatically, because it is
    # applied inside `load_trusted_keys` rather than at each caller.
    ENGINE_TREE = frozenset({
        ("engine/runtime/bro_audit_log.py", "<default ROOT>"),
        ("engine/runtime/bro_completion.py", "root"),
        ("engine/runtime/bro_contracts.py", "root"),
        ("engine/runtime/bro_control_plane.py", "ROOT"),
        ("engine/runtime/bro_execution_lease.py", "root"),
        ("engine/runtime/bro_identity_hook.py", "ROOT"),
        ("engine/runtime/bro_policy.py", "root"),
        ("engine/runtime/bro_recovery.py", "root"),
        ("engine/runtime/bro_release_v3.py", "root"),
        ("engine/runtime/bro_workspace.py", "root"),
        ("engine/tools/bro_backup.py", "<default ROOT>"),
        ("engine/tools/bro_deploy_preflight.py", "root"),
        ("engine/tools/bro_monitor.py", "<default ROOT>"),
        ("engine/tools/bro_validate.py", "ROOT"),
        ("engine/tools/broctl.py", "root"),
    })

    # Call sites that deliberately NAME a registry root of their own, from a CLI flag or
    # an operator-set variable. With the override unset these are unchanged; with it set
    # they are refused unless they name the same root, so none of them can quietly read
    # the stale committed registry while the rest of the process reads the provisioned
    # one. `broctl inspect --registry` is in ENGINE_TREE rather than here because it
    # derives its root from the path it was given and that path is usually the engine's.
    NAMED_ROOT = frozenset({
        ("engine/tools/bro_supervisor.py", "registry_root"),
        ("engine/tools/brops_supervisor_service.py",
         "pathlib.Path(e['BROPS_REGISTRY_ROOT'])"),
        ("bridge/engine_sidecar.py", "pathlib.Path(registry)"),
    })

    AREAS = ("engine/runtime", "engine/tools", "engine/ci", "bridge")

    def call_sites(self) -> set[tuple[str, str]]:
        found: set[tuple[str, str]] = set()
        for area in self.AREAS:
            for path in sorted((REPO / area).rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    func = node.func
                    name = (func.id if isinstance(func, ast.Name) else
                            func.attr if isinstance(func, ast.Attribute) else None)
                    if name != "load_trusted_keys":
                        continue
                    if node.args:
                        argument = ast.unparse(node.args[0])
                    else:
                        keywords = {k.arg: k.value for k in node.keywords}
                        argument = (ast.unparse(keywords["root"])
                                    if "root" in keywords else "<default ROOT>")
                    found.add((path.relative_to(REPO).as_posix(), argument))
        return found

    def test_the_inventory_is_complete(self) -> None:
        found = self.call_sites()
        known = self.ENGINE_TREE | self.NAMED_ROOT
        self.assertEqual(
            found - known, set(),
            "a new registry-root call site appeared. Decide which registry it reads "
            "and add it to ENGINE_TREE (it passes the engine's own tree and therefore "
            "honours BRO_TRUSTED_REGISTRY_ROOT) or to NAMED_ROOT (it names a root of "
            "its own and is refused when that disagrees with the override)")
        self.assertEqual(
            known - found, set(),
            "a registry-root call site named here no longer exists; remove it rather "
            "than leaving the inventory describing a tree that has moved on")

    def test_the_registry_file_is_read_in_exactly_one_place(self) -> None:
        """`resolve_registry_root` is only a chokepoint while there is one reader.

        A module that joined `config/trusted-keys.json` to a root of its own and read
        it directly would bypass the redirect, the pin, the production binding and the
        rollback floor all at once — a whole second trust path, invisible to the
        inventory above because it never calls `load_trusted_keys`.
        """
        readers = set()
        for area in self.AREAS:
            for path in sorted((REPO / area).rglob("*.py")):
                source = path.read_text(encoding="utf-8")
                relative = path.relative_to(REPO).as_posix()
                for line in source.splitlines():
                    if "trusted-keys.json" not in line and "REGISTRY_REL" not in line:
                        continue
                    # a path JOIN, not a mention in prose or a refusal message
                    if ("/ REGISTRY_REL" in line or "/ \"trusted-keys.json\"" in line
                            or "/ 'trusted-keys.json'" in line
                            or "root / REGISTRY_REL" in line
                            or "\"config\" / \"trusted-keys.json\"" in line):
                        readers.add(relative)
        self.assertEqual(
            readers,
            {"engine/runtime/bro_signature.py",   # the one reader
             "engine/tools/broctl.py",            # validates the --registry spelling
             "engine/ci/gen_isolation_fixture.py"},  # writes a CI fixture
            "a module builds a registry path of its own. If it READS it, that is a "
            "second trust path around resolve_registry_root and every check behind it")


class ConductorSessionO3Tests(unittest.TestCase):
    """O-3, end to end, in both directions.

    The minted conductor-session artifact verifies perfectly — against a registry
    nothing consulted. These drive the real `verify_conductor_session_token` against the
    real engine `ROOT` (so the real, shipped `.bro/policy.json` supplies the
    requirement) and change only where the registry is read from.
    """

    def setUp(self) -> None:
        self.provisioned = _outside(self, "bro-o3-provisioned-")
        self.keys = _provision(self.provisioned, "o3prov")
        # A second, equally valid deployment. Pointing the override here must refuse the
        # token: "some registry accepted it" is not "this deployment accepted it".
        self.elsewhere = _outside(self, "bro-o3-elsewhere-")
        _provision(self.elsewhere, "o3else")
        _acknowledge_no_principal_separation(self)
        use_operator_pin(self, self.keys["operator-root"]["public_key"])
        self.token = self.provisioned.parent / "conductor-session.json"
        self.addCleanup(self.token.unlink, True)
        self.token.write_text(json.dumps(self.sign()), encoding="utf-8")

    def sign(self, authority: str = "operator-root", **overrides) -> dict:
        payload = {
            "schema": 1,
            "artifact_type": CONDUCTOR_SESSION_ARTIFACT,
            "key_id": self.keys[authority]["key_id"],
            "session_id": SESSION,
            "agent_id": CANONICAL_CONDUCTOR_ID,
            "role": CONDUCTOR_ROLE,
            "issued_at_epoch": int(time.time()) - 10,
            "expires_at_epoch": int(time.time()) + 3600,
        }
        payload.update(overrides)
        return sign_payload(self.keys[authority]["private_key"], payload)

    def verify(self, override: pathlib.Path | None) -> tuple[bool, str]:
        environment = {CONDUCTOR_SESSION_TOKEN_ENV: str(self.token)}
        with patch.dict(os.environ, environment):
            os.environ.pop(ENV_REGISTRY_ROOT, None)
            if override is not None:
                os.environ[ENV_REGISTRY_ROOT] = str(override)
            state = State("review", CONDUCTOR_ROLE, SESSION, CANONICAL_CONDUCTOR_ID)
            return verify_conductor_session_token(state, ROOT)

    def test_the_token_is_accepted_when_the_override_points_at_the_provisioned_store(self) -> None:
        ok, note = self.verify(self.provisioned)
        self.assertTrue(ok, note)
        self.assertIn("verified against the trusted-key registry", note)

    def test_the_same_token_is_refused_with_the_override_unset(self) -> None:
        """O-3 as it stands without the redirect: the committed registry answers.

        The refusal names the pin/registry disagreement, which is the proof that the
        engine read `engine/config/trusted-keys.json` — a registry signed by an operator
        key this deployment never provisioned — and not the provisioned one.
        """
        ok, note = self.verify(None)
        self.assertFalse(ok)
        self.assertIn("RED", note)
        self.assertIn("does not match the external operator pin", note)

    def test_the_same_token_is_refused_when_the_override_points_elsewhere(self) -> None:
        """A registry that is operator-signed, current and well-formed — just not this
        deployment's. Redirecting is not the same as accepting whatever it finds."""
        ok, note = self.verify(self.elsewhere)
        self.assertFalse(ok)
        self.assertIn("RED", note)

    def test_a_token_the_provisioned_registry_does_not_authorise_is_still_refused(self) -> None:
        """The redirect moves WHERE trust is read, never WHAT it permits: the builder
        key is in the very registry the override selects and still may not speak for
        the conductor's identity."""
        self.token.write_text(
            json.dumps(self.sign("builder", key_id=self.keys["builder"]["key_id"])),
            encoding="utf-8")
        ok, note = self.verify(self.provisioned)
        self.assertFalse(ok)
        self.assertIn("RED", note)


if __name__ == "__main__":
    unittest.main()
