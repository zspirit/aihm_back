"""Platform layer (modular monolith).

Shared primitives that let independent modules (ATS, screening, timesheet,
invoicing, ...) cohabit and be composed per tenant — without importing each
other. See .claude/specs/adr/ADR-05-composition-modules-entitlements.md.

POC scope: event bus + entitlements + People/Party unification.
"""
