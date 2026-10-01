//! The guard, guarded: tests for `tests/prerequisites/mod.rs` itself.
//!
//! # Why this file exists
//!
//! The previous guard carried a comment asserting that a direct `io::stderr()` write escapes
//! libtest's capture, so a skipped test would announce itself in a plain `cargo test` run.
//! A real Debian run refuted it: libtest captures the raw handle too, the notice appeared only
//! under `--show-output`, and the suite reported **131 passed, 0 failed, 0 ignored** with the one
//! test that proves the POSIX anchor is out of the account's reach silently skipped — counts
//! byte-identical to a run in which it had executed.
//!
//! Nothing in the suite could have caught that, because the guard was the one module with no
//! tests. A claim about observability written in a comment is not a check; this file is the
//! check. The property it holds down:
//!
//! > No configuration of this suite can report all-green while a decisive test quietly did not
//! > run. Either the prerequisite was present, or a human typed its exact tag.
//!
//! Each test below is written so that the obvious way to regress the guard makes it RED:
//! restoring "print and return" breaks [`an_undeclared_skip_panics_rather_than_printing`];
//! making the decision permissive breaks the [`prerequisites::verdict`] cases; adding a
//! convenience wildcard breaks [`there_is_no_blanket_form_that_turns_the_guard_off`]; exempting
//! a test as a "platform fact" without putting it in the reviewed table breaks
//! [`a_platform_exemption_outside_the_table_is_refused`].

mod prerequisites;

use prerequisites::Verdict;

/// A tag no workflow and no runbook declares, so a `should_panic` test built on it cannot be
/// disarmed by the environment the suite happens to run in.
const NEVER_DECLARED: &str = "a-prerequisite-no-machine-is-expected-to-have";

// =================================================================================================
// The default: fatal
// =================================================================================================

/// An undeclared missing prerequisite is a FAILURE, not an early return.
///
/// This is the inversion the Debian run forced. Before it, the same input produced a silent pass
/// off CI, and the suite's exit code and counts said nothing about whether the test had run.
#[test]
fn an_undeclared_missing_prerequisite_is_fatal() {
    for declaration in ["", "   ", ",", " , , ", "some-other-tag", "posix-foreign-anchor-2"] {
        assert!(
            matches!(prerequisites::verdict("posix-foreign-anchor", declaration), Verdict::Fail(_)),
            "declaration {declaration:?} was treated as declaring `posix-foreign-anchor`"
        );
    }
}

/// And the failure text tells the operator the two things they need: which prerequisite, and the
/// exact string that accepts the hole if the machine genuinely cannot provide it.
#[test]
fn the_refusal_names_the_tag_and_the_way_to_accept_it() {
    let Verdict::Fail(why) = prerequisites::verdict("windows-symlink-creation", "") else {
        panic!("an undeclared tag was not a failure");
    };
    assert!(why.contains(prerequisites::DECLARATION_ENV), "{why}");
    assert!(why.contains("windows-symlink-creation"), "{why}");
    // And it says why an early return would be worthless, because that is the thing an operator
    // reaching for a skip has not thought about yet.
    assert!(why.contains("same counts either way"), "{why}");
}

/// Exactness: a tag declares itself and nothing else. No prefixes, no substrings, no globs.
#[test]
fn only_the_exact_tag_declares_it() {
    assert_eq!(prerequisites::verdict("procfs", "procfs"), Verdict::Declared);
    assert_eq!(
        prerequisites::verdict("procfs", " posix-foreign-anchor , procfs , windows-symlink-creation "),
        Verdict::Declared
    );
    for near_miss in ["procf", "procfs2", "proc", "PROCFS", "pro*", "*fs"] {
        assert!(
            matches!(prerequisites::verdict("procfs", near_miss), Verdict::Fail(_)),
            "{near_miss:?} was accepted as a declaration of `procfs`"
        );
    }
}

/// There is no single value that switches the guard off, and reaching for one is refused *by
/// name* rather than silently matching nothing.
///
/// The distinction matters: if `BROPS_TEST_MISSING_PREREQUISITES=1` merely failed to match, an
/// operator would see the ordinary "not declared" refusal and try harder to find the magic
/// value. This says there is none.
#[test]
fn there_is_no_blanket_form_that_turns_the_guard_off() {
    for blanket in ["all", "*", "any", "1", "true", "yes", "on", "everything", "ALL", "True"] {
        let verdict = prerequisites::verdict("procfs", blanket);
        let Verdict::Fail(why) = verdict else {
            panic!("{blanket:?} switched the guard off");
        };
        assert!(why.contains("declares NOTHING"), "{blanket:?}: {why}");
    }
    // Even beside a genuine tag: a blanket form anywhere in the list poisons the whole
    // declaration, so "all,procfs" cannot become the idiom that means "and everything else too".
    assert!(matches!(prerequisites::verdict("procfs", "all,procfs"), Verdict::Fail(_)));
    assert!(matches!(prerequisites::verdict("procfs", "procfs,all"), Verdict::Fail(_)));
}

