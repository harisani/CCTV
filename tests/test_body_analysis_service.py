from types import SimpleNamespace
from uuid import uuid4

from app.models import IdentityDecision
from app.services.body_analysis_service import BodyAnalysisService


def build_service() -> BodyAnalysisService:
    settings = SimpleNamespace(
        reid_similarity_threshold=0.78,
        reid_match_margin=0.05,
    )
    return BodyAnalysisService(
        repository=object(),
        settings=settings,
        engine=object(),
        storage=object(),
    )


def candidate(similarity: float, person_id=None):
    return SimpleNamespace(
        similarity=similarity,
        person=SimpleNamespace(id=person_id or uuid4()),
        embedding=SimpleNamespace(id=uuid4()),
    )


def test_body_only_match_is_probable_and_requires_correlation():
    best = candidate(0.91)

    result = build_service()._body_decision([best], 0.9)

    assert result[0] == IdentityDecision.PROBABLE
    assert result[1] == best.person.id
    assert result[5] is True
    assert result[6] == "BODY_ONLY_MATCH_REQUIRES_CORRELATION"


def test_close_body_matches_are_conflict():
    best = candidate(0.88)
    second = candidate(0.85)

    result = build_service()._body_decision([best, second], 0.9)

    assert result[0] == IdentityDecision.CONFLICT
    assert result[5] is True
    assert result[6] == "AMBIGUOUS_BODY_MATCH"


def test_body_similarity_below_threshold_is_unknown():
    best = candidate(0.70)

    result = build_service()._body_decision([best], 0.9)

    assert result[0] == IdentityDecision.UNKNOWN
    assert result[1] is None
    assert result[5] is False


def test_no_labeled_reference_does_not_create_identity():
    result = build_service()._body_decision([], 0.9)

    assert result[0] == IdentityDecision.UNKNOWN
    assert result[1] is None
    assert result[6] == "NO_LABELED_BODY_REFERENCE"
