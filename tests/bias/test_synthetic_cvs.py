"""Unit tests for the synthetic-CV factory used by COMP-08 bias runner.

Cheap, offline — no API calls, no DB.
"""

from collections import Counter

from tests.bias.synthetic_cvs import build_cvs


def test_build_cvs_yields_exactly_100():
    cvs = build_cvs()
    assert len(cvs) == 100


def test_build_cvs_covers_all_origin_gender_pairs():
    cvs = build_cvs()
    pairs = Counter((c.origin_proxy, c.gender_proxy) for c in cvs)
    expected_origins = {"fr_classic", "ma", "sub_saharan", "eastern_eur"}
    expected_genders = {"male", "female"}
    assert set(p[0] for p in pairs) == expected_origins
    assert set(p[1] for p in pairs) == expected_genders


def test_each_cv_has_expected_fields():
    cvs = build_cvs()
    for c in cvs:
        assert c.cv["name"]
        assert c.cv["email"].endswith("@example.test")
        assert isinstance(c.cv["skills"], list) and c.cv["skills"]
        assert isinstance(c.cv["experiences"], list) and c.cv["experiences"]
        assert c.age_band in {"junior", "mid", "senior"}


def test_archetypes_share_skills_within_same_label():
    """Two CVs of the same archetype must carry the same skill set so that
    score deltas across origin/gender are attributable to the surrogate."""
    cvs = build_cvs()
    by_arch = {}
    for c in cvs:
        by_arch.setdefault(c.archetype, []).append(tuple(c.cv["skills"]))
    for arch, skill_lists in by_arch.items():
        assert len(set(skill_lists)) == 1, (
            f"Archetype {arch} has inconsistent skill sets — bias-test "
            f"comparisons would be invalid."
        )
