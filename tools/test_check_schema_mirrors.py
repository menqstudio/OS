"""Tests for tools/check_schema_mirrors.py — M1 of the `contracts/` dedupe.

The gate exists because a Rust struct and the JSON Schema it claims to mirror were bound by nothing
but a doc comment. These tests pin both directions of that binding — and the correction that made
the rule sharper.

**The first version of this gate was wrong**, and the way it was wrong is worth keeping: it saw
`schema` in the schema's `required` list, did not see it on the struct, and reported both mirrors
as broken. They are not. `schema: {const: 1}` is a DISCRIMINATOR — it says what the object IS — and
`governance.rs` checks it on the raw value and drops it, which is the right thing to do with a
constant. Carrying it into the parsed struct would add a field that can only ever hold one value.

Fixing that false positive made the gate stronger: a discriminator must now be **either carried or
checked**, so one that is *neither* — a shape parsed on the strength of its other fields alone — is
a finding the loose version could not have produced.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_schema_mirrors as m  # noqa: E402


def write_schema(required, properties, closed=True):
    d = pathlib.Path(tempfile.mkdtemp()) / "s.schema.json"
    d.write_text(json.dumps({
        "required": required,
        "properties": properties,
        "additionalProperties": False if closed else True,
    }), encoding="utf-8")
    return d


class SchemaReadTests(unittest.TestCase):
    def test_reads_required_properties_closedness_and_discriminators(self):
        p = write_schema(["a", "schema"], {"a": {"type": "string"}, "schema": {"const": 1}})
        required, props, closed, disc = m.schema_fields(p)
        self.assertEqual(required, {"a", "schema"})
        self.assertEqual(props, {"a", "schema"})
        self.assertTrue(closed)
        self.assertEqual(disc, {"schema"})

    def test_an_open_schema_is_not_reported_closed(self):
        p = write_schema(["a"], {"a": {"type": "string"}}, closed=False)
        self.assertFalse(m.schema_fields(p)[2])


class RustReadTests(unittest.TestCase):
    SRC = """
        /// doc comment mentioning pub fake: String,
        #[derive(Debug)]
        #[serde(rename_all = "camelCase")]
        pub struct Thing {
            pub receipt_id: String,   // a trailing comment
            pub key_id: String,
            pub count: i64,
        }
    """

    def test_reads_the_declared_fields(self):
        self.assertEqual(m.rust_struct_fields(self.SRC, "Thing"),
                         {"receipt_id", "key_id", "count"})

    def test_attributes_and_comments_do_not_become_fields(self):
        self.assertNotIn("derive", m.rust_struct_fields(self.SRC, "Thing"))
        self.assertNotIn("fake", m.rust_struct_fields(self.SRC, "Thing"))

    def test_a_missing_struct_is_None_not_an_empty_set(self):
        # The caller turns this into a FAILURE. An empty set would silently pass every check,
        # making the gate weakest exactly where a rename happened.
        self.assertIsNone(m.rust_struct_fields(self.SRC, "Renamed"))


class CompareTests(unittest.TestCase):
    def test_agreement_is_green(self):
        self.assertEqual(
            m.compare("T", {"a", "b"}, {"a", "b"}, True, set(), {"a", "b"}, ""), [])

    def test_a_dropped_required_field_is_red(self):
        f = m.compare("T", {"a", "b"}, {"a", "b"}, True, set(), {"a"}, "")
        self.assertTrue(any("REQUIRES `b`" in p for p in f), f)

    def test_an_invented_field_is_red_when_the_schema_is_closed(self):
        f = m.compare("T", {"a"}, {"a"}, True, set(), {"a", "extra"}, "")
        self.assertTrue(any("extra" in p for p in f), f)

    def test_an_invented_field_is_allowed_when_the_schema_is_open(self):
        self.assertEqual(m.compare("T", {"a"}, {"a"}, False, set(), {"a", "extra"}, ""), [])

    # --- the correction ------------------------------------------------------------------
    def test_a_discriminator_that_is_CHECKED_may_be_dropped(self):
        # THE FALSE POSITIVE, as a test. governance.rs validates `schema` on the raw value and
        # does not carry it; that is correct, and the gate must not demand a field that could
        # only ever hold one value.
        src = 'if o.get("schema").and_then(|v| v.as_i64()) != Some(1) { return Err(..) }'
        self.assertEqual(
            m.compare("T", {"a", "schema"}, {"a", "schema"}, True, {"schema"}, {"a"}, src), [])

    def test_a_discriminator_that_is_NEITHER_carried_NOR_checked_is_red(self):
        # The finding the loose version could not produce: the shape is then parsed on the
        # strength of its other fields alone.
        f = m.compare("T", {"a", "schema"}, {"a", "schema"}, True, {"schema"}, {"a"}, "no check here")
        self.assertTrue(any("neither kept nor checked" in p for p in f), f)

    def test_a_discriminator_that_is_CARRIED_needs_no_raw_check(self):
        self.assertEqual(
            m.compare("T", {"schema"}, {"schema"}, True, {"schema"}, {"schema"}, ""), [])

    def test_validates_wants_the_field_read_not_merely_mentioned(self):
        self.assertTrue(m.validates('o.get("schema")', "schema"))
        # A doc comment saying the word is not a check.
        self.assertFalse(m.validates("// we should check schema one day", "schema"))


class ScopedValidationTests(unittest.TestCase):
    """`A-02`, sixth independent audit — `validates()` required a SUBSTRING, not a check.

    It searched the whole file for `get("schema")`, comments and `#[cfg(test)]` included, while
    both MIRRORS entries named the same file. The auditor measured five mutations that all left
    the gate GREEN — including deleting `parse_evidence_event`'s comparison outright while the
    receipt's own check kept the substring alive, which on the real repository produced 29 passed
    and a green gate.

    Each mutation below is one of those five. Three are killed here; the other two — a comparison
    replaced by `false`, and one inverted so every version is accepted — still contain the
    substring in the right function and are killed by the REQUIRED negative test instead. Both
    halves are asserted, and neither claims to do the other's job.
    """

    SRC = '''
        /// doc mentioning o.get("schema") in prose
        pub fn parse_thing(o: &Value) -> Result<Thing, String> {
            if o.get("schema").and_then(|v| v.as_i64()) != Some(1) {
                return Err("thing: schema must be 1".to_string());
            }
            Ok(Thing {})
        }

        pub fn parse_other(o: &Value) -> Result<Other, String> {
            Ok(Other {})
        }

        #[cfg(test)]
        mod tests {
            #[test]
            fn rejects_bad_thing_schema() {
                let mut t = valid();
                t["schema"] = json!(2);
                assert!(parse_thing(&t).is_err());
            }
        }
    '''

    def test_a_parser_that_checks_its_own_discriminator_passes(self):
        self.assertTrue(m.validates(self.SRC, "schema", "parse_thing"))

    def test_mutation_1_another_parsers_check_does_not_count(self):
        # THE FINDING. `parse_other` never looks at `schema`; the file does, in `parse_thing`.
        self.assertFalse(m.validates(self.SRC, "schema", "parse_other"))

    def test_mutation_3_a_comment_is_not_a_check(self):
        src = self.SRC.replace('if o.get("schema").and_then(|v| v.as_i64()) != Some(1) {',
                               '// o.get("schema") is checked elsewhere\n            if false {')
        self.assertFalse(m.validates(src, "schema", "parse_thing"))

    def test_mutation_4_a_mention_inside_cfg_test_is_not_a_check(self):
        src = self.SRC.replace('if o.get("schema").and_then(|v| v.as_i64()) != Some(1) {',
                               'if false {')
        # The test module still contains `t["schema"]` and calls the parser; neither is a check.
        self.assertFalse(m.validates(src, "schema", "parse_thing"))

    def test_a_parser_that_is_not_there_fails_closed(self):
        self.assertFalse(m.validates(self.SRC, "schema", "parse_missing"))

    def test_strip_test_modules_brace_counts_rather_than_stopping_at_the_first_brace(self):
        stripped = m.strip_test_modules(self.SRC)
        self.assertNotIn("rejects_bad_thing_schema", stripped)
        self.assertIn("parse_thing", stripped)

    def test_function_body_brace_counts(self):
        body = m.function_body(self.SRC, "parse_thing")
        self.assertIn("schema must be 1", body)
        self.assertNotIn("parse_other", body)

    # --- the half a static reader cannot do -------------------------------------------
    def test_a_declared_negative_test_that_exists_is_found(self):
        self.assertTrue(m.has_negative_test(self.SRC, "rejects_bad_thing_schema"))

    def test_a_declared_negative_test_that_was_renamed_away_is_not(self):
        self.assertFalse(m.has_negative_test(self.SRC, "rejects_bad_thing_schema_v2"))


class RealRepositoryTests(unittest.TestCase):
    """The regression: the real mirrors, against the real schemas."""
    def test_every_declared_mirror_agrees_today(self):
        self.assertEqual(m.main([]), 0)

    def test_the_mirror_table_is_not_empty(self):
        # A gate over nothing is green forever.
        self.assertGreaterEqual(len(m.MIRRORS), 2)
        for entry in m.MIRRORS:
            self.assertTrue(entry.get("reason"), entry)

    def test_every_mirror_declares_a_parser_and_a_negative_test(self):
        # A-02's structural half. Without `parser` the discriminator is searched for file-wide
        # again; without `negative_test` an inverted comparison is invisible to everything.
        for entry in m.MIRRORS:
            self.assertTrue(entry.get("parser"), entry)
            self.assertTrue(entry.get("negative_test"), entry)

    def test_every_declared_negative_test_really_exists(self):
        # Belt and braces with main(): named here so a rename shows up as THIS failing rather than
        # as a generic gate RED whose cause has to be read out of a message.
        for entry in m.MIRRORS:
            source = (m.ROOT / entry["rust"]).read_text(encoding="utf-8")
            self.assertTrue(m.has_negative_test(source, entry["negative_test"]),
                            f"{entry['struct']}: {entry['negative_test']} is gone")


if __name__ == "__main__":
    unittest.main()
