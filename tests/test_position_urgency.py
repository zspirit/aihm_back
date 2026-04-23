"""Tests unitaires purs de compute_urgency (pas de DB, pas de FastAPI).

Vérifie les bornes (2j, 7j), les cas null, dépassé, et le cas spec
(sla_days=5 créé il y a 4j → urgent).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.position import compute_urgency

NOW = datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "deadline,expected,desc",
    [
        (None, None, "pas de SLA configuré"),
        (NOW - timedelta(days=1), "late", "dépassé d'1 jour"),
        (NOW, "late", "pile à la deadline"),
        (NOW + timedelta(hours=12), "urgent", "reste 12h"),
        (NOW + timedelta(days=2), "urgent", "reste 2j pile"),
        (NOW + timedelta(days=3), "soon", "reste 3j"),
        (NOW + timedelta(days=7), "soon", "reste 7j pile"),
        (NOW + timedelta(days=8), "normal", "reste 8j"),
        (NOW + timedelta(days=30), "normal", "reste 30j"),
    ],
)
def test_compute_urgency_thresholds(deadline, expected, desc):
    assert compute_urgency(deadline, NOW) == expected, desc


def test_spec_case_sla5_created_4d_ago_is_urgent():
    """Cas de la spec utilisateur : sla_days=5, créé il y a 4j → reste 1j → urgent."""
    created = NOW - timedelta(days=4)
    sla_days = 5
    deadline = created + timedelta(days=sla_days)
    assert compute_urgency(deadline, NOW) == "urgent"


def test_naive_datetime_is_treated_as_utc():
    """Si sla_deadline est naive (ce qui ne devrait pas arriver avec TIMESTAMPTZ,
    mais on est défensif), on le traite comme UTC."""
    naive = NOW.replace(tzinfo=None) + timedelta(days=10)
    assert compute_urgency(naive, NOW) == "normal"


def test_now_defaults_to_utcnow_when_not_provided():
    """Sans now explicite, compute_urgency doit toujours renvoyer quelque chose
    de cohérent (pas de crash)."""
    future = datetime.now(timezone.utc) + timedelta(days=100)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    assert compute_urgency(future) == "normal"
    assert compute_urgency(past) == "late"
