"""`engine/ci/live/write_broker_config.py` — the first writer of a `$BROPS_BROKER_CONFIG` document.

Two kinds of test, and the first kind is the point.

**The mirrors are bound to the Rust.** The writer carries three lists that belong to the broker: the
twenty-five configuration keys `build_governed_executor` reads, the §2.5 artifact roster the floor
demands, and the four `sidecar` rules `SidecarPrincipal::from_config` enforces. Each is a copy of a
Rust constant that Python cannot see, and this repository has now found the same
duplicate-implementation defect often enough to know what an unchecked copy becomes. So these tests
extract the constants out of the Rust source and compare them BOTH ways: a key added on either side
and not the other fails here, in seconds, on any platform.

**Every refusal is exercised.** The writer refuses fourteen ways, and each refusal exists because the
same condition, reached at broker start-up instead, renders as one indistinguishable `blocked` reply.
A refusal that is never tested is a refusal that can be deleted without anything turning red — and
the value of the whole file is that it turns an unreadable `blocked` into a named key.
"""

from __future__ import annotations

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
# Derived from the engine tree rather than spelled REPO_ROOT/engine: the writer ships INSIDE engine/,
# so it is present wherever the engine is, including a deployed tree in which engine/ is the root.
WRITER = os.path.join(ENGINE_ROOT, "ci", "live", "write_broker_config.py")

TAURI = os.path.join(REPO_ROOT, "apps", "desktop", "src-tauri")
PREFLIGHT_RS = os.path.join(TAURI, "broker", "src", "preflight.rs")
TCB_INTEGRITY_RS = os.path.join(TAURI, "core", "src", "tcb_integrity.rs")
SIDECAR_RS = os.path.join(TAURI, "core", "src", "governed_sidecar.rs")

from _prerequisites import DESKTOP_BROKER_CONTRACT_SOURCE, requires  # noqa: E402


