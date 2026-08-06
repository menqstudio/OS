---
id: marketing-brand
version: 1.1.0
status: active
---

# Marketing Brand

## Trigger
Use when the task is positioning, messaging architecture, brand voice/identity guidelines, campaign concepting, landing/ad/email copy, content strategy, or naming with brand fit. Also for auditing existing assets against brand and ICP. Do NOT use for paid-media bidding execution or CRM plumbing (route to sales-revenue-growth ops), nor for legal claims review (route to legal-compliance-contracts).

## Inputs
- ICP / target segment, the job-to-be-done, and the primary competitor/alternative.
- Product truth: what it does, the differentiated value, and proof points (metrics, customers, mechanism).
- Brand guardrails: voice attributes, tone, do/don't lexicon, visual constraints.
- Channel, funnel stage, and the single conversion action for this asset.

## Workflow
1. Nail positioning first: for [ICP] who [need], [product] is the [category] that [differentiated benefit], unlike [alternative], because [proof]. Everything downstream inherits this.
2. Build the messaging hierarchy: one core value prop, 3 supporting pillars, each backed by a concrete proof point — no unsubstantiated superlatives.
3. Match message to funnel stage: awareness = problem/POV, consideration = differentiation/proof, decision = risk-reversal/CTA.
4. Draft copy in brand voice: lead with customer outcome not features, use their language from research, keep one clear CTA per asset, cut jargon.
5. Ensure every claim is substantiated; flag any comparative or regulated claim ("#1", "guaranteed", health/financial) for legal review before use.
6. Design the test: define the metric that matters per stage (CTR, conversion, activation), the hypothesis, and a variant worth testing — not cosmetic A/B noise.
7. Check consistency: voice, visual, and message align across the touchpoints in the journey.

## Outputs
- Positioning statement and messaging hierarchy (value prop + pillars + proof).
- Channel-ready copy variants with one CTA each, in brand voice.
- Claims list with substantiation status and legal-review flags.
- Test plan: hypothesis, metric, variant, and success threshold.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Never publish, launch, or spend budget without grant. Do not fabricate metrics, customer names, testimonials, or comparative claims. Regulated/comparative claims fail closed pending legal review. Ambiguous mutation targets fail closed.

## Handoffs
Comparative, health, financial, or guarantee claims to legal-compliance-contracts. Sales enablement and pipeline handoff to sales-revenue-growth. Co-marketing with partners to partnership-channel-bd. Localization to language-mastery. Escalate cross-domain decisions to the owning SST role; medium, high, and critical work requires an independent verifier; publish/spend hands off only to the authorized executor.

## Verification
Confirm positioning names ICP, differentiation, and proof; every claim has a substantiation source; regulated/comparative claims are flagged; each asset has one CTA and a defined success metric; voice matches guardrails. Any metric or testimonial without a verifiable source remains RED.

## Failure and rollback
Stop on undefined ICP, missing product proof, unverifiable claims, or a request to publish/spend without grant. Discard the draft, restore prior assets, and report the missing input. Never call unsubstantiated or unlaunched copy final or GREEN.
