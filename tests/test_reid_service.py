import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.reid import PersonReIdentificationService


class TestSettings:
    reid_model = "osnet_x1_0"
    reid_device = "auto"
    reid_image_width = 128
    reid_image_height = 256
    reid_embedding_dimension = 512
    reid_similarity_threshold = 0.75
    reid_match_margin = 0.05
    reid_candidate_limit = 50
    reid_min_quality_score = 0.45
    reid_embedding_retention_days = 90
    reid_min_crop_width = 32
    reid_min_crop_height = 64
    reid_sharpness_reference = 150.0


class FakeSession:
    async def commit(self) -> None:
        pass


class TemplateRepository:
    def __init__(self, candidates: list[object]) -> None:
        self.candidates = candidates
        self.people = []
        self.templates = []
        self.matches = []
        self.session = FakeSession()

    async def find_embedding_candidates(self, *_args: object, **_kwargs: object) -> list[object]:
        return self.candidates

    async def add(self, person: object) -> object:
        self.people.append(person)
        return person

    async def add_embedding(self, template: object) -> object:
        if getattr(template, "id", None) is None:
            template.id = uuid4()
        self.templates.append(template)
        return template

    async def record_match(self, embedding_id: object, **_kwargs: object) -> None:
        self.matches.append(embedding_id)


class FakeRepository:
    def __init__(self, persons: list[object]) -> None:
        self.persons = persons
        self.session = FakeSession()

    async def list_with_embeddings(self) -> list[object]:
        return self.persons

    async def add(self, person: object) -> object:
        self.persons.append(person)
        return person


def embedding(first: float = 1.0) -> list[float]:
    return [first] + [0.0] * 511


class ReIdentificationServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_person_above_similarity_threshold(self) -> None:
        person = SimpleNamespace(id=uuid4(), reid_embedding={"vector": embedding()}, last_seen_at=None)
        service = PersonReIdentificationService(TestSettings(), embedding_extractor=lambda _crop: embedding())
        result = await service.identify_embedding(embedding(), FakeRepository([person]))
        self.assertTrue(result.matched_existing)
        self.assertEqual(result.person_id, person.id)
        self.assertEqual(result.similarity, 1.0)

    async def test_creates_person_below_similarity_threshold(self) -> None:
        repository = FakeRepository([])
        service = PersonReIdentificationService(
            TestSettings(),
            person_factory=lambda **fields: SimpleNamespace(id=uuid4(), **fields),
        )
        result = await service.identify_embedding(embedding(), repository)
        self.assertFalse(result.matched_existing)
        self.assertEqual(len(repository.persons), 1)
        self.assertEqual(len(repository.persons[0].reid_embedding["vector"]), 512)

    async def test_marks_close_competing_candidates_as_ambiguous(self) -> None:
        first = SimpleNamespace(id=uuid4(), last_seen_at=SimpleNamespace())
        second = SimpleNamespace(id=uuid4(), last_seen_at=SimpleNamespace())
        repository = TemplateRepository([
            SimpleNamespace(person=first, embedding=SimpleNamespace(id=uuid4()), similarity=0.86),
            SimpleNamespace(person=second, embedding=SimpleNamespace(id=uuid4()), similarity=0.84),
        ])
        service = PersonReIdentificationService(
            TestSettings(),
            person_factory=lambda **fields: SimpleNamespace(id=uuid4(), **fields),
        )
        result = await service.identify_embedding(embedding(), repository, quality_score=0.9)
        self.assertEqual(result.decision, "AMBIGUOUS")
        self.assertFalse(result.matched_existing)
        self.assertTrue(repository.people[0].needs_review)
        self.assertEqual(len(repository.templates), 1)

    async def test_accepts_candidate_only_when_threshold_and_margin_pass(self) -> None:
        from datetime import UTC, datetime

        person = SimpleNamespace(id=uuid4(), last_seen_at=datetime.now(UTC))
        reference_id = uuid4()
        repository = TemplateRepository([
            SimpleNamespace(person=person, embedding=SimpleNamespace(id=reference_id), similarity=0.91),
            SimpleNamespace(person=SimpleNamespace(id=uuid4()), embedding=SimpleNamespace(id=uuid4()), similarity=0.80),
        ])
        service = PersonReIdentificationService(TestSettings())
        result = await service.identify_embedding(embedding(), repository, quality_score=0.88)
        self.assertEqual(result.decision, "MATCHED")
        self.assertTrue(result.matched_existing)
        self.assertEqual(repository.matches, [reference_id])


if __name__ == "__main__":
    unittest.main()
