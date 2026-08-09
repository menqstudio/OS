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
#[test]
fn the_prerequisite_tags_are_distinct_and_declarable() {
    let tags = [
        prerequisites::TAG_NOT_ROOT,
        prerequisites::TAG_POSIX_FOREIGN_ANCHOR,
        prerequisites::TAG_PROCFS,
        prerequisites::TAG_UNELEVATED_TOKEN,
        prerequisites::TAG_WINDOWS_SYMLINK,
        prerequisites::TAG_OWNER_ASSIGNMENT,
        prerequisites::TAG_DACL_APPLICATION,
        prerequisites::TAG_INSTALLED_SIGNER_SERVICE,
        prerequisites::TAG_ELEVATED_REGISTRATION,
    ];
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
