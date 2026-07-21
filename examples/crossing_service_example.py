"""Virtual horizontal line crossing example."""

from app.services import CrossingService, VirtualLineConfig
from app.tracker import TrackedDetection

service = CrossingService(
    VirtualLineConfig(
        line_id="front-door",
        line_type="horizontal",
        position=360,
        enter_direction="down",  # y < 360 to y > 360 is ENTER
    )
)

before_line = TrackedDetection(1, (100, 250, 200, 350), 0.9, 0, "person", (150, 300), "down", ())
after_line = TrackedDetection(1, (100, 350, 200, 450), 0.9, 0, "person", (150, 400), "down", ())

print(service.process([before_line]))  # []
print(service.process([after_line]))   # one ENTER event
