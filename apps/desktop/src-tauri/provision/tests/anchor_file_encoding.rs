//! `installed_anchor_bytes` against the REAL `json.dumps`, because a Rust test could not find
//! this and did not.
//!
//! # The bug this exists because of
//!
//! `sign_anchor` recorded its anti-rollback digest over `serde_json::to_vec(&document)`. The
//! engine computes the same digest over the anchor **file**, which `bro_audit_log._install_anchor`
//! writes with `json.dumps(document, sort_keys=True)` — Python's *default* separators, `", "` and
//! `": "`. The two encodings differ by a space after every separator, so the first anchor of a
//! ledger installed fine and the **second** append was refused, forever, as `AnchorChainBroken`.
//!
//! Every Rust test agreed with itself. The `audit-signer` end-to-end proof against the real module
//! found it on its first run. This test is the cheap guard that keeps it found: it asks the actual
//! Python `json.dumps` for the bytes and compares them with the Rust encoder's, over inputs chosen
//! to hit the places the two libraries disagree — separators, `ensure_ascii`, `0x7F`, control
//! characters, non-BMP code points, key ordering, nesting.
//!
//! **It does not skip.** No Python is a failure of the proof, not an excuse to disable it: the
//! machine without an interpreter is exactly the machine where the drift would go unnoticed.

use std::process::Command;

use brops_provision::audit_signer::installed_anchor_bytes;
use serde_json::{json, Value};

fn resolve_python() -> String {
    let mut candidates = Vec::new();
    if let Ok(explicit) = std::env::var("BROPS_TEST_PYTHON") {
        if !explicit.trim().is_empty() {
            candidates.push(explicit);
        }
    }
    candidates.extend(["python3".to_string(), "python".to_string()]);
    let mut reasons = Vec::new();
    for candidate in candidates {
        match Command::new(&candidate).args(["-c", "import json"]).output() {
            Ok(out) if out.status.success() => return candidate,
            Ok(out) => reasons
                .push(format!("`{candidate}` failed: {}", String::from_utf8_lossy(&out.stderr))),
            Err(e) => reasons.push(format!("could not run `{candidate}`: {e}")),
        }
    }
    panic!(
        "no usable Python to pin the anchor FILE encoding against. This test does NOT skip: the \
         digest `sign_anchor` records must equal the one bro_audit_log computes over the file it \
         writes with json.dumps, and nothing else in this crate can check that. Set \
         BROPS_TEST_PYTHON.\n  {}",
        reasons.join("\n  ")
    );
}

