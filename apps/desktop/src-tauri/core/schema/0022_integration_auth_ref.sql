-- Phase 9 (Integrations): give a connector a place to name WHERE its credential lives,
-- without the desktop ever holding the credential.
--
-- WHY: the rebuilt Integrations surface reports four independent facts per connector, and
-- one of them — credential custody — was permanently stuck at "no reference" because the
-- record had no column to read. `credentialCustodyOf` in the frontend already reads an
-- `authRef` field precisely so this migration lights it up. This adds that column.
--
-- WHAT `auth_ref` IS: a REFERENCE — a name/handle/path that the ENGINE or the OPERATOR
-- resolves, on the other side of the Phase-9 trust boundary, to a secret they hold.
--   e.g.  engine:slack/bot-token   operator:helpdesk-api   keychain:brops/github
--         env:SLACK_BOT_TOKEN      vault:kv/data/brops/smtp#password
--
-- WHAT `auth_ref` IS NOT — and what this whole schema is not: it is NOT the secret, and
-- nothing in this table, this process, or this repository may ever hold the secret. The
-- desktop is deliberately on the untrusted side of the boundary; a credential that got
-- here would be a credential leaked. In the same register as `repo::integrations::set_status`,
-- which "records the desired state; it does not itself reach any external service":
-- writing an `auth_ref` records an INTENDED handoff target. It does not prove the secret
-- exists, is valid, is reachable, or is the right one — and it must never be read as
-- proof of any of those. It cannot promote a connector to `connected_verified`; that
-- verdict still requires locally-enabled AND a probe that genuinely answered.
--
-- NULLABLE, AND NULL IS THE HONEST DEFAULT: every row that exists today gets NULL, which
-- reads back as "no reference" — not an error, and specifically not an empty string, which
-- a caller could mistake for a configured-but-blank reference. There is NO backfill and
-- there can never be one: inventing a reference for a connector nobody configured would be
-- a fabricated fact on a surface whose entire purpose is to only state proven ones.
--
-- ── THE CHECK: what it can and cannot catch ────────────────────────────────────────────
-- The constraint below makes it structurally HARD — not impossible — to store something
-- secret-shaped. Stated honestly:
--
--   IT CAN:
--     * bound the length (3..160 chars), so a PEM body, a long token blob, or a pasted
--       key file cannot fit;
--     * confine the alphabet to [A-Za-z0-9._:/@+-], which rejects whitespace and newlines
--       (so a multi-line PEM/private key cannot be stored at all) and rejects '=' (so
--       padded base64 material is refused);
--     * require the shape `scheme:locator` with `scheme` from a closed, documented set —
--       raw credentials essentially never carry one of these prefixes, so a paste of a
--       bare API key is refused outright;
--     * reject the well-known key-material prefixes listed below wherever they begin a
--       ':'-delimited segment (JWTs, OpenAI/Stripe-style `sk-`, GitHub `ghp_`/`github_pat_`,
--       GitLab `glpat-`, Slack `xox?-`, AWS `AKIA`/`ASIA`, Google `AIza`/`ya29.`, npm,
--       Shopify, and a PEM armor header).
--
--   IT CANNOT — and no CHECK constraint ever could:
--     * tell a reference from a password. `engine:hunter2` is a perfectly well-formed
--       reference and a perfectly good password; the database cannot know which it is.
--     * detect entropy. A 40-character random secret with no recognised prefix
--       (`engine:9f2c...`) satisfies every rule above.
--     * catch a scheme it has never heard of, or key material from a vendor whose prefix
--       is not on the list. The list is a floor, not a filter.
--     * make a stored reference TRUE. It constrains shape only, never meaning.
--
--   Therefore the operating rule stays where it belongs — in the caller, in
--   `repo::integrations::normalize_auth_ref`, which states the same rule a second time and
--   REFUSES anything it cannot positively recognise as a reference. If it is unclear
--   whether a value is a reference or a secret, it is a secret, and it is refused.
--
-- SQLite note: a CHECK added by ALTER TABLE ... ADD COLUMN binds every future INSERT and
-- UPDATE, including ones issued by anything else that opens this database file. It is NOT
-- retroactively evaluated against existing rows — which is harmless here, because every
-- existing row receives NULL and NULL is explicitly allowed.

ALTER TABLE integrations ADD COLUMN auth_ref TEXT
    CHECK (
        auth_ref IS NULL
        OR (
            -- Bounded length: long enough to name something, far too short to be a key blob.
            length(auth_ref) BETWEEN 3 AND 160
            -- Reference alphabet only: no whitespace, no newlines, no quotes, no '=' padding.
            AND auth_ref NOT GLOB '*[^A-Za-z0-9._:/@+-]*'
            -- Must be `scheme:locator` with a scheme this build understands. Adding a scheme
            -- is a NEW forward migration, never an edit to this one.
            AND substr(auth_ref, 1, instr(auth_ref, ':'))
                IN ('engine:', 'operator:', 'keychain:', 'env:', 'vault:')
            -- ...and the locator after that colon is not empty.
            AND length(auth_ref) > instr(auth_ref, ':')
            -- Obvious key material, wherever it starts a ':'-delimited segment.
            AND auth_ref NOT GLOB '*:eyJ*'              -- JWT ( {"  base64url-encoded )
            AND auth_ref NOT GLOB '*:sk-*'              -- OpenAI / Anthropic style
            AND auth_ref NOT GLOB '*:sk_*'              -- Stripe secret key
            AND auth_ref NOT GLOB '*:pk_*'              -- Stripe publishable key
            AND auth_ref NOT GLOB '*:rk_*'              -- Stripe restricted key
            AND auth_ref NOT GLOB '*:gh[opsru]_*'       -- GitHub tokens (ghp_/gho_/ghs_/ghr_/ghu_)
            AND auth_ref NOT GLOB '*:github_pat_*'      -- GitHub fine-grained PAT
            AND auth_ref NOT GLOB '*:glpat-*'           -- GitLab PAT
            AND auth_ref NOT GLOB '*:xox[abceoprs]-*'   -- Slack tokens
            AND auth_ref NOT GLOB '*:AKIA*'             -- AWS access key id
            AND auth_ref NOT GLOB '*:ASIA*'             -- AWS temporary access key id
            AND auth_ref NOT GLOB '*:AIza*'             -- Google API key
            AND auth_ref NOT GLOB '*:ya29.*'            -- Google OAuth access token
            AND auth_ref NOT GLOB '*:npm_*'             -- npm automation token
            AND auth_ref NOT GLOB '*:shpat_*'           -- Shopify access token
            AND auth_ref NOT GLOB '*-----BEGIN*'        -- PEM armor, wherever it appears
        )
    );

-- Reading the page asks "which connectors name a reference at all?" far more often than it
-- asks for a particular reference, and the partial index keeps NULL rows (the overwhelming
-- majority, and the honest default) out of the index entirely.
CREATE INDEX IF NOT EXISTS idx_integrations_auth_ref
    ON integrations(auth_ref) WHERE auth_ref IS NOT NULL;