def writer_module():
    """Import the writer as a module, for the constants and the extractor it owns."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("brops_write_broker_config", WRITER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class BoundToTheRustTests(unittest.TestCase):
    """The three mirrors, held against the constants they mirror."""

    def test_the_key_set_is_the_brokers_own(self):
        module = writer_module()
        rust = module.rust_string_list(
            read(PREFLIGHT_RS), "CONFIG_KEYS_READ_BY_BUILD_GOVERNED_EXECUTOR")
        self.assertEqual(
            sorted(rust), sorted(module.BROKER_READ_KEYS),
            "BROKER_READ_KEYS and preflight.rs::CONFIG_KEYS_READ_BY_BUILD_GOVERNED_EXECUTOR "
            "disagree. The Rust list is the contract; whichever side is behind, this writer must "
            "produce exactly what build_governed_executor reads")
        self.assertEqual(len(rust), 25, "the read set moved; the writer's docstring cites 25")

    def test_the_tcb_roster_is_the_floors_own(self):
        module = writer_module()
        rust = module.rust_string_list(read(TCB_INTEGRITY_RS), "TCB_REQUIRED_ARTIFACTS")
        self.assertEqual(
            sorted(rust), sorted(module.TCB_REQUIRED_ARTIFACTS),
            "the writer's coverage check would pass a manifest verify_tcb_integrity refuses, or "
            "refuse one it accepts")

    def test_the_sidecar_rules_are_the_brokers_own(self):
        module = writer_module()
        source = read(SIDECAR_RS)

        def string_const(name):
            match = re.search(
                r"pub const " + name + r':\s*&str\s*=\s*"([^"]*)"\s*;', source)
            self.assertIsNotNone(match, "no `pub const %s: &str` in governed_sidecar.rs" % name)
            return match.group(1)

        def usize_const(name):
            match = re.search(r"pub const " + name + r"\s*:\s*usize\s*=\s*(\d+)\s*;", source)
            self.assertIsNotNone(match, "no `pub const %s: usize` in governed_sidecar.rs" % name)
            return int(match.group(1))

        self.assertEqual(string_const("PRINCIPAL_KEY"), module.PRINCIPAL_KEY)
        self.assertEqual(string_const("INVOKER_KEY"), module.INVOKER_KEY)
        self.assertEqual(string_const("ENV_PROGRAM"), module.ENV_PROGRAM)
        self.assertEqual(usize_const("MIN_INVOKER_TOKENS"), module.MIN_INVOKER_TOKENS)

    def test_the_extractor_refuses_a_constant_that_is_not_there(self):
        """The binding is only as good as the extractor failing loudly. A silent empty list would
        make every comparison above pass against nothing."""
        module = writer_module()
        with self.assertRaises(ValueError):
            module.rust_string_list("fn main() {}", "CONFIG_KEYS_READ_BY_BUILD_GOVERNED_EXECUTOR")

    def test_the_extractor_drops_commented_out_literals(self):
        """`TCB_REQUIRED_ARTIFACTS` carries `// ---- ... ----` section headers between its entries,
        and a comment that happened to contain a quoted word would otherwise become a required
        artifact."""
        module = writer_module()
        source = (
            'pub const X: &[&str] = &[\n'
            '    // a "commented" name\n'
            '    "real",\n'
            '];\n'
        )
        self.assertEqual(module.rust_string_list(source, "X"), ["real"])


@requires(DESKTOP_BROKER_CONTRACT_SOURCE)
class BoundToTheRustSourceTests(BoundToTheRustTests):
    """The same assertions, skipped (or failed under CI) where the Rust tree is not beside engine/.

    Declared as a subclass rather than a decorator on the class above so that the prerequisite is
    what gates them: `engine/.github/workflows/verify.yml` runs with engine/ as the root and has no
    apps/desktop at all.
    """


del BoundToTheRustTests  # only the gated subclass runs


class Deployment:
    """A complete, minimal provisioned deployment on disk — the inputs, none of the behaviour."""

    def __init__(self, root, module):
        self.root = root
        self.module = module
        self.tcb = os.path.join(root, "tcb")
        os.makedirs(self.tcb)
        os.makedirs(os.path.join(root, "sandbox"))

        self.base_config = os.path.join(root, "config.json")
        self.write_base()

        self.messages_db = self._file("messages.db", "not really sqlite, and never opened here")
        self.floor = self._file("floor.json", '{"highest_epoch":1,"highest_hash":"ab"}')
        self.system_file = self._file("system.txt", "You are Bro.\nSecond line.\n")
        self.python = self._file("python3", "#!/bin/sh\n")
        self.script = self._file("engine_sidecar.py", "# front door\n")
        self.pin_manifest = os.path.join(self.tcb, "tcb-pin.json")
        self.write_pin_manifest()

    def _file(self, name, content):
        # BINARY, deliberately. Text mode translates "\n" to "\r\n" on Windows, and the writer reads
        # the system prompt as bytes and decodes them — which is the contract, because every digest
        # the ladder derives from that prompt moves if one byte does. A fixture written in text mode
        # would have this test asserting about the fixture's line endings rather than the writer's
        # fidelity.
        path = os.path.join(self.root, name)
        with open(path, "wb") as handle:
            handle.write(content.encode("utf-8"))
        return path

    def write_base(self, **override):
        base = {
            "uids": {"broker": 501, "sidecar": 507},
            "sockets": {"authority": os.path.join(self.root, "authority.sock"),
                        "supervisor": os.path.join(self.root, "supervisor.sock")},
            "trust": {
                "manifest_path": os.path.join(self.tcb, "key-manifest.json"),
                "manifest_sig_path": os.path.join(self.tcb, "key-manifest.sig"),
                "signer_key_id": "signer-1",
                "supervisor_attestation_key_id": "sup-attest-1",
            },
            "resolved": {
                "workspace_id": "ws-1", "install_id": "install-1",
                "system_sha256": "a" * 64, "history_sha256": "b" * 64,
                "generation_config_sha256": "c" * 64,
                "requested_at": "2026-09-21T00:00:00Z", "requested_at_ms": 1789000000000,
                "run_id": "run-1", "task_id": "task-1", "author": "Bro",
            },
            # Not in the read set, and the whole reason the writer copies by ALLOWLIST: whatever
            # else a provisioned config holds stays in that file.
            "store": {"private_note": "this must not travel into the broker config"},
        }
        base.update(override)
        with open(self.base_config, "w", encoding="utf-8") as handle:
            json.dump(base, handle, indent=2)
        return base

    def write_pin_manifest(self, *, drop=(), owner_uids=None):
        artifacts = [
            {"logical_name": name, "path": os.path.join(self.tcb, name),
             "expected_sha256": "d" * 64, "expected_owner": "root"}
            for name in self.module.TCB_REQUIRED_ARTIFACTS if name not in drop
        ]
        document = {"artifacts": artifacts,
                    "owner_uids": {"root": 0} if owner_uids is None else owner_uids}
        with open(self.pin_manifest, "w", encoding="utf-8") as handle:
            json.dump(document, handle)

    def argv(self, **override):
        args = {
            "--base-config": self.base_config,
            "--out": os.path.join(self.root, "broker-config.json"),
            "--messages-db": self.messages_db,
            "--system-file": self.system_file,
            "--window": "8",
            "--floor-path": self.floor,
            "--tcb-pin-manifest": self.pin_manifest,
            "--sidecar-python": self.python,
            "--sidecar-script": self.script,
            "--sidecar-cwd": os.path.join(self.root, "sandbox"),
            "--sidecar-principal": "brops-sidecar",
        }
        invoker = override.pop("invoker", ["/usr/bin/sudo", "-n", "-u", "brops-sidecar",
                                          "/usr/bin/env"])
        # A JSON array in ONE argument, exactly as the writer takes it: the prefix's own `-n` / `-u`
        # tokens would otherwise be read as options by the argument parser.
        args["--sidecar-invoker"] = (invoker if isinstance(invoker, str)
                                     else json.dumps(invoker))
        args.update({k: v for k, v in override.items() if v is not None})
        flat = []
        for key, value in args.items():
            flat += [key, str(value)]
        return flat

    @property
    def out(self):
        return os.path.join(self.root, "broker-config.json")


class WriterBehaviourTests(unittest.TestCase):
    def setUp(self):
        self.module = writer_module()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dep = Deployment(os.path.join(self._tmp.name, "opt"), self.module)

    def run_writer(self, **override):
        return subprocess.run(
            [sys.executable, WRITER] + self.dep.argv(**override),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONUTF8": "1"})

    def expect_refusal(self, fragment, **override):
        done = self.run_writer(**override)
        self.assertEqual(done.returncode, 1,
                         "expected a refusal; got %d\n%s\n%s"
                         % (done.returncode, done.stdout, done.stderr))
        self.assertIn(fragment, done.stderr)
        self.assertFalse(os.path.exists(self.dep.out),
                         "a refused run must leave no document: a half-written config is one an "
                         "operator can still export")
        return done

    # ---- the happy path ------------------------------------------------------------------------

    def test_a_complete_deployment_produces_every_key_the_broker_reads(self):
        done = self.run_writer()
        self.assertEqual(done.returncode, 0, done.stderr)
        document = json.loads(read(self.dep.out))
        missing = [key for key in self.module.BROKER_READ_KEYS
                   if self.module.get_dotted(document, key) is None]
        self.assertEqual(missing, [], "build_governed_executor would read None out of these")

    def test_the_system_prompt_travels_as_bytes_not_as_an_argv_token(self):
        """`content.system` is multi-line by nature and every digest derived from it moves if a
        newline is lost, which is why the writer takes a FILE."""
        self.run_writer()
        document = json.loads(read(self.dep.out))
        self.assertEqual(document["content"]["system"], "You are Bro.\nSecond line.\n")

    def test_nothing_outside_the_allowlist_travels_out_of_the_base_config(self):
        """The base config holds a `store` block. A wholesale copy would carry it — and one day a
        secret — into a document written for a different reader."""
        self.run_writer()
        document = json.loads(read(self.dep.out))
        self.assertNotIn("store", document)
        self.assertEqual(sorted(document), ["content", "resolved", "sidecar", "sockets", "trust",
                                            "uids"])

    def test_the_socket_the_broker_must_not_dial_is_not_copied(self):
        """`sockets.supervisor` is in the base config and is deliberately NOT in the read set: on
        the ladder the broker speaks to the challenge authority only, and a path it holds is a path
        it could use."""
        self.run_writer()
        document = json.loads(read(self.dep.out))
        self.assertEqual(sorted(document["sockets"]), ["authority"])

    def test_emit_prints_exactly_the_bytes_it_wrote(self):
        # `--emit` is a flag, and the argv helper pairs every key with a value, so it is appended
        # here rather than passed through that helper.
        done = subprocess.run(
            [sys.executable, WRITER] + self.dep.argv() + ["--emit"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONUTF8": "1"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(read(self.dep.out), done.stdout)

    def test_the_report_names_the_variable_an_operator_has_to_export(self):
        done = self.run_writer()
        self.assertIn("export BROPS_BROKER_CONFIG=", done.stdout)
        self.assertIn("does NOT open a governed surface", done.stdout)

    # ---- the refusals --------------------------------------------------------------------------

    def test_a_base_config_missing_a_read_key_is_refused_by_name(self):
        base = self.dep.write_base()
        del base["resolved"]["run_id"]
        with open(self.dep.base_config, "w", encoding="utf-8") as handle:
            json.dump(base, handle)
        self.expect_refusal("resolved.run_id")

    def test_a_base_config_carrying_an_inline_root_anchor_is_refused(self):
        base = self.dep.write_base()
        base["trust"]["root_pub_hex"] = "e" * 64
        with open(self.dep.base_config, "w", encoding="utf-8") as handle:
            json.dump(base, handle)
        self.expect_refusal("trust.root_pub_hex")

    def test_an_inline_root_key_id_is_refused_too(self):
        base = self.dep.write_base()
        base["trust"]["root_key_id"] = "root-2026"
        with open(self.dep.base_config, "w", encoding="utf-8") as handle:
            json.dump(base, handle)
        self.expect_refusal("trust.root_key_id")

    def test_an_unreadable_base_config_is_refused(self):
        self.expect_refusal("not readable",
                            **{"--base-config": os.path.join(self.dep.root, "absent.json")})

    def test_a_base_config_that_is_not_json_is_refused(self):
        with open(self.dep.base_config, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.expect_refusal("not valid JSON")

    def test_an_empty_system_prompt_is_refused(self):
        empty = os.path.join(self.dep.root, "empty.txt")
        open(empty, "w", encoding="utf-8").close()
        self.expect_refusal("is empty", **{"--system-file": empty})

    def test_a_non_positive_window_is_refused(self):
        self.expect_refusal("window", **{"--window": "0"})

    def test_a_messages_db_that_is_not_there_is_refused(self):
        self.expect_refusal("--messages-db",
                            **{"--messages-db": os.path.join(self.dep.root, "gone.db")})

    def test_a_floor_path_that_is_not_there_is_refused(self):
        self.expect_refusal("--floor-path",
                            **{"--floor-path": os.path.join(self.dep.root, "gone.json")})

    def test_a_sandbox_that_is_not_a_directory_is_refused(self):
        self.expect_refusal("--sidecar-cwd", **{"--sidecar-cwd": self.dep.messages_db})

    def test_an_empty_sidecar_principal_is_refused(self):
        self.expect_refusal("sidecar.principal", **{"--sidecar-principal": "   "})

    def test_an_invoker_shorter_than_the_minimum_is_refused(self):
        self.expect_refusal("tokens", invoker=["/usr/bin/sudo", "-u", "/usr/bin/env"])

    def test_a_relative_invoker_program_is_refused(self):
        self.expect_refusal(
            "not an absolute path",
            invoker=["sudo", "-n", "-u", "brops-sidecar", "/usr/bin/env"])

    def test_an_invoker_that_does_not_end_in_env_is_refused(self):
        self.expect_refusal(
            "rather than `env`",
            invoker=["/usr/bin/sudo", "-n", "-u", "brops-sidecar", "/usr/bin/python3"])

    def test_an_invoker_that_never_names_the_account_is_refused(self):
        """The §2.6 collapse: a prefix that does not change principal spawns the sidecar as the
        broker, which the supervisor refuses outright."""
        self.expect_refusal(
            "never names the account",
            invoker=["/usr/bin/sudo", "-n", "-u", "root", "/usr/bin/env"])

    def test_the_account_standing_where_env_must_stand_is_refused(self):
        """Position matters at the END: the last token is `env`, so an account whose only
        occurrence is there has not changed principal even though the string is present.

        The account is spelled `/usr/bin/env` so that the occurrence is an EXACT match — the rule is
        string equality, and a near-miss would make this test pass for the wrong reason. That is not
        hypothetical: the first version of the test below used `/brops-sidecar` against the account
        `brops-sidecar`, which never matched at all, and a mutant that let the account stand
        anywhere survived it.
        """
        self.expect_refusal(
            "never names the account",
            **{"--sidecar-principal": "/usr/bin/env",
               "invoker": ["/usr/bin/sudo", "-n", "-u", "someone", "/usr/bin/env"]})

    def test_the_account_as_the_program_is_refused(self):
        """At index 0 the account name is the PROGRAM, not an argument to one; `invoker[1..last]` is
        the only window in which it changes principal.

        The account is spelled `/usr/bin/sudo` for the same reason as above: it has to be exactly
        `invoker[0]`, and it has to be absolute or the earlier rule refuses first and this one is
        never reached.
        """
        self.expect_refusal(
            "never names the account",
            **{"--sidecar-principal": "/usr/bin/sudo",
               "invoker": ["/usr/bin/sudo", "-n", "-u", "someone", "/usr/bin/env"]})

    def test_an_under_covering_pin_manifest_is_refused_and_names_the_gap(self):
        self.dep.write_pin_manifest(drop=("trusted-verifier-broker.bin",))
        done = self.expect_refusal("does not cover")
        self.assertIn("trusted-verifier-broker.bin", done.stderr)

    def test_a_pin_manifest_with_no_owner_uids_is_refused(self):
        self.dep.write_pin_manifest(owner_uids={})
        self.expect_refusal("owner_uids")

    def test_a_pin_manifest_that_is_not_there_is_refused(self):
        self.expect_refusal(
            "not readable",
            **{"--tcb-pin-manifest": os.path.join(self.dep.tcb, "absent.json")})

    def test_a_pin_manifest_with_no_artifacts_array_is_refused(self):
        with open(self.dep.pin_manifest, "w", encoding="utf-8") as handle:
            json.dump({"owner_uids": {"root": 0}}, handle)
        self.expect_refusal("no `artifacts` array")

    def test_a_pin_manifest_is_read_before_its_path_is_written_down(self):
        """The ordering IS the property: a writer that emitted the document and then checked would
        leave a config on disk naming a manifest it had just refused."""
        self.dep.write_pin_manifest(drop=("key-manifest.root-anchor",))
        self.expect_refusal("does not cover")
        self.assertFalse(os.path.exists(self.dep.out))


class TheTreeStillWritesNoConfigForTheProductTests(unittest.TestCase):
    """The claim fifty places in this repository make, kept true by measurement.

    The refusal `build_governed_executor` takes is not that no code CAN write the document — this
    file writes it — but that nothing the product ships does. These assert the precise version: the
    writer lives in the operator-run live kit, and no crate of the desktop application sets the
    variable or calls it.
    """

    def test_the_writer_is_not_reachable_from_any_desktop_crate(self):
        if not os.path.isdir(TAURI):
            self.skipTest("apps/desktop/src-tauri is not beside the engine tree")
        hits = []
        for current, dirs, files in os.walk(TAURI):
            dirs[:] = [d for d in dirs if d not in ("target", "node_modules")]
            for name in files:
                if not name.endswith(".rs"):
                    continue
                path = os.path.join(current, name)
                source = read(path)
                if "write_broker_config" in source:
                    hits.append(os.path.relpath(path, REPO_ROOT))
                if re.search(r'set_var\s*\(\s*"BROPS_BROKER_CONFIG"', source):
                    hits.append(os.path.relpath(path, REPO_ROOT) + " (set_var)")
        self.assertEqual(hits, [],
                         "a desktop crate now reaches the deployment-config writer or sets the "
                         "variable; the fail-closed claim in README.md, CLAUDE.md, START_HERE.md "
                         "and config/spec-conformance.json would then be false")

    def test_the_writer_never_takes_a_private_key(self):
        """There is no argument, and no file read, through which a root seed could enter this
        document. The security boundary is that the Builder's tooling never handles the private
        half — see docs/OWNER_ACTION_REQUIRED.md."""
        source = read(WRITER)
        for forbidden in ("seed", "private", "gen_private", "SigningKey"):
            self.assertNotIn(
                '"--%s' % forbidden, source,
                "an argument named for the private half appeared in the writer")
        self.assertNotIn("root_seed", source)


if __name__ == "__main__":
    unittest.main()
