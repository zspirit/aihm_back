# Technical documentation — EU AI Act Art. 11 + Annex IV

**System**: AIHM (AI Hiring Manager)
**Version**: 1.0 (Release 2026-06)
**Authoring date**: 2026-06-08
**Author**: AIHM SAS — engineering

This document is the EU AI Act Annex IV technical file. It is kept
internally and made available on request to market surveillance authorities
(Art. 23 §1) and notified bodies. Where reasonable it mirrors the
post-market monitoring system (Art. 72) so a single update propagates.

---

## 1. General description (Annex IV §1)

### 1.1 Intended purpose
AIHM is a multi-tenant SaaS that assists HR teams with:
- Automated CV scoring against a job description
- Outbound IA-conducted phone screening interviews (~5 min)
- Scorecard synthesis from the transcript
- Recruiter-facing pipeline and matching tools

### 1.2 Foreseeable misuse
- Use to make final hire/no-hire decisions without human review (mitigated:
  the back-end refuses to set `pipeline_status='rejected'` from an automated
  worker — see `back/app/api/v1/candidates/crud.py` and
  `back/app/workers/cv_processing.py`).
- Use on minors (out-of-scope per Terms; no tenant onboarding for staffing
  of <18 candidates).
- Personality/biometric inference (interdicted in system prompts; no
  emotional or biometric voice analysis library is integrated).

### 1.3 Versioning
- Repository: `aihm-monorepo` (front + back)
- Branch policy: `master` canonical, releases tagged `v1.0`, `v1.1`, ...
- Each AI model use site embeds a `model_version` constant (e.g. `2026-04`).

## 2. System architecture (Annex IV §2)

### 2.1 Component diagram (text form)

```
[Recruiter browser] --HTTPS-->  Caddy --reverse-proxy-->  FastAPI (back)
                                                            |
                                                            |--SQL-->   Postgres
                                                            |--cache--> Redis
                                                            |--queue--> Celery worker
                                                            |--object-> MinIO
                                                            |--LLM-->   Anthropic API
                                                            |--TTS-->   edge-tts (default) / OpenAI nova (optional)
                                                            |--voice--> Twilio (PSTN)
                                                            |--mail-->  Resend
```

### 2.2 AI components inventory
| Component | Model | Where it runs | Purpose |
|---|---|---|---|
| CV scoring | Claude Sonnet 4.6 | `back/app/workers/cv_processing.py` | Pertinence score |
| Profile quality | Claude Sonnet 4.6 | `back/app/workers/cv_processing.py` | CV quality 0-100 |
| Question generation | Claude Sonnet 4.6 | `back/app/workers/question_generation.py` | 3 questions tailored to position |
| Safety classifier | Claude Haiku | `back/app/services/call_safety.py` | normal/off_scope/injection/empty |
| Scorecard | Claude Sonnet 4.6 | `back/app/services/scorecard.py` | Synthesized scorecard from transcript |
| Matching | Claude Sonnet 4.6 | `back/app/api/v1/matching.py` | N×M matching |
| Copilot | Claude Sonnet 4.6 | `back/app/api/v1/copilot.py` | Recruiter-facing chat |
| STT | OpenAI Whisper v3 | Twilio infrastructure | Speech to text |
| TTS | edge-tts (default) | `back/app/services/tts.py` | Voice synthesis FR |

## 3. Data (Annex IV §3)

### 3.1 Training data
AIHM does NOT train its own foundation models. The underlying GPAI (Claude)
is trained by Anthropic on data documented in their own GPAI transparency
report.

### 3.2 Operational data
- Candidate CV: uploaded by recruiter or candidate, stored in MinIO
- Phone call audio + transcript: stored 6 months in MinIO
- Scoring outputs: stored in Postgres on `candidates` / `applications` tables
- Audit logs: stored 5 years in Postgres `audit_logs` table

### 3.3 Data preparation
- CV PDF/DOCX → text via `unstructured` + custom Claude prompt
- No PII enrichment from external sources
- No facial / voice biometric features extracted

## 4. Risk management (Annex IV §5)

Lives in `back/docs/compliance/RISK_MANAGEMENT.md`. Summary:
- Identified risks: scoring bias, hallucination, unauthorised access,
  re-identification from transcripts, availability loss.
- Each risk has at least one mitigation control with an owner and a
  monitoring metric.

## 5. Validation procedures (Annex IV §6)

### 5.1 Functional validation
- pytest suite: `back/tests/`
- Frontend unit tests: `front/src/**/__tests__/`
- E2E manual test plan: `design-review/TEST_PLAN.md`
- E2E manual test report (2026-05-04): `design-review/TEST_REPORT.md`

### 5.2 Bias validation
- Bias-testing harness: 100 synthetic CVs, axes gender / surname-origin /
  age-proxy. Output: distribution of scores per protected attribute,
  highlight |Δ| > 5 pts as a regression.
- COMP-13: quarterly automated re-run + report generation.

### 5.3 Adversarial validation
- Call-safety classifier evaluated against injection prompts (off-scope
  questions, jailbreak attempts, "ignore previous instructions" patterns).
- `back/tests/test_call_safety.py` covers known patterns.

## 6. Cybersecurity & operational measures (Annex IV §7)

- TLS 1.2+ via Caddy (auto-renewed Let's Encrypt)
- JWT auth + refresh tokens (15min access / 30day refresh)
- bcrypt password hashing (12 rounds)
- Multi-tenant isolation: every model has `tenant_id`, every query filters
- OAuth tokens encrypted at rest with Fernet
- Rate limiting per IP on authentication endpoints
- Backups: Postgres dump nightly, MinIO replicated, retention 30 days
- Incident response: contact security@aihm.com, SLA 24h ack / 72h triage

## 7. Post-market monitoring (Art. 72)

- All AI calls written to `audit_logs` with model, version, prompt_hash,
  confidence
- Daily aggregate dashboard for the provider:
  - call success rate (target > 95%)
  - safety classifier error rate (target < 2%)
  - recruiter override rate (drift indicator)
- Reports: see `back/docs/compliance/POST_MARKET_REPORTS/` (created
  quarterly).

## 8. Declaration of conformity

See `back/docs/compliance/EU_DECLARATION_OF_CONFORMITY.md`.
