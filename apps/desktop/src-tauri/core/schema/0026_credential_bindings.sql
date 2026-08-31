-- §4's credential binding store: which SLOT of which BUNDLE DIGEST names which
-- REFERENCE. The flow names the slot; this table names where the secret lives.
--
-- WHAT THIS TABLE HOLDS, and the correction that produced it: an `auth_ref`, on
-- the same terms migration 0022 states for `integrations.auth_ref` — a
-- name/handle/path that the ENGINE or the OPERATOR resolves, on the other side
-- of the trust boundary, to a secret they hold.
--
--   e.g.  engine:slack/bot-token   operator:helpdesk-api   keychain:brops/github
--         env:SLACK_BOT_TOKEN      vault:kv/data/brops/smtp#password
--
-- The first version of this migration had a `secret TEXT NOT NULL` column and
-- documented, carefully and at length, that the value sat in plaintext in the
-- desktop's own SQLite file. The documentation was honest and the column was
-- wrong: 0022 already settled the question for this whole process —
--
--   "nothing in this table, this process, or this repository may ever hold the
--    secret. The desktop is deliberately on the untrusted side of the boundary;
--    a credential that got here would be a credential leaked."
--
-- A second table holding what the first forbids is not a smaller version of the
-- same decision. So the CHECK below is 0022's, restated for a NOT NULL column,
-- and `repo::integrations::normalize_auth_ref` — the same function, not a copy
-- of it — states the rule a second time in Rust so a refusal reaches the caller
-- as an explanation instead of a constraint violation.
--
-- WHAT THE CHECK CAN AND CANNOT DO is written out in full in 0022 and is not
-- repeated here, because a second copy is a second thing to drift. Read it
-- there. The one line worth carrying: it cannot tell a reference from a
-- password, so the operating rule lives in the caller, which refuses anything
-- it cannot positively recognise as a reference.
--
-- The binding is to `bundle_digest`, NOT `bundle_id`, and the foreign key is
-- what enforces it. Rebuilding an agent produces a new digest, so every
-- binding it had stops applying and a fresh gated act is required. That is the
-- "swapping a test key for a production key requires a new approval" property
-- obtained structurally, from the key of a table, rather than from a rule
-- somebody has to remember. If that ever feels inconvenient, the inconvenience
-- is the control working.
--
-- ON DELETE CASCADE: retiring a bundle takes its bindings with it. A reference
-- nothing can reach and nobody is looking at is a stale pointer at best and a
-- misleading custody claim at worst.
CREATE TABLE IF NOT EXISTS credential_bindings (
    bundle_digest   TEXT NOT NULL REFERENCES agent_bundles(bundle_digest) ON DELETE CASCADE,
    slot_id         TEXT NOT NULL,
    auth_ref        TEXT NOT NULL
        CHECK (
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
        ),
    bound_at        TEXT NOT NULL,
    PRIMARY KEY (bundle_digest, slot_id)
);