/// The whole point, exercised through the real entry point rather than the pure decision.
///
/// `skip` must PANIC. If anybody restores the previous behaviour — a line on stderr and a return
/// — this test goes red, because a returning `skip` is a passing test.
#[test]
#[should_panic(expected = "MISSING PREREQUISITE")]
fn an_undeclared_skip_panics_rather_than_printing() {
    prerequisites::skip(
        "an_undeclared_skip_panics_rather_than_printing",
        NEVER_DECLARED,
        "a prerequisite invented by this test so no environment can declare it away",
    );
}

/// And the panic carries the remedy, so the failure is actionable rather than merely loud.
#[test]
#[should_panic(expected = "BROPS_TEST_MISSING_PREREQUISITES")]
fn the_panic_names_the_variable_that_would_accept_the_hole() {
    prerequisites::skip(
        "the_panic_names_the_variable_that_would_accept_the_hole",
        NEVER_DECLARED,
        "a prerequisite invented by this test",
    );
}

/// A declared tag is the ONLY thing that turns the failure into an early return.
#[test]
fn a_declared_tag_is_the_only_early_return() {
    assert_eq!(prerequisites::verdict(NEVER_DECLARED, NEVER_DECLARED), Verdict::Declared);
    assert!(matches!(prerequisites::verdict(NEVER_DECLARED, ""), Verdict::Fail(_)));
}

// =================================================================================================
// Platform facts are a table, not a habit
// =================================================================================================

/// `not_applicable` is not a second, quieter `skip`: it refuses any test that is not in the
/// reviewed table.
///
/// Without this, "the platform has no such concept" becomes the sentence anybody writes to make
/// an inconvenient environment gap go away — which is the old CI-panic escape hatch under a new
/// name.
#[test]
#[should_panic(expected = "PLATFORM_EXEMPTIONS")]
fn a_platform_exemption_outside_the_table_is_refused() {
    prerequisites::not_applicable("a_test_that_is_not_in_the_reviewed_table");
}

/// Every entry in the table names a test that actually exists, on a platform this matrix runs,
/// with a reason that says where the property IS measured.
///
/// The sources are read at compile time, so a renamed or deleted test leaves a dangling
/// exemption that this catches rather than one that silently exempts nothing.
#[test]
fn every_platform_exemption_names_a_test_that_exists() {
    const SOURCES: [&str; 2] =
        [include_str!("anchor_custody.rs"), include_str!("audit_signer.rs")];

    let mut seen: Vec<&str> = Vec::new();
    for (test, platform, why) in prerequisites::PLATFORM_EXEMPTIONS {
        assert!(
            !seen.contains(&test),
            "{test} is in PLATFORM_EXEMPTIONS twice; the table is a list of distinct properties \
             this platform does not measure"
        );
        seen.push(test);

        let declaration = format!("fn {test}(");
        assert!(
            SOURCES.iter().any(|src| src.contains(&declaration)),
            "PLATFORM_EXEMPTIONS names `{test}`, which no test in this suite defines — a \
             dangling exemption exempts nothing and hides that it stopped applying"
        );
        assert!(
            ["windows", "linux", "macos", "unix"].contains(&platform),
            "`{test}` is exempted on `{platform}`, which is not a platform this matrix runs"
        );
        // The reason has to say where the property IS measured. An exemption whose reason is
        // only "not here" is a coverage hole with a nicer name.
        assert!(
            why.contains("runs this test for real") || why.contains("measures"),
            "`{test}`'s exemption does not say what measures the property instead: {why}"
        );
    }
    assert!(!seen.is_empty(), "the table is empty; delete the mechanism rather than keep a stub");
}

