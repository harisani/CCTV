from types import SimpleNamespace

from app.models import IdentityDecision
from app.services.biometric_identity_service import BiometricIdentityService


class Repository:
    pass


class Engine:
    @staticmethod
    def cosine_similarity(left, right):
        return sum(a * b for a, b in zip(left, right, strict=True))


def build_service(**overrides):
    values = {
        "biometric_confirmed_threshold": 0.50,
        "biometric_probable_threshold": 0.40,
        "biometric_conflict_margin": 0.05,
    }
    values.update(overrides)
    return BiometricIdentityService(
        Repository(),
        SimpleNamespace(**values),
        engine=Engine(),
        storage=object(),
    )


def test_confirmed_requires_threshold_and_distinct_subject_margin():
    decision, review, reason = build_service()._decision(0.61, 0.08)

    assert decision == IdentityDecision.CONFIRMED
    assert review is False
    assert reason == "THRESHOLD_AND_MARGIN_MET"


def test_close_top_matches_are_conflict_not_forced_identity():
    decision, review, reason = build_service()._decision(0.61, 0.02)

    assert decision == IdentityDecision.CONFLICT
    assert review is True
    assert reason == "AMBIGUOUS_TOP_MATCH"


def test_probable_match_always_requires_review():
    decision, review, _reason = build_service()._decision(0.45, 0.30)

    assert decision == IdentityDecision.PROBABLE
    assert review is True


def test_low_similarity_is_unknown_without_identity():
    decision, review, _reason = build_service()._decision(0.20, 0.30)

    assert decision == IdentityDecision.UNKNOWN
    assert review is False


def test_ranking_uses_second_distinct_subject_not_duplicate_template():
    templates = [
        SimpleNamespace(
            id="a1",
            person_id="person-a",
            external_subject_key=None,
            embedding=[0.61, 0.0],
        ),
        SimpleNamespace(
            id="a2",
            person_id="person-a",
            external_subject_key=None,
            embedding=[0.60, 0.0],
        ),
        SimpleNamespace(
            id="b1",
            person_id="person-b",
            external_subject_key=None,
            embedding=[0.40, 0.0],
        ),
    ]

    ranked = build_service()._rank_distinct_subjects(
        [1.0, 0.0], templates
    )

    assert [item[1].id for item in ranked] == ["a1", "b1"]
