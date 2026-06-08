# Quality Management System (QMS) — EU AI Act Art. 17

**System**: AIHM (AI Hiring Manager)
**Version**: 1.0 (Release 2026-06)
**Author**: AIHM SAS
**Review cadence**: every 6 months or on major model bump

This QMS satisfies the obligation of EU AI Act Art. 17 for providers of
high-risk AI systems. It is intentionally pragmatic and proportionate to
AIHM's current organisation (one-person engineering team, < 10 active
tenants in beta phase). It scales as the company grows.

---

## 1. Compliance strategy

- **Frame of reference**: EU AI Act + GDPR + French Loi Informatique &
  Libertés + Moroccan Law 09-08 where the candidate is processed in
  Morocco.
- **Risk-based**: AIHM is high-risk under Annex III §4(a). All controls
  in this QMS are calibrated to that classification.
- **Living docs**: every doc in `back/docs/compliance/` is versioned in
  git and reviewed at the cadence noted in its header. Major drift
  triggers an immediate review (see §5).

## 2. Design controls

- **Specifications**: each major change goes through a written plan or a
  Github issue with acceptance criteria.
- **Prompt versioning**: every Claude prompt has a `model_version`
  constant in code and a `prompt_hash` written to the audit log on every
  call (COMP-02).
- **Anti-discrimination by design**: system prompts explicitly forbid
  inference on personality, gender, origin, religion, age and similar
  protected attributes.
- **Human-final by design**: the back-end refuses to set candidate
  `pipeline_status='rejected'` from a worker; only authenticated user
  actions can flip that status.

## 3. Development & verification procedures

- **Source control**: git, branch `master` canonical (see CLAUDE memory
  `branch_policy`).
- **Local validation**: `npm run build` must pass before push (see CLAUDE
  memory `npm_build_in_ci`); pytest must pass for backend changes.
- **Code review**: solo author = self-review; each change is structured
  as a small focused commit with a "Why" line in the message for
  non-obvious work.
- **AI Act change-review**: any change to a Claude prompt, model name, or
  AI-touched workflow must bump `model_version` and update the model card.

## 4. Data management

- **Inventory**: see DPIA (`back/docs/compliance/` generated per tenant
  via `/api/v1/compliance/dpia.md`).
- **Quality**: parsed CV data validated by Pydantic schemas before storage.
- **Retention**: tenant-configurable `data_retention_days`, default 365
  for candidates / 180 for audio.
- **Subject rights**: ex-ante info on consent page, public explanation
  endpoint, support inbox dpo@aihm.com.

## 5. Post-market monitoring & change control

- All AI calls audit-logged (Art. 12 satisfied via `services/audit.py`).
- Quarterly compliance review checklist:
  1. Re-export DPIA per tenant, compare to previous quarter (look for
     volume / threshold drift)
  2. Re-run bias-testing harness (`back/tests/bias/`)
  3. Inspect override-rate trend per tenant
  4. Refresh model card with any new model/version
  5. Refresh technical documentation if architecture changed
- Serious incident reporting (Art. 73): documented at
  `back/docs/compliance/INCIDENT_RESPONSE.md` (not yet written; trigger
  before first paying customer).

## 6. Records management

| Record | Location | Retention |
|---|---|---|
| Audit logs (AI + human actions) | Postgres `audit_logs` | 5 years |
| Consent grants/revocations | Postgres `consents` | 5 years post-revocation |
| Bias-testing reports | `back/docs/compliance/BIAS_REPORTS/` | 5 years |
| DPIA snapshots | downloaded by tenant admin | tenant-managed |
| Model card history | git history | repository lifetime |

## 7. Roles & responsibilities

| Role | Holder | Responsibility |
|---|---|---|
| Provider (Art. 16) | AIHM SAS | overall AI Act compliance |
| DPO | TBD — escalation to founder until appointment | GDPR subject rights, complaints |
| Tech lead | Founder | engineering, model selection |
| Compliance owner | Founder | this QMS, incident reporting |

DPO appointment will be triggered when AIHM passes either threshold:
- > 250 candidates processed per day across the platform
- > 5 enterprise tenants
(both indicators tracked monthly).

## 8. Sub-processors & supply chain

- Anthropic, OpenAI (optional), ElevenLabs (optional), Twilio, Resend,
  Hetzner, Cloudflare (CDN). See DPIA §1.4.
- Each sub-processor change requires a written impact assessment and an
  update of the sub-processor list in the DPIA template.

## 9. Cooperation with authorities

- CNIL (FR) — primary supervisory authority.
- CNDP (MA) — Moroccan supervisory authority.
- Market surveillance authority for AI Act (per Member State of deployment).

Access to the technical file is granted on written request within 30
working days.
