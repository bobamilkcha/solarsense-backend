import uuid
from typing import Annotated

from app.modules.auth.deps import CurrentUser, company_scope
from app.modules.bills import schemas
from app.modules.bills.deps import BillsServiceDep
from fastapi import APIRouter, File, UploadFile, status
from fastapi.responses import Response

router = APIRouter(prefix="/sites", tags=["bills"])
bills_router = APIRouter(prefix="/bills", tags=["bills"])


@router.post(
    "/{site_id}/bills", response_model=schemas.TNBBillResponse, status_code=status.HTTP_201_CREATED
)
async def upload_bill(
    site_id: uuid.UUID,
    current_user: CurrentUser,
    service: BillsServiceDep,
    file: Annotated[UploadFile, File()],
):
    pdf_bytes = await file.read()
    return await service.upload_bill(
        site_id, company_scope(current_user), file.filename or "bill.pdf", pdf_bytes
    )


@router.get("/{site_id}/bills", response_model=list[schemas.TNBBillResponse])
async def list_bills(site_id: uuid.UUID, current_user: CurrentUser, service: BillsServiceDep):
    return await service.list_bills(site_id, company_scope(current_user))


@bills_router.get("/{bill_id}/file")
async def download_bill_file(
    bill_id: uuid.UUID, current_user: CurrentUser, service: BillsServiceDep
):
    data, filename = await service.get_bill_file(bill_id, company_scope(current_user))
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
