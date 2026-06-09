# AIHM Model Card

**Version**: 1.0 (Release 2026-06)
**Last updated**: 2026-06-08
**Public URL**: https://aihm.com/about/ai-transparency

This Model Card documents the AI components of AIHM, an EU AI Act
high-risk system (Annex III §4 — Employment, workers management and access
to self-employment). It is intended for candidates, recruiters, deploying
organisations, auditors and regulators.

---

## 1. System identity

| Field | Value |
|---|---|
| System name | AIHM (AI Hiring Manager) |
| Provider | AIHM SAS (France) |
| Purpose | Assist HR teams with CV scoring, screening calls, scorecards |
| EU AI Act class | High-risk — Annex III §4(a) (recruitment) |
| EU AI Act DB ID | `pending` (registered before 2026-08-02) |
| GPAI dependency | Anthropic Claude Sonnet 4.6 (general-purpose AI model) |

## 2. AI components

### 2.1 CV scoring & profile quality
- **Model**: Claude Sonnet 4.6 (`claude-sonnet-4-6`)
- **Provider**: Anthropic PBC (USA, SCC EU 2021)
- **Input**: parsed CV (text), job description, scoring weights
- **Output**: numeric score 0-100 + JSON breakdown (skills / experience / education)
- **Decision power**: recommendation only; never auto-rejects
- **Audit log action**: `cv_scoring`, `profile_scoring`, `cv_reject_recommended`

### 2.2 Conversational screening call
- **Models**:
  - Anthropic Claude Sonnet 4.6 — question generation, safety classification,
    scorecard synthesis
  - OpenAI Whisper v3 — speech-to-text (running via Twilio)
  - Edge-TTS (Henri Neural) — default text-to-speech (no transfer outside the EU)
  - Optional: OpenAI tts-1 nova FR if `TTS_PROVIDER=openai` (used when
    streaming TTS becomes necessary for VOICE-07)
- **Persona**: "Léa", explicitly disclosed as AI at call start and end
  (EU AI Act Art. 50)
- **Decision power**: produces a scorecard; never auto-progresses or rejects
  the candidate

### 2.3 Matching N×M
- **Model**: Claude Sonnet 4.6
- **Input**: position requirements × candidate profile
- **Output**: scored matches for recruiter consideration

### 2.4 Copilot assistant
- **Model**: Claude Sonnet 4.6
- **Scope**: read-only assistant for recruiters, no candidate-facing output

## 3. Intended use

- **In-scope**: pre-screening of HR candidates by professional recruiters
  inside a tenant organisation.
- **Out-of-scope** (explicit interdicts):
  - Personality, emotion, biometric, or socio-economic inference
  - Final hire/no-hire decisions without human approval
  - Background checks, criminal record screening, social media OSINT
  - Determining wage levels or conditions of employment
  - Use on minors

## 4. Performance & limitations

### 4.1 Known limitations
- Performance on CVs not written in French has not been formally evaluated.
- Phone-call conversational quality is degraded on low-bandwidth GSM calls
  (mu-law 8 kHz). VoIP > 16 kHz performs noticeably better.
- The scoring model has limited recall on senior profiles whose CV is
  unstructured prose without a clear "skills" section.

### 4.2 Validation
- Functional E2E test suite covers CRUD, pipeline, multi-tenant isolation,
  bulk import, approval gates (last full run: 2026-05-04, see
  `design-review/TEST_REPORT.md`).
- Bias-testing on 100 synthetic CVs across gender / surname-origin /
  age-proxy axes: scheduled for COMP-08 before public release.

### 4.3 Confidence calibration
- The `confidence_score` returned in audit logs is the model's self-reported
  confidence, normalised to 0-1. It MUST NOT be interpreted as a calibrated
  probability — it is provided for traceability and trend monitoring only.

## 5. Human oversight (Art. 14)

- Final decisions (reject, advance, hire) always require an authenticated
  recruiter action; the IA never sets `pipeline_status='rejected'`.
- The IA's `cv_reject_recommended` action is logged with
  `decision_status='pending_human_review'` and surfaced as an in-app
  notification with the wording "IA recommande rejet — revue humaine requise".
- Recruiters can override any AI score and trigger a "contest evaluation"
  approval flow.

## 6. Transparency to candidates (Art. 50, Art. 86 + GDPR Art. 22)

- Consent page discloses ex-ante: system identity, automation scope,
  human-final guarantee, right to a fully human review, professional-only
  criteria.
- Public endpoint `/public/explanation/{token}` lets a candidate inspect
  every AI decision affecting them and submit a written explanation
  request (30-day response SLA).
- All AI decisions are persisted in the `audit_logs` table with
  `actor='ai'`, `model`, `model_version`, `confidence_score`, `prompt_hash`
  (SHA-256/12 chars), `summary`.

## 7. Data & training

- AIHM does NOT train or fine-tune the underlying language models.
- Anthropic operates under a no-train policy on API customer data by
  default (confirmed in their commercial terms).
- Candidate data is NOT shared with third parties beyond the sub-processors
  listed in the DPIA.

## 8. Bias monitoring (Art. 10)

- Bias-testing harness on 100 synthetic CVs (gender / origin / age-proxy):
  v1.0 baseline scheduled.
- Continuous monitoring (COMP-13): light quarterly automated report aggregating
  score distributions by job title, gender (where declared), region.
- Recruiter override rate per tenant tracked as a drift indicator.

## 9. Change log

| Date | Version | Change |
|---|---|---|
| 2026-06-08 | 1.0 | Initial public model card |

## 10. Contact

- **Provider**: AIHM SAS — contact@aihm.com
- **DPO**: dpo@aihm.com
- **Compliance**: compliance@aihm.com
- **Security**: security@aihm.com