/// The tags the suite uses are distinct and comma-free, because the declaration format is
/// comma-separated and a tag containing one could never be declared.
///
/// It iterates [`prerequisites::ALL_TAGS`], not a list written out here. The list written out
/// here had nine entries when the module defined eleven: `TAG_ROOT_INSTALLER` and
/// `TAG_ENGINE_AS_DESKTOP_UID` were in use and checked by nothing.
#[test]
fn the_prerequisite_tags_are_distinct_and_declarable() {
    let tags = prerequisites::ALL_TAGS;
    for (i, tag) in tags.iter().enumerate() {
        assert!(!tag.is_empty() && !tag.contains(','), "{tag:?} could never be declared");
        assert!(!tags[..i].contains(tag), "{tag:?} is used for two different prerequisites");
        // Each one declares itself and only itself, through the real decision function.
        assert_eq!(prerequisites::verdict(tag, tag), Verdict::Declared);
        for other in tags.iter().filter(|o| o != &tag) {
            assert!(
                matches!(prerequisites::verdict(tag, other), Verdict::Fail(_)),
                "declaring {other:?} also declared {tag:?}"
            );
        }
    }
}

/// The module's own source, line endings normalised (a Windows checkout may hand `include_str!`
/// CRLF, and a scan written against `\n` would then find nothing and pass).
fn prerequisites_source() -> String {
    include_str!("prerequisites/mod.rs").replace("\r\n", "\n")
}

/// `ALL_TAGS` is every tag: a `TAG_` constant declared in the module and left out of the table
/// is exactly the hole the hand-copied list had, moved one file over.
///
/// Read from the module's source, so adding a tag without listing it fails here.
#[test]
fn every_prerequisite_tag_constant_is_in_all_tags() {
    let source = prerequisites_source();
    let declared: Vec<&str> = source
        .lines()
        .filter_map(|line| line.strip_prefix("pub const TAG_"))
        .filter_map(|rest| rest.split(':').next())
        .collect();
    assert!(declared.len() >= 11, "the scan found only {} TAG_ constants", declared.len());

    let (_, table) = source
        .split_once("pub const ALL_TAGS: [&str;")
        .expect("prerequisites/mod.rs no longer declares ALL_TAGS");
    let table = table.split_once("];").expect("ALL_TAGS has no end").0;
    let listed: Vec<&str> = table
        .lines()
        .map(str::trim)
        .filter_map(|line| line.strip_prefix("TAG_"))
        .map(|rest| rest.trim_end_matches(','))
        .collect();

    for name in &declared {
        assert!(
            listed.contains(name),
            "TAG_{name} is declared in prerequisites/mod.rs and missing from ALL_TAGS, so nothing \
             checks that it is distinct and declarable"
        );
    }
    assert_eq!(
        listed.len(),
        declared.len(),
        "ALL_TAGS lists {listed:?} and the module declares {declared:?}"
    );
    assert_eq!(prerequisites::ALL_TAGS.len(), declared.len());
}

// =================================================================================================
// "Never compiled out" — and the table of the tests that are
// =================================================================================================

/// Every `cfg`-gated test in this directory, read from the sources: `(file, test or "*", cfg)`.
///
/// A gate counts when it sits at column 0 — an attribute on an ITEM — and is either the
/// file-level `#![cfg(…)]` or attached to a `#[test]` function. A `#[cfg(unix)] { … }` block
/// INSIDE a test body is indented and is not counted: that test still exists and runs on both
/// legs, which is the rule being kept rather than an exception to it.
fn compiled_out_tests_in_the_sources() -> Vec<(String, String, String)> {
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests");
    let mut files: Vec<std::path::PathBuf> = std::fs::read_dir(&dir)
        .unwrap_or_else(|e| panic!("cannot list {}: {e}", dir.display()))
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| path.extension().is_some_and(|ext| ext == "rs"))
        .collect();
    files.sort();
    assert!(files.len() >= 6, "found only {} test files in {}", files.len(), dir.display());

    let mut found = Vec::new();
    for path in files {
        let file = path.file_name().unwrap().to_string_lossy().to_string();
        let text = std::fs::read_to_string(&path)
            .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
        let lines: Vec<&str> = text.lines().collect();
        for (i, line) in lines.iter().enumerate() {
            if let Some(rest) = line.strip_prefix("#![cfg(") {
                let cfg = rest.strip_suffix(")]").unwrap_or(rest);
                found.push((file.clone(), "*".to_string(), cfg.to_string()));
                continue;
            }
            let Some(rest) = line.strip_prefix("#[cfg(") else { continue };
            let cfg = rest.strip_suffix(")]").unwrap_or(rest);
            let before = i.checked_sub(1).and_then(|at| lines.get(at)).copied();
            let after = lines.get(i + 1).copied();
            if before != Some("#[test]") && after != Some("#[test]") {
                continue;
            }
            let name = lines[i + 1..]
                .iter()
                .take(4)
                .find_map(|l| l.strip_prefix("fn "))
                .and_then(|l| l.split('(').next())
                .unwrap_or_else(|| panic!("{file}:{}: a gated #[test] with no fn after it", i + 1));
            found.push((file.clone(), name.to_string(), cfg.to_string()));
        }
    }
    found
}

