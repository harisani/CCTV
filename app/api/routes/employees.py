from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.api.dependencies import get_employee_service
from app.api.schemas import (
    EmployeeCreate,
    EmployeeImportResponse,
    EmployeeResponse,
    EmployeeUpdate,
    Page,
    RFIDCardCreate,
    RFIDCardResponse,
    RFIDCardUpdate,
)
from app.api.security import require_authenticated_user, require_roles
from app.models import RFIDCard, RFIDCardStatus, User, UserRole
from app.services.employee_service import EmployeeService

router = APIRouter(
    prefix="/employees",
    dependencies=[Depends(require_authenticated_user)],
)

view_roles = (
    UserRole.SUPER_ADMIN,
    UserRole.ADMIN,
    UserRole.SUPERVISOR,
    UserRole.AUDITOR,
)
manage_roles = (UserRole.SUPER_ADMIN, UserRole.ADMIN)
max_employee_csv_bytes = 2 * 1024 * 1024


@router.get("", response_model=Page[EmployeeResponse])
async def list_employees(
    search: str | None = Query(default=None, max_length=150),
    department: str | None = Query(default=None, max_length=120),
    is_active: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    _: User = Depends(require_roles(*view_roles)),
    service: EmployeeService = Depends(get_employee_service),
) -> Page[EmployeeResponse]:
    items, total = await service.employees.list_filtered(
        search=search,
        department=department,
        is_active=is_active,
        offset=offset,
        limit=limit,
    )
    return Page[EmployeeResponse](
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: UUID,
    _: User = Depends(require_roles(*view_roles)),
    service: EmployeeService = Depends(get_employee_service),
) -> EmployeeResponse:
    employee = await service.employees.get(employee_id)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pegawai tidak ditemukan.",
        )
    return EmployeeResponse.model_validate(employee)


@router.post("", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
async def create_employee(
    payload: EmployeeCreate,
    actor: User = Depends(require_roles(*manage_roles)),
    service: EmployeeService = Depends(get_employee_service),
):
    return await service.create_employee(payload, actor)


@router.post("/import", response_model=EmployeeImportResponse)
async def import_employees(
    file: UploadFile = File(),
    actor: User = Depends(require_roles(*manage_roles)),
    service: EmployeeService = Depends(get_employee_service),
) -> EmployeeImportResponse:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Pilih file dengan format .csv.",
        )
    content = await file.read(max_employee_csv_bytes + 1)
    await file.close()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="File CSV kosong.",
        )
    if len(content) > max_employee_csv_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Ukuran file CSV maksimal 2 MB.",
        )
    imported_count, total_rows = await service.import_employees_csv(content, actor)
    return EmployeeImportResponse(
        imported_count=imported_count,
        total_rows=total_rows,
    )


@router.patch("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: UUID,
    payload: EmployeeUpdate,
    actor: User = Depends(require_roles(*manage_roles)),
    service: EmployeeService = Depends(get_employee_service),
):
    employee = await service.employees.get(employee_id)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pegawai tidak ditemukan.",
        )
    return await service.update_employee(employee, payload, actor)


@router.get("/{employee_id}/cards", response_model=Page[RFIDCardResponse])
async def list_employee_cards(
    employee_id: UUID,
    card_status: RFIDCardStatus | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    _: User = Depends(require_roles(*view_roles)),
    service: EmployeeService = Depends(get_employee_service),
) -> Page[RFIDCardResponse]:
    if await service.employees.get(employee_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pegawai tidak ditemukan.",
        )
    items, total = await service.cards.list_by_employee_filtered(
        employee_id,
        card_status=card_status,
        offset=offset,
        limit=limit,
    )
    return Page[RFIDCardResponse](
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/{employee_id}/cards",
    response_model=RFIDCardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_employee_card(
    employee_id: UUID,
    payload: RFIDCardCreate,
    actor: User = Depends(require_roles(*manage_roles)),
    service: EmployeeService = Depends(get_employee_service),
):
    employee = await service.employees.get(employee_id)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pegawai tidak ditemukan.",
        )
    return await service.register_card(employee, payload, actor)


@router.patch(
    "/{employee_id}/cards/{card_id}",
    response_model=RFIDCardResponse,
)
async def update_employee_card(
    employee_id: UUID,
    card_id: UUID,
    payload: RFIDCardUpdate,
    actor: User = Depends(require_roles(*manage_roles)),
    service: EmployeeService = Depends(get_employee_service),
) -> RFIDCard:
    card = await service.cards.get(card_id)
    if card is None or card.employee_id != employee_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kartu RFID tidak ditemukan untuk pegawai ini.",
        )
    return await service.update_card(card, payload, actor)
