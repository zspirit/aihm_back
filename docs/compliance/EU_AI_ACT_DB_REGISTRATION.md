# EU AI Act database registration kit — COMP-14

**Deadline**: 2026-08-02 — before placing the system on the EU market
(Regulation 2024/1689 Art. 71).

This is the source-of-truth payload for AIHM's entry in the EU AI Act
database (`https://artificialintelligenceact.eu/` portal once open, or
the official EC database when published). When the EC portal opens,
register, fill, and submit — every field below is pre-filled to match
the technical file shipped in `back/docs/compliance/`.

Status: **pending submission** — to be done by the founder before public
go-live.

---

## 1. Provider

- **Legal name**: AIHM SAS
- **Country**: France
- **Contact email**: compliance@aihm.com
- **DPO email**: dpo@aihm.com
- **Authorised representative in the EU**: same (provider is established
  in the EU)

## 2. System identification

- **Trade name**: AIHM (AI Hiring Manager)
- **Internal identifier**: AIHM-V1.0-2026-06
- **Version**: 1.0
- **Type**: high-risk AI system
- **Annex III category**: §4(a) — Employment, workers management and
  access to self-employment, including AI systems intended to be used for
  the recruitment or selection of natural persons (CV screening, job
  matching, interview question generation, scorecard assistance).

## 3. Description

AIHM is a SaaS that helps HR teams pre-screen candidates by:
1. Scoring CVs against a job description (Claude Sonnet 4.6)
2. Conducting an AI-led phone interview (~5 min, persona "Léa")
3. Generating a recruiter-facing scorecard
4. Surfacing matches across candidates × open positions

The system never takes the final hiring decision; a human recruiter always
confirms reject or advance.

## 4. Intended purpose, intended users

- **Purpose**: pre-screening assistance for HR.
- **Users**: HR professionals (recruiter, sourcer, talent acquisition).
- **Affected persons**: job candidates who consent to the IA-assisted
  process.

## 5. Conformity assessment procedure

Annex VI — internal control (admissible for Annex III high-risk systems
under Art. 43 §2). No notified body.

## 6. Technical documentation reference

See:
- `MODEL_CARD.md`
- `TECHNICAL_DOCUMENTATION.md`
- `QUALITY_MANAGEMENT_SYSTEM.md`
- `RISK_MANAGEMENT.md`
- `EU_DECLARATION_OF_CONFORMITY.md`

## 7. Member States where the system is placed on the market or put into
service

- France (primary)
- Other EU Member States — case by case, on tenant onboarding
- Morocco (non-EU) — via local representative

## 8. Compliance with fundamental rights

The system has undergone a Fundamental Rights Impact Assessment (FRIA)
focused on:
- Right to non-discrimination (mitigated via bias monitoring COMP-13)
- Right to a fair recruitment process (mitigated via human-final
  guarantee COMP-01)
- Right to information & explanation (mitigated via ex-ante consent
  COMP-03 and the public explanation endpoint COMP-04)
- Right to data protection (mitigated via DPIA COMP-06 + GDPR
  compliance program)

## 9. Internal records

This registration entry is treated as a living artefact. It is reviewed:
- On every quarterly compliance review
- On any architecture / GPAI / sub-processor change
- On every material change to the conformity-relevant parts of the system

## 10. Submission checklist

- [ ] Account created on the EU AI Act database portal
- [ ] All sections above filled in matching `MODEL_CARD.md`
- [ ] `EU_DECLARATION_OF_CONFORMITY.md` signed by the founder and uploaded
- [ ] Internal-control conformity assessment record uploaded
- [ ] Confirmation email saved in `back/docs/compliance/RECEIPTS/`
- [ ] Public registration ID copied back into `MODEL_CARD.md` §1