/// The rule says "never compiled out". These are the tests that are — and the table is exactly
/// them, in both directions.
///
/// Until this test, `posix_install.rs` (whole), eight tests in `audit_signer.rs` and one in
/// `provision.rs` were removed by the compiler on one leg while the module header said no test
/// ever is. A new `#[cfg(windows)]` test now fails here until it is declared with the leg that
/// runs it, and an entry whose test stopped being gated fails here until it is removed.
#[test]
fn every_compiled_out_test_is_declared_and_nothing_else_is() {
    let found = compiled_out_tests_in_the_sources();
    assert!(!found.is_empty(), "the scan found no cfg-gated test at all; it read the wrong thing");

    for (file, test, cfg) in &found {
        assert!(
            prerequisites::COMPILED_OUT
                .iter()
                .any(|(f, t, c, _)| f == file && t == test && c == cfg),
            "{file}: `{test}` is under #[cfg({cfg})], so the compiler removes it on the other \
             leg, and it is not in prerequisites::COMPILED_OUT. Either make it run everywhere \
             (gate the BODY and use `skip`/`not_applicable`), or declare it there with the leg \
             that does run it"
        );
    }
    let mut seen: Vec<(&str, &str)> = Vec::new();
    for (file, test, cfg, why) in prerequisites::COMPILED_OUT {
        assert!(!seen.contains(&(file, test)), "{file}::{test} is in COMPILED_OUT twice");
        seen.push((file, test));
        assert!(
            found.iter().any(|(f, t, c)| f == file && t == test && c == cfg),
            "COMPILED_OUT names {file}::{test} under cfg({cfg}), and the sources have no such \
             gate — a dangling entry excuses nothing and hides that it stopped applying"
        );
        // The reason has to name the leg that DOES run it, as PLATFORM_EXEMPTIONS must.
        let leg = if cfg == "windows" { "windows-latest leg runs it" } else { "ubuntu-latest leg runs it" };
        assert!(why.contains(leg), "{file}::{test} (cfg({cfg})) does not say that the {leg}: {why}");
    }
    assert_eq!(found.len(), prerequisites::COMPILED_OUT.len());
}

// =================================================================================================
// The two measurements the guard itself makes
// =================================================================================================

/// A named interpreter is the ONLY one tried.
///
/// There were four copies of this rule and two of them fell back to `python3`/`python` when the
/// named interpreter failed — so a `BROPS_TEST_PYTHON` with a typo in it, or one without
/// `cryptography`, produced a green cross-language proof run under some other interpreter.
#[test]
fn a_named_python_is_exclusive_and_only_its_absence_means_the_defaults() {
    let defaults = vec!["python3".to_string(), "python".to_string()];
    assert_eq!(prerequisites::python_candidates(None), defaults);
    for blank in ["", " ", "\t", "  \n"] {
        assert_eq!(prerequisites::python_candidates(Some(blank)), defaults, "{blank:?}");
    }
    for named in ["/opt/venv/bin/python", "python3.12", "C:\\Python312\\python.exe"] {
        assert_eq!(
            prerequisites::python_candidates(Some(named)),
            vec![named.to_string()],
            "naming {named:?} must leave nothing to fall back to"
        );
    }
    assert_eq!(prerequisites::PYTHON_ENV, "BROPS_TEST_PYTHON");
}

/// A uid that was measured answers the question.
#[test]
fn a_measured_euid_decides_whether_this_is_root() {
    assert!(prerequisites::root_from_euid_probe(Ok(0)));
    for uid in [1u32, 1000, 65534] {
        assert!(!prerequisites::root_from_euid_probe(Ok(uid)), "uid {uid} was read as root");
    }
}

/// A uid that could NOT be measured is not "not root".
///
/// `running_as_root` used to end in `.unwrap_or(false)`, so a failed probe told every test that
/// asks — in order to skip under root — that it was safe to assert a custody property.
#[test]
#[should_panic(expected = "is UNKNOWN")]
fn an_unmeasured_euid_is_not_read_as_not_root() {
    prerequisites::root_from_euid_probe(Err("the probe file could not be created".to_string()));
}
