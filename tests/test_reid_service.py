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


class FakeSession:
    async def commit(self) -> None:
        pass


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


if __name__ == "__main__":
    unittest.main()