/// What `json.dumps(document, sort_keys=True)` really produces for `value`.
///
/// # The transport is explicit about bytes, and has to be
///
/// This used to hand Python the input through `sys.stdin.read()` and take the answer through
/// `print`. Both of those go through Python's *text* layer, whose encoding on Windows is the
/// process code page — cp1252 on a GitHub runner — not UTF-8. The first Windows CI run of this
/// crate therefore compared:
///
/// ```text
///   rust:   {"ledger": "journal-é中.jsonl"}
///   python: {"ledger": "journal-Ã©ä¸­.jsonl"}
/// ```
///
/// which is `é中` UTF-8-encoded and then re-read as cp1252, one byte at a time. The two encoders
/// had not drifted at all; the test's own pipe had corrupted the input before either of them saw
/// it, and the failure it reported was about the wrong thing entirely.
///
/// So the bytes are stated at both ends: `sys.stdin.buffer.read().decode("utf-8")` in, and
/// `sys.stdout.buffer.write(...encode("ascii"))` out. The `ascii` encode is not cosmetic — it is
/// an assertion that `json.dumps` really did honour `ensure_ascii=True`, and it raises rather
/// than transcoding if it did not.
fn python_dumps(python: &str, value: &Value) -> String {
    let compact = serde_json::to_string(value).expect("serialise the input for Python");
    let program = "import json,sys;                    text = sys.stdin.buffer.read().decode('utf-8');                    out = json.dumps(json.loads(text), sort_keys=True);                    sys.stdout.buffer.write(out.encode('ascii'))";
    let mut child = Command::new(python)
        .args(["-c", program])
        // A HOSTILE text layer, on purpose. The bug this guards against only reproduced on a
        // machine whose Python text encoding was not UTF-8 — a GitHub Windows runner, code page
        // 1252 — and on a developer box with UTF-8 mode on, reverting the fix goes green and
        // says nothing. Pinning the child's text encoding to cp1252 and turning UTF-8 mode off
        // makes the failure machine-independent: `sys.stdin.read()` mangles or raises on EVERY
        // box under these, while `sys.stdin.buffer.read().decode("utf-8")` is indifferent to
        // both because it never touches the text layer at all.
        .env("PYTHONIOENCODING", "cp1252")
        .env("PYTHONUTF8", "0")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .expect("spawn python");
    {
        use std::io::Write;
        child.stdin.as_mut().unwrap().write_all(compact.as_bytes()).unwrap();
    }
    let out = child.wait_with_output().expect("python output");
    assert!(
        out.status.success(),
        "python refused the input: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    let answer =
        String::from_utf8(out.stdout).expect("json.dumps is ASCII with ensure_ascii=True");
    assert!(
        answer.is_ascii(),
        "json.dumps returned non-ASCII bytes, so either ensure_ascii stopped defaulting to True          or the pipe transcoded them: {answer:?}"
    );
    answer
}

#[test]
fn the_anchor_file_encoder_agrees_with_the_real_json_dumps() {
    let python = resolve_python();
    let cases: Vec<(&str, Value)> = vec![
        (
            "a real anchor document",
            json!({
                "payload": {
                    "artifact_type": "audit-head",
                    "count": 3,
                    "issued_at_epoch": 1_700_000_000i64,
                    "key_id": "audit-anchor-0123456789abcdef",
                    "last_hash": "a".repeat(64),
                    "ledger": "bro-audit.jsonl",
                    "previous_anchor_sha256": Value::Null,
                },
                "signature": "ab".repeat(64),
            }),
        ),
        // The separators, on their own: this is the space that broke it.
        ("nesting and separators", json!({"a": {"b": [1, 2, {"c": 3}]}, "d": []})),
        // `ensure_ascii=True` is the default, so every one of these must come back \uXXXX-escaped.
        ("a non-ascii ledger name", json!({"ledger": "journal-\u{e9}\u{4e2d}.jsonl"})),
        // 0x7F is NOT in Python's `\x20-\x7e` unescaped range, and is easy to get wrong.
        ("delete and control characters", json!({"k": "\u{7f}\u{1}\u{1f}"})),
        // The five control characters with short forms, plus the two structural escapes.
        ("short-form escapes", json!({"k": "\u{8}\u{c}\n\r\t\"\\"})),
        // Above the BMP: Python emits a surrogate PAIR, not one \U escape.
        ("a non-BMP code point", json!({"k": "\u{1f600}"})),
        // Key ordering has to be the sorted one on both sides.
        ("keys out of order", json!({"z": 1, "a": 2, "M": 3, "_": 4})),
        ("scalars", json!({"t": true, "f": false, "n": Value::Null, "i": -42, "big": i64::MAX})),
        ("an empty document", json!({})),
    ];

    for (name, value) in cases {
        let rust = String::from_utf8(installed_anchor_bytes(&value).expect(name)).unwrap();
        let py = python_dumps(&python, &value);
        assert_eq!(
            rust, py,
            "{name}: the Rust anchor-file encoder and Python's json.dumps disagree.\n  rust:   \
             {rust}\n  python: {py}\nThe digest sign_anchor records would not match the one \
             bro_audit_log computes over the file, and every anchor after the first would be \
             refused as AnchorChainBroken."
        );
    }
}

#[test]
fn a_float_is_refused_rather_than_encoded_to_a_digest_that_might_be_right() {
    // Python's `repr` and Rust's shortest round-trip agree on most floats and not on all of them,
    // and "most" is not a property an anti-rollback digest can be built on. No anchor payload
    // contains a float; if one is ever added, this refusal is what makes it visible instead of
    // producing a ledger whose second append fails mysteriously.
    let value = json!({"issued_at_epoch": 1.5});
    assert!(
        installed_anchor_bytes(&value).is_err(),
        "a float was encoded; the digest may or may not have matched Python's"
    );
}
