# Risk Management System — EU AI Act Art. 9

**System**: AIHM (AI Hiring Manager)
**Version**: 1.0
**Last review**: 2026-06-08
**Next review**: 2026-12-08 (or earlier if scoring methodology / GPAI changes)

This is a living document. The risk register is reviewed at minimum every
six months and on every "major change" (Art. 43 §4):
- Switch of underlying GPAI (Claude → other)
- Change in tenant scoring weights default
- Addition of a new AI-touched workflow (e.g. video interview, biometric)

---

## 1. Risk identification methodology

Risks are identified by combining:
- Top-down threat modelling (which Annex III §4 risks plausibly apply
  to recruitment AI?)
- Bottom-up incident harvesting (CNIL fines, EU AI Act enforcement
  examples, our own post-mortems)
- Adversarial review (what would a market surveillance authority test?)

Each risk is scored:
- **Likelihood**: 1 (rare) → 5 (almost certain)
- **Impact**: 1 (cosmetic) → 5 (fundamental rights breach)
- **Inherent risk** = L × I (before mitigation)
- **Residual risk** = L' × I' (after mitigation)

We accept residual risk ≤ 6. Anything above must have an action plan
with an owner and a deadline.

---

## 2. Risk register

### R-01 — Bias in CV scoring (gender, origin, age proxy)
- **Source**: Pre-training biases of the underlying GPAI propagate to
  pertinence scores; surname/origin proxies may correlate with score even
  in absence of explicit attribute.
- **Inherent**: L=4 × I=5 = 20
- **Mitigation**:
  - Prompt explicitly forbids inference on protected attributes (see
    `back/app/workers/cv_processing.py` score_cv prompt §3 "REGLES
    STRICTES")
  - Human-in-the-loop for any reject (COMP-01)
  - Bias-testing harness on 100 synthetic CVs (COMP-08) baseline before v1.0
    public; quarterly continuous monitoring (COMP-13)
  - Score breakdown exposes the *evidence* used (project names extracted),
    making spurious correlations easier to spot
- **Residual**: L=2 × I=4 = 8 — above threshold, action: deploy bias
  monitoring dashboard in v1.1 (POST-04)
- **Owner**: founder

### R-02 — Hallucinated competence
- **Source**: Model fabricates a skill or experience not actually present
  in the CV.
- **Inherent**: L=3 × I=3 = 9
- **Mitigation**:
  - Prompt requires every claimed match to cite the *project* where the
    skill is demonstrated
  - `keyword stuffing` rule reduces confidence rather than amplifying it
  - Recruiter sees the raw extracted explanation, can dispute
- **Residual**: L=2 × I=2 = 4 — acceptable

### R-03 — Prompt injection through CV / phone call
- **Source**: Candidate injects "ignore previous instructions" or
  equivalent in their CV / spoken answer to manipulate scoring or
  classification.
- **Inherent**: L=4 × I=3 = 12
- **Mitigation**:
  - Safety classifier (Claude Haiku) on every phone answer; labels
    `injection` are short-circuited to `redirect`
  - CV parsing prompt isolates the CV content in a clearly-bounded
    section and explicitly tells the model the CV is untrusted data
  - Audit logs surface the safety classification reason
- **Residual**: L=2 × I=2 = 4 — acceptable

### R-04 — Unauthorised cross-tenant data access
- **Source**: Bug / misconfiguration that lets tenant A read tenant B's
  candidates.
- **Inherent**: L=2 × I=5 = 10
- **Mitigation**:
  - Multi-tenant isolation: `tenant_id` on every table; every list/get
    query filters on `current_user.tenant_id`
  - Tests covering bulk endpoints and cross-tenant request shape
  - Code review explicitly checks tenant scoping on any new endpoint
- **Residual**: L=1 × I=5 = 5 — acceptable; monitored via security
  test additions on every new endpoint

### R-05 — Loss of availability
- **Source**: Single-host VPS, no HA. A crash interrupts service.
- **Inherent**: L=3 × I=3 = 9
- **Mitigation**:
  - Nightly Postgres backup + offsite copy
  - Caddy auto-restart, systemd-supervised processes
  - Documented restore procedure
- **Residual**: L=2 × I=2 = 4 — acceptable for v1.0 (no SLA contract yet);
  raise to HA Postgres when first enterprise SLA contract is signed.

### R-06 — Re-identification from transcripts
- **Source**: Candidate accidentally discloses sensitive personal data
  during the call; transcript stored in MinIO.
- **Inherent**: L=3 × I=4 = 12
- **Mitigation**:
  - Retention capped at 6 months for audio + transcript
  - Transcripts pseudonymised in exports (candidate id, not name)
  - Access restricted to tenant admins; recruiter sees scorecard only
- **Residual**: L=2 × I=3 = 6 — acceptable

### R-07 — IA recommendation interpreted as final decision
- **Source**: Recruiter unfamiliar with EU AI Act treats the IA's
  recommendation as binding, skipping human review.
- **Inherent**: L=3 × I=4 = 12
- **Mitigation**:
  - Notification wording: "IA recommande rejet — revue humaine requise"
  - Pipeline status `flagged_for_review` is visually distinct
  - Audit log separates `cv_reject_recommended` (actor=ai) from
    `candidate_rejected` (actor=human)
  - Onboarding doc + tooltip on the recommendation card explains the
    obligation
- **Residual**: L=2 × I=3 = 6 — acceptable

### R-08 — Vendor lock-in / sudden GPAI deprecation
- **Source**: Anthropic deprecates `claude-sonnet-4-6` model without
  migration window.
- **Inherent**: L=2 × I=4 = 8
- **Mitigation**:
  - Model name centralised in `settings.ANTHROPIC_MODEL`
  - Prompts compatible with neighbouring Claude versions
  - `tts.py` already abstracts TTS provider (edge / openai / elevenlabs)
- **Residual**: L=2 × I=2 = 4 — acceptable

---

## 3. Residual-risk acceptance

The founder, acting as the provider's responsible person, accepts the
residual risks listed above as of 2026-06-08. The next acceptance
review is scheduled for 2026-12-08.

---

## 4. Linked artefacts

- DPIA template: see `/api/v1/compliance/dpia.md` endpoint
- Bias-testing harness: `back/tests/bias/` (COMP-08)
- Quarterly bias report: `back/docs/compliance/BIAS_REPORTS/` (COMP-13)
- Audit log schema + helpers: `back/app/services/audit.py`
- Incident response: `back/docs/compliance/INCIDENT_RESPONSE.md` (TODO)
