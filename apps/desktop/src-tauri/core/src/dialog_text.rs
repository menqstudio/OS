//! Text that is safe to show inside a native confirmation dialog (audit K-04, K-06).
//!
//! The native window and its buttons are trustworthy; a string put into its body is not. A run's
//! intent, plan, step title and step detail, and an automation's name, trigger and action, are
//! all written by the renderer. They were interpolated into the dialog raw, so the text being
//! approved could draw the dialog it was shown in: a newline followed by `Risk: low` reads as a
//! line the application wrote, and U+202E reverses what follows it on screen. The digest still
//! binds every byte — it proves what was approved, not that a person could read it.
//!
//! Two forms, and a dialog uses nothing else for a value it did not compile in:
//!
//! - [`inline`] — the value on ONE line, after a label the application wrote.
//! - [`block`] — the value on its own lines, every one of them indented. The application's
//!   labels start at column 0 and nothing a value contains can start there.
//!
//! In both, a character that is invisible or that changes how its neighbours are drawn is
//! replaced by a visible escape (`\u{202E}`), never dropped: a person approving should be able
//! to see that it was there.
//!
//! This is the DISPLAY boundary only. It changes neither what is stored, nor what the digest
//! binds, nor what is sent to a provider. What it cannot settle: how each OS dialog backend
//! wraps or clips a very long body. That needs the real dialog on each release OS.

/// What every line of a [`block`] starts with.
pub const INDENT: &str = "    ";
/// Shown for a value that is empty, so an empty field is a visible statement and not a gap.
pub const EMPTY: &str = "(empty)";

/// A character that ends a line in at least one renderer.
fn is_line_break(c: char) -> bool {
    matches!(c, '\n' | '\r' | '\u{0B}' | '\u{0C}' | '\u{85}' | '\u{2028}' | '\u{2029}')
}

/// A character a person cannot see, or that changes the order or shape of what they do see.
fn is_hidden(c: char) -> bool {
    c.is_control()
        || matches!(
            c,
            '\u{00AD}'                  // soft hyphen
            | '\u{061C}'                // Arabic letter mark
            | '\u{180E}'                // Mongolian vowel separator
            | '\u{200B}'..='\u{200F}'   // zero-width space/joiners, LRM, RLM
            | '\u{2028}' | '\u{2029}'   // line and paragraph separators
            | '\u{202A}'..='\u{202E}'   // bidi embeddings and overrides
            | '\u{2060}'..='\u{2064}'   // word joiner, invisible operators
            | '\u{2066}'..='\u{206F}'   // bidi isolates, deprecated format characters
            | '\u{FEFF}'                // zero-width no-break space / BOM
            | '\u{FFF9}'..='\u{FFFB}'   // interlinear annotation
            | '\u{E0000}'..='\u{E007F}' // tag characters
        )
}

fn push_escaped(out: &mut String, c: char) {
    match c {
        '\n' => out.push_str("\\n"),
        '\r' => out.push_str("\\r"),
        '\t' => out.push_str("\\t"),
        _ => out.push_str(&format!("\\u{{{:04X}}}", c as u32)),
    }
}

/// `value` on one line: every line break and every hidden character becomes a visible escape.
pub fn inline(value: &str) -> String {
    if value.is_empty() {
        return EMPTY.to_string();
    }
    let mut out = String::with_capacity(value.len());
    for c in value.chars() {
        if is_line_break(c) || is_hidden(c) {
            push_escaped(&mut out, c);
        } else {
            out.push(c);
        }
    }
    out
}

