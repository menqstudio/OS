"""The live kit's ROOT TRUST ANCHOR must state its provenance (audit F-17), and only one exists.

The kit used to mint a root keypair, sign the production ``KeyManifest`` with it, and hand the
matching public key back to the verifier through the same ``config.json`` the verifier read its
own knobs from. That verifies perfectly and proves nothing: the kit supplied both sides of the
signature. These tests pin the properties that make the difference visible rather than assumed —
the anchor lives in a separate TCB file that says which case it is, the self-certifying inline form
cannot be re-expressed by editing config, and a file that CLAIMS outside custody is refused.

There is no outside-anchor mode to test. The Owner decided on 2026-08-09 (#78) that the install
mints trust and no person carries a key; the offline-root ceremony later rebuilt for the broker was
removed in T-130, and the tests below hold that it stays removed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)
ENGINE_ROOT = os.path.dirname(TESTS_DIR)
REPO_ROOT = os.path.dirname(ENGINE_ROOT)
# Derived from the engine tree, not spelled REPO_ROOT/"engine": the kit ships INSIDE engine/, so
# it is present wherever the engine is, whatever the directory above it is called.
LIVE_DIR = os.path.join(ENGINE_ROOT, "ci", "live")
PROVISION = os.path.join(LIVE_DIR, "provision_keys.py")

from _kit_scripts import heredoc as _heredoc  # noqa: E402
from _kit_scripts import script as _script  # noqa: E402
from _kit_scripts import shell_function as _shell_function  # noqa: E402
from _prerequisites import DESKTOP_ANCHOR_REFUSAL_SOURCE, requires  # noqa: E402

SHA_A = "aa" * 32
SHA_B = "bb" * 32


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _provision(root: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, PROVISION, "--root-dir", root,
         "--launcher-sha", SHA_A, "--executor-sha", SHA_B, *extra],
        capture_output=True, text=True,
    )


class LiveProvisioningAnchorTests(unittest.TestCase):
    def test_the_kit_labels_its_own_anchor_as_kit_generated(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(_provision(root).returncode, 0)
            anchor = _read_json(os.path.join(root, "tcb", "root-anchor.json"))
            self.assertEqual(anchor["provenance"], "kit_generated")
            self.assertEqual(len(anchor["public_key_hex"]), 64)

    def test_the_config_cannot_carry_the_anchor_inline(self):
        # The driver refuses a config with an inline anchor, so the provisioner must not write one:
        # if both existed, "which one wins" would be a question again.
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(_provision(root).returncode, 0)
            trust = _read_json(os.path.join(root, "config.json"))["trust"]
            self.assertNotIn("root_pub_hex", trust)
            self.assertNotIn("root_key_id", trust)
            self.assertTrue(trust["root_anchor_path"].endswith("root-anchor.json"))

    def test_the_provisioner_takes_no_outside_anchor(self):
        # Each of these flags existed to carry an offline root's manifest in or out. argparse refuses
        # an unknown flag with exit 2, which is the proof they are gone rather than ignored.
        for flag in ("--root-anchor-key-id", "--root-anchor-pub-hex", "--manifest-in",
                     "--manifest-sig-in", "--emit-manifest", "--keys-in"):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as root:
                r = _provision(root, flag, "x")
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertFalse(os.path.exists(os.path.join(root, "config.json")))


class KitScriptTests(unittest.TestCase):
    """The two orchestrators: they parse, read no anchor from the environment, and refuse a claim."""

    def test_every_live_shell_script_parses(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash on this host, so syntax cannot be checked here")
        scripts = sorted(f for f in os.listdir(LIVE_DIR) if f.endswith(".sh"))
        self.assertGreaterEqual(len(scripts), 2, scripts)
        for name in scripts:
            with self.subTest(script=name):
                r = subprocess.run([bash, "-n", os.path.join(LIVE_DIR, name)],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{name}: {r.stderr}")

    def test_neither_kit_reads_an_anchor_from_the_environment(self):
        for name in ("run_live_turn.sh", "run_ladder_turn.sh"):
            script = _script(name)
            for var in ("BROPS_KEYS_IN", "BROPS_ROOT_ANCHOR_KEY_ID", "BROPS_ROOT_ANCHOR_PUB_HEX",
                        "BROPS_MANIFEST_IN", "BROPS_MANIFEST_SIG_IN", "BROPS_REGISTRY_SIG_IN"):
                with self.subTest(script=name, var=var):
                    self.assertNotIn(var, script)

    @requires(DESKTOP_ANCHOR_REFUSAL_SOURCE)
    def test_the_throwaway_negative_names_the_refusal_the_driver_actually_emits(self):
        # The ladder kit relabels its own root `external` and expects the driver to refuse it. The
        # outcome string is built from two languages: `setup_blocked` prefixes `root_anchor_` to the
        # reason `check_declared_external_anchor` returns. A rename on either side would leave the
        # kit expecting an outcome nothing produces.
        script = _script("run_ladder_turn.sh")
        self.assertIn("run_driver throwaway-external", script)
        self.assertIn("blocked:setup:root_anchor_external_not_the_pinned_root", script)
        tcb = os.path.join(REPO_ROOT, "apps", "desktop", "src-tauri", "broker", "src", "tcb.rs")
        with open(tcb, "r", encoding="utf-8") as f:
            self.assertIn('Err("external_not_the_pinned_root")', f.read())
        for driver in ("ladder_turn.rs", "live_turn.rs"):
            path = os.path.join(REPO_ROOT, "apps", "desktop", "src-tauri", "proof", "src", "bin",
                                driver)
            with self.subTest(driver=driver), open(path, "r", encoding="utf-8") as f:
                text = f.read()
                self.assertIn("check_declared_external_anchor", text)
                self.assertIn('format!("root_anchor_{why}")', text)

    @requires(DESKTOP_ANCHOR_REFUSAL_SOURCE)
    def test_the_install_minted_negative_names_the_refusal_the_driver_actually_emits(self):
        # T-131 slice C. `install_minted` is the one provenance that can ever support a production
        # claim, so a driver must not take it from an anchor file that is merely root-owned: the
        # kit relabels its own root, puts it OUTSIDE the pinned path, and expects a refusal. The
        # outcome string is built in two languages here too, and BOTH drivers must make the check —
        # with the real floor question, not a closure that answers `Ok`.
        script = _script("run_ladder_turn.sh")
        self.assertIn("run_driver throwaway-install-minted", script)
        self.assertIn("blocked:setup:root_anchor_install_minted_not_floor_pinned", script)
        tauri = os.path.join(REPO_ROOT, "apps", "desktop", "src-tauri")
        with open(os.path.join(tauri, "broker", "src", "tcb.rs"), "r", encoding="utf-8") as f:
            self.assertIn('"install_minted_not_floor_pinned"', f.read())
        for driver in ("ladder_turn.rs", "live_turn.rs"):
            path = os.path.join(tauri, "proof", "src", "bin", driver)
            with self.subTest(driver=driver), open(path, "r", encoding="utf-8") as f:
                text = f.read()
                self.assertEqual(
                    text.count("brops_broker::tcb::check_declared_install_minted_anchor("), 1)
                call = text.split("brops_broker::tcb::check_declared_install_minted_anchor(")[1]
                call = call.split('format!("root_anchor_{why}")')[0]
                self.assertIn("crate::tcb_verify::anchor_is_floor_pinned(", call)
                # The bytes handed to the floor question are the bytes this driver PARSED.
                self.assertIn("anchor_raw", call)
                # ...and a refusal is a refusal: the next thing after the check is the blocked exit.
                self.assertRegex(
                    call, r"\}\)\s*\{\s*return (setup_blocked\(&evidence, expect, |blocked\()&$")
        with open(os.path.join(tauri, "proof", "src", "tcb_verify.rs"), "r", encoding="utf-8") as f:
            shared = f.read()
        self.assertIn("brops_broker::tcb_probe::anchor_bytes_are_floor_pinned(", shared)

    @requires(DESKTOP_ANCHOR_REFUSAL_SOURCE)
    def test_the_product_broker_phase_names_a_committed_demonstration_turn_and_never_production(self):
        # The phase used to assert `blocked/upstream_blocked` BECAUSE the kit root was not the
        # compiled pin. The broker now verifies the kit's manifest under the kit's own floor-pinned
        # anchor, so the expected outcome is named: committed, labelled `demonstration_custody`,
        # with `trusted_verified` a RED of its own. A check weakened to "any outcome" fails here.
        script = _script("run_ladder_turn.sh")
        self.assertIn('r.get("status") == "committed"', script)
        self.assertIn('and label == "demonstration_custody"', script)
        self.assertIn('if label == "trusted_verified":', script)
        # The product positive is judged by the committed verdict, against the anchor the product
        # manifest pins, and no longer by the blocked check.
        lines = script.splitlines()
        self.assertIn('broker_expect_committed product kit_generated "$TCB/root-anchor.json"', lines)
        self.assertNotIn("reply_is_blocked_upstream product", script)
        # The floor-refusal negative keeps the blocked check.
        self.assertIn("reply_is_blocked_upstream ladder-pin", script)
        # The relabel control: the same deployment, the anchor's one word changed and PINNED —
        # started over ITS config and judged against ITS anchor.
        self.assertIn('run_broker install-minted "$BROKER_CONFIG_IM"', lines)
        self.assertIn(
            'broker_expect_committed install-minted install_minted "$BROKER_ANCHOR_IM"', lines)
        self.assertIn('anchor["provenance"] = "install_minted"', script)
        # Each verdict follows its own run, with nothing between them.
        for run, verdict in (
                ('run_broker product "$BROKER_CONFIG"',
                 'broker_expect_committed product kit_generated "$TCB/root-anchor.json"'),
                ('run_broker install-minted "$BROKER_CONFIG_IM"',
                 'broker_expect_committed install-minted install_minted "$BROKER_ANCHOR_IM"')):
            self.assertEqual(lines.index(verdict), lines.index(run) + 1, run)
        # The stderr line the kit greps is the line the broker prints, in two languages.
        self.assertIn(
            'grep -qF "provenance=$2 read from the floor-pinned $3; production custody claim '
            'supported: false"', script)
        main_rs = os.path.join(REPO_ROOT, "apps", "desktop", "src-tauri", "broker", "src", "main.rs")
        with open(main_rs, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn(
            '"brops-broker: root anchor {} provenance={} read from the floor-pinned {}; \\\n'
            '             production custody claim supported: {}",', text)
        # Both completing broker turns wait for the §2.4 budget the way the third driver turn does.
        self.assertEqual(script.count('wait_for_staging_reclaim "brops-broker '), 2)
        self.assertEqual(script.count('wait_for_turn_slot "brops-broker '), 2)

    def test_the_relabelled_broker_deployment_is_pinned_before_any_service_starts(self):
        # A pin is a start-time measurement: the relabelled anchor, its config and its manifest are
        # all written before the first `start_service`, and the manifest is derived AFTER the
        # product manifest it copies.
        lines = _script("run_ladder_turn.sh").splitlines()

        def first(needle: str) -> int:
            hits = [i for i, l in enumerate(lines) if needle in l]
            self.assertTrue(hits, "no line in run_ladder_turn.sh contains %r" % needle)
            return hits[0]

        anchor = first("<<'PYBROKERIM'")
        product_pin = first('--kit broker --broker-config "$BROKER_CONFIG"')
        derived = first("<<'PYPINIM'")
        owned = first('chown 0:0 "$BROKER_PIN_IM"; chmod 0644 "$BROKER_PIN_IM"')
        start = [i for i, l in enumerate(lines) if l.lstrip().startswith('start_service "$')][0]
        self.assertLess(anchor, product_pin)
        self.assertLess(product_pin, derived)
        self.assertLess(derived, owned)
        self.assertLess(owned, start)


@unittest.skipUnless(os.name == "posix" and shutil.which("bash") and shutil.which("python3"),
                     "the kit's verdict functions are bash calling python3; this host has not both")
class KitBrokerVerdictTests(unittest.TestCase):
    """`broker_expect_committed`, EXECUTED: the kit's verdict on a product-broker turn.

    The three shell functions are lifted out of `run_ladder_turn.sh` verbatim and run in bash
    against a log and a reply this test writes. So the outcome the kit names — committed,
    `demonstration_custody`, the anchor read from the pinned path, never production — is checked as
    behaviour, not as text. What it cannot check is that a real broker produces that log and reply.
    """

    PROVISIONED = "trusted manifest provisioned - serving the 4.10(g) governed ladder"
    ANCHOR = "/opt/brops-live/tcb/root-anchor.json"

    def setUp(self):
        script = _script("run_ladder_turn.sh")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = self.tmp.name
        self.functions = "".join(_shell_function(script, name) for name in (
            "broker_read_anchor", "reply_is_committed_demonstration", "broker_expect_committed"))
        # The kit's own definition of the line it greps for, not a copy of it.
        declared = [l for l in script.splitlines() if l.startswith("BROKER_PROVISIONED=")]
        self.assertEqual(declared, ["BROKER_PROVISIONED='%s'" % self.PROVISIONED])

    def log(self, provenance="kit_generated", anchor=None, supported="false", provisioned=True,
            extra=""):
        text = ("brops-broker: root anchor brops-live-root-1 provenance=%s read from the "
                "floor-pinned %s; production custody claim supported: %s\n"
                % (provenance, anchor or self.ANCHOR, supported))
        if provisioned:
            text += "brops-broker: %s\n" % self.PROVISIONED
        return text + extra

    def reply(self, status="committed", trust_state="demonstration_custody"):
        document = {"protocol": "brops.renderer-governed-turn-result.v1", "status": status,
                    "client_request_id": "c", "broker_turn_id": "b", "conversation_id": "k"}
        if status == "committed":
            document["message"] = {"message_id": "m", "author": "Bro", "body": "hello",
                                   "created_at_ms": 1, "trust_state": trust_state}
        else:
            document["reason"] = "upstream_blocked"
        return document

    def verdict(self, log, reply, provenance="kit_generated"):
        with open(os.path.join(self.run_dir, "t.log"), "w", encoding="utf-8") as fh:
            fh.write(log)
        with open(os.path.join(self.run_dir, "t.reply.json"), "w", encoding="utf-8") as fh:
            json.dump(reply, fh)
        driver = os.path.join(self.run_dir, "verdict.sh")
        with open(driver, "w", encoding="utf-8") as fh:
            fh.write("set -u\nBROKER_RUN=%s\nBROKER_PROVISIONED='%s'\nBROKER_PRODUCT_RC=0\n"
                     % (self.run_dir, self.PROVISIONED))
            fh.write(self.functions)
            fh.write('broker_expect_committed t %s "%s"\n' % (provenance, self.ANCHOR))
            fh.write('echo "RC=$BROKER_PRODUCT_RC"\n')
        done = subprocess.run(["bash", driver], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        # The verdict is the last line of STDOUT; stderr (the reply check's own explanation) is
        # returned beside it for the assertions and is not where the verdict is read from.
        rc = int(done.stdout.rsplit("RC=", 1)[1].strip())
        return rc, done.stdout + done.stderr

    def test_a_committed_demonstration_turn_under_the_pinned_anchor_is_green(self):
        rc, out = self.verdict(self.log(), self.reply())
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN", out)
        self.assertIn("NOT production", out)
        # ...and the same for the relabelled deployment, judged against the word IT pinned.
        rc, out = self.verdict(self.log(provenance="install_minted"), self.reply(),
                               provenance="install_minted")
        self.assertEqual(rc, 0, out)

    def test_a_production_label_is_red_and_says_production(self):
        rc, out = self.verdict(self.log(), self.reply(trust_state="trusted_verified"))
        self.assertEqual(rc, 1, out)
        self.assertIn("PRODUCTION claim", out)
        self.assertNotIn("GREEN", out)

    def test_a_blocked_turn_is_red(self):
        # The outcome this phase USED to expect. It is now a failure of the product binary to take
        # the turn the driver takes.
        rc, out = self.verdict(self.log(), self.reply(status="blocked"))
        self.assertEqual(rc, 1, out)
        self.assertIn("did not commit as demonstration_custody", out)

    def test_a_broker_that_did_not_name_the_pinned_anchor_is_red_even_when_the_turn_committed(self):
        cases = {
            "another provenance": self.log(provenance="demonstration"),
            "another path": self.log(anchor="/opt/brops-live/tcb/elsewhere.json"),
            "a production claim": self.log(supported="true"),
            "no anchor line at all": "brops-broker: %s\n" % self.PROVISIONED,
        }
        for name, log in cases.items():
            with self.subTest(case=name):
                rc, out = self.verdict(log, self.reply())
                self.assertEqual(rc, 1, out)
                self.assertNotIn("GREEN", out)

    def test_a_broker_that_refused_or_never_provisioned_is_red(self):
        rc, out = self.verdict(self.log(provisioned=False), self.reply())
        self.assertEqual(rc, 1, out)
        self.assertIn("never reported the trusted manifest provisioned", out)
        rc, out = self.verdict(
            self.log(extra="brops-broker: root anchor REFUSED (x) — serving fail-closed\n"),
            self.reply())
        self.assertEqual(rc, 1, out)
        self.assertIn("reported a refusal", out)


class KitHeredocTests(unittest.TestCase):
    """The Python the ladder kit runs for the T-131 controls, RUN — against a synthetic tree.

    The kit itself needs root, seven accounts and `/opt/brops-live`, so no test here runs it and
    none of this says a turn completes. What it does say: the relabelled anchor, the derived pin
    manifest and the reply check each do what the script's prose claims, on inputs of the shape the
    kit hands them. The text assertions above hold WHERE these run; these hold WHAT they do.
    """

    def setUp(self):
        self.script = _script("run_ladder_turn.sh")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        self.anchor = self.path("root-anchor.json")
        self.write(self.anchor, {"root_key_id": "brops-live-root-1", "public_key_hex": "ab" * 32,
                                 "provenance": "kit_generated"})
        self.broker_cfg = self.path("broker-config.json")
        self.broker_pin = self.path("broker-tcb-pin-manifest.json")
        self.write(self.broker_cfg, {"trust": {"tcb_pin_manifest_path": self.broker_pin,
                                               "manifest_path": "/x"}, "uids": {}})
        self.other = self.path("supervisor.py")
        with open(self.other, "w", encoding="utf-8") as fh:
            fh.write("# a pinned file this control must not touch\n")
        self.write(self.broker_pin, {
            "artifacts": [
                self.pin("key-manifest.root-anchor", self.anchor),
                self.pin("trusted-verifier-broker.config", self.broker_cfg),
                self.pin("trusted-verifier-broker.pinned-manifest-config", self.broker_cfg),
                dict(self.pin("supervisor.bin", self.other), digest_origin="source:x"),
            ],
            "owner_uids": {"root": 0, "brops_admin": 0},
        })

    def path(self, name):
        return os.path.join(self.dir, name)

    @staticmethod
    def write(path, document):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(document, fh, separators=(",", ":"))

    @staticmethod
    def sha(path):
        import hashlib
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    def pin(self, role, path):
        return {"logical_name": role, "path": path, "expected_sha256": self.sha(path),
                "expected_owner": "root", "digest_origin": "deployment-measured"}

    def run_heredoc(self, tag, *args):
        return subprocess.run([sys.executable, "-", *args], input=_heredoc(self.script, tag)[1],
                              capture_output=True, text=True)

    def relabelled_deployment(self):
        anchor_im = self.path("root-anchor-install-minted.json")
        cfg_im = self.path("broker-config-install-minted.json")
        pin_im = self.path("broker-tcb-pin-manifest-install-minted.json")
        r = self.run_heredoc("PYBROKERIM", self.anchor, anchor_im, self.broker_cfg, cfg_im, pin_im)
        self.assertEqual(r.returncode, 0, r.stderr)
        return anchor_im, cfg_im, pin_im

    def test_the_relabel_changes_one_word_of_the_anchor_and_one_key_of_the_config(self):
        anchor_im, cfg_im, pin_im = self.relabelled_deployment()
        self.assertEqual(_read_json(anchor_im), {"root_key_id": "brops-live-root-1",
                                                 "public_key_hex": "ab" * 32,
                                                 "provenance": "install_minted"})
        relabelled = _read_json(cfg_im)
        self.assertEqual(relabelled["trust"]["tcb_pin_manifest_path"], pin_im)
        relabelled["trust"]["tcb_pin_manifest_path"] = self.broker_pin
        self.assertEqual(relabelled, _read_json(self.broker_cfg))
        # It relabels a KIT anchor and nothing else: handed one that is already relabelled, it stops.
        r = self.run_heredoc("PYBROKERIM", anchor_im, self.path("x.json"), self.broker_cfg,
                             self.path("y.json"), pin_im)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.path("x.json")))

    def test_the_derived_manifest_repoints_three_pins_and_leaves_every_other_alone(self):
        anchor_im, cfg_im, pin_im = self.relabelled_deployment()
        r = self.run_heredoc("PYPINIM", self.broker_pin, pin_im, anchor_im, cfg_im)
        self.assertEqual(r.returncode, 0, r.stderr)
        derived = _read_json(pin_im)
        by_role = {}
        for artifact in derived["artifacts"]:
            by_role.setdefault(artifact["logical_name"], []).append(artifact)
        # ONE anchor entry (the broker refuses an ambiguous role), at the relabelled file's digest.
        self.assertEqual(len(by_role["key-manifest.root-anchor"]), 1)
        self.assertEqual(by_role["key-manifest.root-anchor"][0]["path"], anchor_im)
        self.assertEqual(by_role["key-manifest.root-anchor"][0]["expected_sha256"],
                         self.sha(anchor_im))
        # Both of the broker's config roles pin the document that names THIS manifest — the role
        # `verify_broker_tcb` compares with `$BROPS_BROKER_CONFIG` is one of them.
        for role in ("trusted-verifier-broker.config",
                     "trusted-verifier-broker.pinned-manifest-config"):
            self.assertEqual(by_role[role][0]["path"], cfg_im, role)
            self.assertEqual(by_role[role][0]["expected_sha256"], self.sha(cfg_im), role)
        original = {a["logical_name"]: a for a in _read_json(self.broker_pin)["artifacts"]}
        self.assertEqual(by_role["supervisor.bin"][0], original["supervisor.bin"])
        self.assertEqual(derived["owner_uids"], {"root": 0, "brops_admin": 0})
        self.assertEqual(len(derived["artifacts"]), len(original))

    def test_the_derived_manifest_refuses_inputs_that_would_not_make_a_floor(self):
        anchor_im, cfg_im, pin_im = self.relabelled_deployment()
        # A product manifest with no anchor role: there is nothing to re-point.
        stripped = _read_json(self.broker_pin)
        stripped["artifacts"] = [a for a in stripped["artifacts"]
                                 if a["logical_name"] != "key-manifest.root-anchor"]
        no_anchor = self.path("no-anchor-pin.json")
        self.write(no_anchor, stripped)
        r = self.run_heredoc("PYPINIM", no_anchor, pin_im, anchor_im, cfg_im)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("key-manifest.root-anchor", r.stderr)
        self.assertFalse(os.path.exists(pin_im))
        # A config that names some OTHER manifest: the broker would read a different floor.
        elsewhere = self.path("elsewhere.json")
        r = self.run_heredoc("PYPINIM", self.broker_pin, elsewhere, anchor_im, cfg_im)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(elsewhere))

    def test_the_drivers_throwaway_anchor_is_relabelled_and_named_by_its_own_config(self):
        driver_cfg = self.path("ladder-driver.json")
        self.write(driver_cfg, {"trust": {"root_anchor_path": self.anchor}})
        anchor_out = self.path("root-anchor-throwaway-install-minted.json")
        cfg_out = self.path("ladder-driver-throwaway-install-minted.json")
        r = self.run_heredoc("PYTHROWIM", self.anchor, anchor_out, driver_cfg, cfg_out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(_read_json(anchor_out)["provenance"], "install_minted")
        self.assertEqual(_read_json(cfg_out)["trust"]["root_anchor_path"], anchor_out)
        # The pinned anchor is untouched: the throwaway is a DIFFERENT file, which is the point.
        self.assertEqual(_read_json(self.anchor)["provenance"], "kit_generated")

    def reply_verdict(self, tag, document):
        reply = self.path("reply.json")
        self.write(reply, document)
        return self.run_heredoc(tag, reply).returncode

    def test_the_reply_check_accepts_only_a_committed_demonstration_turn(self):
        protocol = "brops.renderer-governed-turn-result.v1"
        committed = {"protocol": protocol, "status": "committed", "client_request_id": "c",
                     "broker_turn_id": "b", "conversation_id": "k",
                     "message": {"message_id": "m", "author": "Bro", "body": "hello",
                                 "created_at_ms": 1, "trust_state": "demonstration_custody"}}
        blocked = {"protocol": protocol, "status": "blocked", "reason": "upstream_blocked",
                   "client_request_id": "c", "broker_turn_id": "b", "conversation_id": "k"}

        def variant(**message):
            document = json.loads(json.dumps(committed))
            document["message"].update(message)
            return document

        self.assertEqual(self.reply_verdict("PYCOMMITTED", committed), 0)
        # THE outcome this phase exists to make impossible has its own exit code, so the kit can
        # say "production" rather than "not what was expected".
        self.assertEqual(
            self.reply_verdict("PYCOMMITTED", variant(trust_state="trusted_verified")), 3)
        self.assertEqual(self.reply_verdict("PYCOMMITTED", blocked), 1)
        self.assertEqual(self.reply_verdict("PYCOMMITTED", variant(trust_state="other")), 1)
        self.assertEqual(self.reply_verdict("PYCOMMITTED", variant(body="")), 1)
        without_message = json.loads(json.dumps(committed))
        del without_message["message"]
        self.assertEqual(self.reply_verdict("PYCOMMITTED", without_message), 1)
        self.assertEqual(
            self.reply_verdict("PYCOMMITTED", dict(committed, protocol="something.else")), 1)
        self.assertEqual(
            self.reply_verdict("PYCOMMITTED", dict(committed, reason="upstream_blocked")), 1)
        # ...and the floor-refusal negative's check still means what it meant.
        self.assertEqual(self.reply_verdict("PYREPLY", blocked), 0)
        self.assertEqual(self.reply_verdict("PYREPLY", committed), 1)


if __name__ == "__main__":
    unittest.main()
