---
id: language-mastery
version: 1.1.0
status: active
---

# Language Mastery

## Trigger
Use when the task is translation, localization, transcreation, multilingual copy adaptation, register/tone tuning, terminology/glossary management, or grammar and style correction across languages. Also for adapting a message to a locale's cultural conventions. Do NOT use for the strategic content decision itself (route to communication-writing-negotiation or marketing-brand); this skill governs linguistic execution.

## Inputs
- Source text, source language, and one or more target languages/locales.
- Purpose and register (formal/informal, marketing/legal/technical), and audience/region.
- Glossary, brand voice, do-not-translate list, and any prior approved translations (translation memory).
- Constraints: character limits (UI strings), formality (T-V distinction), regional variant (e.g., es-ES vs es-419).

## Workflow
1. Identify content type and choose the right mode: literal for legal/technical, transcreation for marketing, functional for UI — do not mistranslate intent for words.
2. Apply the supplied glossary and translation memory first; keep do-not-translate terms verbatim; flag any term with no approved equivalent.
3. Translate meaning, not surface: preserve idiom by finding the locale's equivalent, adjust register and T-V formality to audience, and respect regional variant.
4. Localize non-text: dates, numbers, currency, units, name order, and address formats to locale conventions; handle plural rules and gender agreement correctly.
5. Fit constraints: respect UI character limits and placeholder/variable tokens; never break interpolation syntax or truncate meaning silently.
6. Cultural check: screen for imagery, humor, or references that don't transfer or could offend in the target market; propose adaptations.
7. Back-translate or spot-check the riskiest segments to confirm meaning survived; list every assumption and ambiguity for reviewer sign-off.

## Outputs
- Target-language text with register and locale conventions applied.
- Glossary additions/flags and any do-not-translate confirmations.
- List of ambiguities, untranslatable terms, and cultural adaptations needing human review.
- Note on regional variant and formality choices made.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Do not invent terminology for legal/regulated content; flag for expert review instead. Never publish or ship strings without grant. Ambiguous mutation targets fail closed.

## Handoffs
Legally binding translations (contracts, compliance notices) to legal-compliance-contracts for equivalence sign-off. Brand voice decisions to marketing-brand. Strategic messaging to communication-writing-negotiation. Escalate cross-domain decisions to the owning SST role; medium, high, and critical work requires an independent verifier (ideally a native reviewer); publish actions hand off only to the authorized executor.

## Verification
Confirm meaning is preserved (back-translation on risky segments), glossary and do-not-translate terms honored, locale formatting correct, interpolation tokens intact, register matches audience, and no untranslatable term silently guessed. Regulated content without expert equivalence review remains RED.

## Failure and rollback
Stop on missing target locale, absent glossary for regulated terms, broken variable tokens, or a request to ship strings without grant. Discard the draft, restore the source, and report the blocker. Never mark an unreviewed regulated translation GREEN.
