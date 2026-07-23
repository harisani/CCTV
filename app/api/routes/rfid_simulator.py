"""Admin-only endpoints for testing RFID workflows without physical hardware."""

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_rfid_simulator_service
from app.api.schemas import (
    Page,
    RFIDAccessEventResponse,
    RFIDSimulatorCardOption,
    RFIDSimulatorOptionsResponse,
    RFIDSimulatorReaderResponse,
    RFIDSimulatorTapRequest,
    RFIDSimulatorTapResponse,
)
from app.api.security import require_roles
from app.models import (
    AccessDirection,
    AccessEvent,
    AccessEventStatus,
    RFIDReaderDirection,
    User,
    UserRole,
)
from app.services.rfid_simulator_service import RFIDSimulatorService

router = APIRouter(prefix="/rfid/simulator")
simulator_roles = (UserRole.SUPER_ADMIN, UserRole.ADMIN)


def serialize_access_event(event: AccessEvent) -> RFIDAccessEventResponse:
    payload = event.raw_payload or {}
    return RFIDAccessEventResponse(
        id=event.id,
        external_event_id=event.external_event_id,
        reader_code=event.reader.code,
        reader_name=event.reader.name,
        card_number=event.credential_identifier,
        card_id=event.card_id,
        employee_id=event.employee_id,
        employee_number=event.employee.employee_number if event.employee else None,
        employee_name=event.employee.full_name if event.employee else None,
        direction=event.direction,
        status=event.status,
        status_reason=event.status_reason,
        occurred_at=event.occurred_at,
        expires_at=event.expires_at,
        simulated=payload.get("source") == "rfid_simulator",
    )


@router.get("/options", response_model=RFIDSimulatorOptionsResponse)
async def get_simulator_options(
    _: User = Depends(require_roles(*simulator_roles)),
    service: RFIDSimulatorService = Depends(get_rfid_simulator_service),
) -> RFIDSimulatorOptionsResponse:
    cards = await service.list_card_options()
    return RFIDSimulatorOptionsResponse(
        enabled=True,
        reader=RFIDSimulatorReaderResponse(
            code=service.settings.rfid_simulator_reader_code.strip().upper(),
            name=service.settings.rfid_simulator_reader_name.strip(),
            location=service.settings.rfid_simulator_reader_location.strip() or None,
            direction=RFIDReaderDirection.BIDIRECTIONAL,
        ),
        cards=[
            RFIDSimulatorCardOption(
                card_number=card.card_number,
                label=card.label,
                employee_id=card.employee_id,
                employee_number=card.employee.employee_number,
                employee_name=card.employee.full_name,
                department=card.employee.department,
            )
            for card in cards
        ],
        event_ttl_seconds=service.settings.rfid_simulator_event_ttl_seconds,
    )


@router.post("/tap", response_model=RFIDSimulatorTapResponse)
async def simulate_rfid_tap(
    payload: RFIDSimulatorTapRequest,
    actor: User = Depends(require_roles(*simulator_roles)),
    service: RFIDSimulatorService = Depends(get_rfid_simulator_service),
) -> RFIDSimulatorTapResponse:
    event, created = await service.simulate_tap(payload, actor)
    return RFIDSimulatorTapResponse(
        created=created,
        event=serialize_access_event(event),
    )


@router.get("/events", response_model=Page[RFIDAccessEventResponse])
async def list_simulated_events(
    direction: AccessDirection | None = None,
    event_status: AccessEventStatus | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    _: User = Depends(require_roles(*simulator_roles)),
    service: RFIDSimulatorService = Depends(get_rfid_simulator_service),
) -> Page[RFIDAccessEventResponse]:
    events, total = await service.list_events(
        direction=direction,
        event_status=event_status,
        offset=offset,
        limit=limit,
    )
    return Page[RFIDAccessEventResponse](
        items=[serialize_access_event(event) for event in events],
        total=total,
        offset=offset,
        limit=limit,
    )