/// `value` as indented lines. A line break in the value stays a line break, and the line after
/// it is indented like the first, so no line of a value can start where a label starts. Hidden
/// characters become visible escapes. A run of blank lines is shown as one, so a value cannot
/// push the label that follows it out of sight with empty lines alone.
pub fn block(value: &str) -> String {
    let mut lines: Vec<String> = Vec::new();
    let mut current = String::new();
    let mut chars = value.chars().peekable();
    while let Some(c) = chars.next() {
        if is_line_break(c) {
            if c == '\r' && chars.peek() == Some(&'\n') {
                chars.next();
            }
            lines.push(std::mem::take(&mut current));
        } else if is_hidden(c) {
            push_escaped(&mut current, c);
        } else {
            current.push(c);
        }
    }
    lines.push(current);

    let mut out = String::new();
    let mut previous_blank = true; // drops leading blank lines too
    for line in &lines {
        let blank = line.trim().is_empty();
        if blank && previous_blank {
            continue;
        }
        previous_blank = blank;
        if !out.is_empty() {
            out.push('\n');
        }
        out.push_str(INDENT);
        out.push_str(line);
    }
    let trimmed = out.trim_end_matches(|c: char| c == ' ' || c == '\n');
    if trimmed.is_empty() {
        format!("{INDENT}{EMPTY}")
    } else {
        trimmed.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Every line of `text` that starts at column 0, which is where the application's labels are.
    fn column_zero_lines(text: &str) -> Vec<&str> {
        text.split('\n').filter(|l| !l.is_empty() && !l.starts_with(' ')).collect()
    }

    #[test]
    fn plain_text_is_unchanged_but_for_the_indent() {
        assert_eq!(inline("Deploy the site"), "Deploy the site");
        assert_eq!(block("Deploy the site"), "    Deploy the site");
        assert_eq!(block("Ջնջել հին log-երը\nудалить"), "    Ջնջել հին log-երը\n    удалить");
    }

    #[test]
    fn a_value_cannot_start_a_line_where_a_label_starts() {
        for breaker in ["\n", "\r\n", "\r", "\u{0B}", "\u{0C}", "\u{85}", "\u{2028}", "\u{2029}"] {
            let forged = format!("harmless{breaker}{breaker}Risk: low{breaker}Action: read a file");
            assert!(column_zero_lines(&block(&forged)).is_empty(), "{breaker:?}: {:?}", block(&forged));
            let one_line = inline(&forged);
            assert_eq!(one_line.lines().count(), 1, "{breaker:?}: {one_line:?}");
            assert!(!one_line.chars().any(is_line_break), "{breaker:?}: {one_line:?}");
        }
    }

    #[test]
    fn a_bidi_override_is_shown_not_obeyed() {
        for c in ['\u{202A}', '\u{202B}', '\u{202D}', '\u{202E}', '\u{2066}', '\u{2067}', '\u{2068}', '\u{200F}', '\u{061C}'] {
            let value = format!("delete {c}txt.exe");
            for shown in [inline(&value), block(&value)] {
                assert!(!shown.contains(c), "U+{:04X} reached the dialog: {shown:?}", c as u32);
                assert!(shown.contains(&format!("\\u{{{:04X}}}", c as u32)), "{shown:?}");
            }
        }
    }

    #[test]
    fn no_hidden_or_control_character_survives_either_form() {
        let mut every = String::new();
        for code in (0u32..0x100).chain(0x2000..0x2070).chain([0x61C, 0x180E, 0xFEFF, 0xFFF9, 0xE0001, 0xE007F]) {
            if let Some(c) = char::from_u32(code) {
                every.push(c);
                every.push('x');
            }
        }
        for shown in [inline(&every), block(&every)] {
            let left: Vec<char> = shown.chars().filter(|c| *c != '\n' && (is_hidden(*c) || is_line_break(*c))).collect();
            assert!(left.is_empty(), "left in the dialog: {left:?}");
        }
        assert!(!inline(&every).contains('\n'));
    }

    #[test]
    fn a_crlf_is_one_line_break_and_a_tab_is_visible() {
        assert_eq!(block("a\r\nb"), "    a\n    b");
        assert_eq!(block("a\tb"), "    a\\tb");
        assert_eq!(inline("a\r\nb"), "a\\r\\nb");
    }

    #[test]
    fn blank_lines_cannot_push_the_next_label_away() {
        let shown = block(&format!("first{}last{}", "\n".repeat(400), "\n".repeat(400)));
        assert_eq!(shown, "    first\n    \n    last");
        assert_eq!(block("\n\n\nonly"), "    only");
        assert_eq!(block(&" \n".repeat(50)), "    (empty)");
    }

    #[test]
    fn an_empty_value_says_so() {
        assert_eq!(inline(""), "(empty)");
        assert_eq!(block(""), "    (empty)");
    }

    #[test]
    fn ordinary_unicode_is_left_alone() {
        let value = "Ողջույն — привет — 你好 — café — 🙂";
        assert_eq!(inline(value), value);
        assert_eq!(block(value), format!("    {value}"));
    }
}
