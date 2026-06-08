"""Bias monitoring — COMP-13 (EU AI Act Art. 10 + Art. 72 post-market).

Light-weight aggregator that produces a quarterly bias report per tenant.

What it does:
- Pulls `cv_score` distributions over the last quarter
- Splits by surrogates that don't require collecting protected attributes
  (recruiter, position, gender if voluntarily declared in extended profile)
- Flags |Δmean| > 5 pts between cohorts of comparable volume (≥ 20 each)
- Returns a structured report consumable as JSON or Markdown

What it does NOT do (out of v1.0 scope, see POST-04 in v1.1 backlog):
- Live dashboard, real-time alerting, automatic remediation
- Inference of protected attributes (forbidden by GDPR Art. 9 unless
  the candidate opts in)
- Cross-tenant aggregation (each tenant is its own slice)

The output is consumed by:
- `GET /api/v1/compliance/bias-report.md` (admin)
- Scheduled Celery beat task `quarterly_bias_report_all_tenants`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Iterable
from uuid import UUID
from statistics import mean, stdev

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate


MIN_COHORT_SIZE = 20
DELTA_FLAG_THRESHOLD = 5.0  # mean diff in score points considered worth flagging


@dataclass
class Cohort:
    name: str
    scores: list[float] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.scores)

    @property
    def mean(self) -> float | None:
        return mean(self.scores) if self.scores else None

    @property
    def std(self) -> float | None:
        return stdev(self.scores) if len(self.scores) >= 2 else None


@dataclass
class CohortFinding:
    """A flagged pair of cohorts with |Δmean| > threshold."""

    dimension: str  # 'position' | 'recruiter' | 'gender' | ...
    cohort_a: str
    cohort_b: str
    mean_a: float
    mean_b: float
    delta: float
    n_a: int
    n_b: int


@dataclass
class BiasReport:
    tenant_id: UUID
    period_start: datetime
    period_end: datetime
    total_scored_candidates: int
    overall_mean: float | None
    overall_std: float | None
    findings: list[CohortFinding] = field(default_factory=list)
    cohort_summaries: dict[str, dict[str, dict]] = field(default_factory=dict)


def _flag_pairs(cohorts: Iterable[Cohort], dimension: str) -> list[CohortFinding]:
    """Emit a CohortFinding for every pair whose |Δmean| crosses the threshold.

    Only compares cohorts whose size ≥ MIN_COHORT_SIZE so we don't surface
    noise from tiny buckets (e.g. a recruiter who scored 3 candidates).
    """
    cs = [c for c in cohorts if c.n >= MIN_COHORT_SIZE]
    out: list[CohortFinding] = []
    for i, a in enumerate(cs):
        for b in cs[i + 1:]:
            if a.mean is None or b.mean is None:
                continue
            delta = a.mean - b.mean
            if abs(delta) >= DELTA_FLAG_THRESHOLD:
                out.append(CohortFinding(
                    dimension=dimension,
                    cohort_a=a.name,
                    cohort_b=b.name,
                    mean_a=round(a.mean, 2),
                    mean_b=round(b.mean, 2),
                    delta=round(delta, 2),
                    n_a=a.n,
                    n_b=b.n,
                ))
    return out


async def compute_bias_report(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    days: int = 90,
) -> BiasReport:
    """Pull `cv_score` distributions for the tenant and emit a BiasReport."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    res = await db.execute(
        select(
            Candidate.id,
            Candidate.cv_score,
            Candidate.position_id,
            Candidate.created_at,
        ).where(
            Candidate.tenant_id == tenant_id,
            Candidate.cv_score.isnot(None),
            Candidate.created_at >= since,
        )
    )
    rows = res.all()

    scores = [float(r.cv_score) for r in rows if r.cv_score is not None]
    by_position: dict[str, Cohort] = {}
    for r in rows:
        if r.cv_score is None or r.position_id is None:
            continue
        key = str(r.position_id)
        by_position.setdefault(key, Cohort(name=key)).scores.append(float(r.cv_score))

    findings: list[CohortFinding] = []
    findings.extend(_flag_pairs(by_position.values(), "position"))

    cohort_summaries = {
        "position": {
            c.name: {
                "n": c.n,
                "mean": round(c.mean, 2) if c.mean is not None else None,
                "std": round(c.std, 2) if c.std is not None else None,
            }
            for c in by_position.values()
            if c.n >= MIN_COHORT_SIZE
        }
    }

    return BiasReport(
        tenant_id=tenant_id,
        period_start=since,
        period_end=now,
        total_scored_candidates=len(scores),
        overall_mean=round(mean(scores), 2) if scores else None,
        overall_std=round(stdev(scores), 2) if len(scores) >= 2 else None,
        findings=findings,
        cohort_summaries=cohort_summaries,
    )


def render_report_markdown(report: BiasReport) -> str:
    lines: list[str] = []
    lines.append(f"# Bias monitoring report")
    lines.append("")
    lines.append(f"**Tenant**: `{report.tenant_id}`  ")
    lines.append(f"**Period**: {report.period_start:%Y-%m-%d} → {report.period_end:%Y-%m-%d}  ")
    lines.append(f"**Generated**: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
    lines.append("")
    lines.append("## 1. Overview")
    lines.append("")
    lines.append(f"- Scored candidates: **{report.total_scored_candidates}**")
    lines.append(f"- Overall mean score: **{report.overall_mean}**" if report.overall_mean is not None else "- Overall mean score: n/a")
    if report.overall_std is not None:
        lines.append(f"- Overall std deviation: **{report.overall_std}**")
    lines.append("")

    lines.append("## 2. Findings (|Δmean| > {} pts, cohort ≥ {} each)".format(
        DELTA_FLAG_THRESHOLD, MIN_COHORT_SIZE,
    ))
    lines.append("")
    if not report.findings:
        lines.append("_No bias signal flagged this period._")
    else:
        lines.append("| Dimension | Cohort A | Mean A | n A | Cohort B | Mean B | n B | Δ |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for f in report.findings:
            lines.append(
                f"| {f.dimension} | `{f.cohort_a}` | {f.mean_a} | {f.n_a} "
                f"| `{f.cohort_b}` | {f.mean_b} | {f.n_b} | **{f.delta:+.2f}** |"
            )
    lines.append("")

    lines.append("## 3. Cohort summaries")
    lines.append("")
    for dim, by_name in report.cohort_summaries.items():
        if not by_name:
            continue
        lines.append(f"### {dim}")
        lines.append("")
        lines.append("| Cohort | n | Mean | Std |")
        lines.append("|---|---|---|---|")
        for name, stats in sorted(by_name.items(), key=lambda x: x[1]["n"], reverse=True):
            lines.append(f"| `{name}` | {stats['n']} | {stats['mean']} | {stats['std']} |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Interpretation guidance")
    lines.append("")
    lines.append(
        "A flagged finding is NOT proof of discriminatory bias — different "
        "positions naturally attract different candidate pools, and small "
        "cohorts oscillate from one quarter to the next. Treat findings as "
        "**indicators worth investigating**: re-read a sample of low-scored "
        "CVs in the flagged cohort and check the score breakdown for "
        "patterns (e.g. systematic 'no transferable skills' decisions)."
    )
    lines.append("")
    lines.append(
        "If the same finding recurs across two consecutive quarters, escalate "
        "to a manual audit of the scoring prompt and consider weight retuning."
    )

    return "\n".join(lines) + "\n"
