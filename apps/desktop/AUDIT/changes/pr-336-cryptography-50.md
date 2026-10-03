Audited-PR: #336
Audited-Head: 467de0f49fefb70b43e2e0e11fdc0ea4473c0014
VERDICT: GREEN — the 50.0.2 pin, bound, waiver removal, and crypto-surface proof are consistent with the engine's actual Ed25519-raw usage and the supported CI evidence.

# Audit scope and interpreter

I confirmed the head with `gh pr view 336 --json headRefOid` and `git rev-parse HEAD`; both reported `467de0f49fefb70b43e2e0e11fdc0ea4473c0014`. I read `docs/design/T-165_CRYPTOGRAPHY_50_AUDIT_REQUEST.md` first, then the requested diff under `engine`, `.github`, and `tools`.

Local execution used CPython 3.14.4. The repository's hash lock supports CPython 3.12/3.13, so a fresh 3.14 `--require-hashes` install did not complete because the lock does not include the CPython 3.14 `rpds-py` wheel hash. The system interpreter already had `cryptography 50.0.1`, not the exact 50.0.2 pin.

# 1. Bound: `>=41,<51`

The `<51` ceiling is correct. The repository pins exactly `cryptography==50.0.2`, while the runtime dependency file expresses the supported major-release family rather than duplicating the lock pin. `<51` admits compatible 50.x patch releases and still fails closed on the next major. The new `PinnedVersionsAreAdmittedTests.test_every_pinned_runtime_library_satisfies_its_declared_bound` verifies that every runtime library pin is inside its declared range; locally it printed:

```text
Ran 1 test in 0.001s
OK
```

Following the pin exactly in `runtime-dependencies.json` would duplicate the lock's deployment choice and make every patch refresh require a runtime-contract edit. I found no reason to narrow the bound to `==50.0.2`.

# 2. 46.0.7 → 50.0.2 behavior

I searched all engine/runtime, engine/tools, engine/CI, and relevant workflow code for cryptography use. The reachable API is raw Ed25519 key generation/from-private-bytes, raw public-key loading, sign/verify, and raw/no-encryption serialization. The source scan reports no X.509, PKCS#7, PKCS#12, CMS, OCSP, PEM/DER/OpenSSH loader, or other affected API use. The direct runtime probe under the available interpreter printed:

```text
cryptography 50.0.1
cffi 2.1.1
ed25519_raw_roundtrip OK 64
```

The official cryptography changelog entries between the old and new releases show the relevant changes are outside this surface: 47.0 removed/changed older OpenSSL and X.509/curve behavior; 50.0.0 fixed a PKCS#7 decryption oracle and deprecated finite-field DH; 50.0.2 updated bundled OpenSSL/PyO3 wheels. No Ed25519 raw API or raw serialization incompatibility is listed. The repository's `check_crypto_surface.py` independently enforces the raw-Ed25519-only premise.

I ran the exact-head engine suite under CPython 3.14.4. It printed:

```text
Ran 2731 tests in 76.271s
FAILED (failures=5, skipped=19)
```

All five failures were unrelated host prerequisites (wired `python` not on PATH and two real-visudo wildcard expectations); no cryptography or Ed25519 test failed. The exact-head supported CI job independently printed `Ran 2731 tests ... OK (skipped=13)` on Linux, and the Windows job was green. The six PR workflows were green according to `gh pr checks 336`.

The official changelog was inspected for the 46.0.7–50.0.2 entries; I did not claim that a generic full suite proves every undocumented backend difference, but the reachable API audit, raw-signature probe, crypto-surface gate, and supported Linux/Windows suites cover the engine's actual use.

# 3. `cffi==2.1.0`

`cffi==2.1.0` is correct. Cryptography's metadata requires `cffi>=2.0.0` for CPython, so 2.1.0 satisfies the lower bound and remains exactly hash-pinned. The available interpreter's installed metadata independently reported:

```text
cffi>=2.0.0 ; platform_python_implementation != 'PyPy'
```

No cffi API is imported directly by engine code; it is the cryptography wheel's runtime binding dependency. The supported CI lock installation passed.

# 4. Crypto-surface self-test proof

The rewrite is a real repository-root proof, not merely an assertion that a waiver exists. `tools/test_check_crypto_surface.py::test_the_default_root_is_this_repository_whatever_the_cwd` changes into an empty temporary directory, invokes `gate.main()` without `--root`, then requires the output to contain the actual repository's pinned version and the real RustSec waiver count. It also requires a successful exit. Running the complete self-test module with `PYTHONPATH=tools` printed:

```text
Ran 34 tests in 0.381s
OK
```

The live gate against this checkout printed:

```text
GREEN: cryptography surface is Ed25519-raw only; 0 waived advisories each record a fix above the pinned 50.0.2; 17 RustSec waiver(s) identical in cargo-audit-ignore.txt and deny.toml
```

The test would fail if the default root were changed to `.`: from its temporary cwd the gate would report missing inputs rather than the repository pin. The gate's documented static-AST limitation remains explicit; dynamic imports/getattr are outside this proof and are not silently claimed covered.

# CI and supply-chain evidence

The exact-head GitHub engine log installed `cryptography==50.0.2` from the hash-pinned lock and completed `2731` tests with `OK (skipped=13)`. The exact-head pip-audit job printed:

```text
No known vulnerabilities found
```

The four cryptography waivers are removed, and the unchanged RustSec waiver remains outside this PR's scope.

# Not independently verified

I did not execute a supported CPython 3.12 or 3.13 environment locally, rerun the deployment on a host, or run Windows locally. I did inspect the exact-head Linux/Windows CI results. I did not alter any runtime code, dependency file, canonical document, or pull-request body; this report is the only file changed by the audit commit.
