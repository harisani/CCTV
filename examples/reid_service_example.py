"""Match a YOLO person crop to a persisted Person identity."""

import cv2

from app.database.session import SessionLocal
from app.reid import PersonReIdentificationService
from app.repository import PersonRepository


async def identify_person() -> None:
    frame = cv2.imread("frame.jpg")
    if frame is None:
        raise SystemExit("Place an input image at frame.jpg")
    reid = PersonReIdentificationService()
    crop = reid.crop_person(frame, (100, 80, 260, 420))
    async with SessionLocal() as session:
        result = await reid.identify(crop, PersonRepository(session))
        print(result.person_id, result.matched_existing, result.similarity)


if __name__ == "__main__":
    import asyncio

    asyncio.run(identify_person())
