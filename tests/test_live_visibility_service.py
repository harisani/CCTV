import unittest
from uuid import uuid4

from app.services.live_visibility_service import LiveVisibilityService


class LiveVisibilityServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_counts_latest_tracks_and_deduplicates_reid_across_cameras(self) -> None:
        service = LiveVisibilityService()
        first_camera = uuid4()
        second_camera = uuid4()
        person_id = str(uuid4())

        total, changed = await service.update(
            first_camera,
            [{"tracking_id": 1, "person_id": person_id}, {"tracking_id": 2, "person_id": None}],
        )
        self.assertEqual(total, 2)
        self.assertTrue(changed)

        total, changed = await service.update(
            second_camera,
            [{"tracking_id": 9, "person_id": person_id}],
        )
        self.assertEqual(total, 2)
        self.assertFalse(changed)
        self.assertEqual(await service.total(first_camera), 2)
        self.assertEqual(await service.total(second_camera), 1)

    async def test_empty_latest_frame_and_offline_camera_remove_visible_people(self) -> None:
        service = LiveVisibilityService()
        camera_id = uuid4()
        await service.update(camera_id, [{"tracking_id": 1, "person_id": None}])

        total, changed = await service.update(camera_id, [])
        self.assertEqual(total, 0)
        self.assertTrue(changed)

        total, changed = await service.clear_camera(camera_id)
        self.assertEqual(total, 0)
        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
