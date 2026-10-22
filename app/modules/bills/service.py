import uuid
from collections.abc import Sequence

from app.core.storage.object_storage import ensure_bucket, get_bytes, upload_bytes
from app.models import Project, Site, TNBBill
from app.modules.bills.exceptions import BillNotFoundError, InvalidPDFError
from app.modules.bills.parser import parse_bill_pdf
from app.modules.readings.exceptions import SiteNotFoundError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

BILLS_BUCKET = "tnb-bills"


class BillsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upload_bill(
        self,
        site_id: uuid.UUID,
        company_id: uuid.UUID | None,
        filename: str,
        pdf_bytes: bytes,
    ) -> TNBBill:
        site = await self._authorized_site(site_id, company_id)

        try:
            fields = parse_bill_pdf(pdf_bytes)
        except Exception as exc:
            # pdfplumber/pypdfium2 raise assorted exception types on non-PDF input.
            raise InvalidPDFError from exc

        safe_filename = filename.replace("/", "_").replace("\\", "_")
        object_key = f"{site_id}/{uuid.uuid4()}_{safe_filename}"

        await ensure_bucket(BILLS_BUCKET)
        await upload_bytes(BILLS_BUCKET, object_key, pdf_bytes, "application/pdf")

        bill = TNBBill(
            site_id=site.id,
            object_key=object_key,
            filename=safe_filename,
            billing_period_start=fields.billing_period_start,
            billing_period_end=fields.billing_period_end,
            kwh_used=fields.kwh_used,
            tariff_category=fields.tariff_category,
            amount_due=fields.amount_due,
            current_charges=fields.current_charges,
        )
        self.db.add(bill)
        await self.db.commit()
        await self.db.refresh(bill)
        return bill

    async def list_bills(
        self, site_id: uuid.UUID, company_id: uuid.UUID | None
    ) -> Sequence[TNBBill]:
        await self._authorized_site(site_id, company_id)

        result = await self.db.scalars(
            select(TNBBill).where(TNBBill.site_id == site_id).order_by(TNBBill.created_at.desc())
        )
        return result.all()

    async def get_bill_file(
        self, bill_id: uuid.UUID, company_id: uuid.UUID | None
    ) -> tuple[bytes, str]:
        bill = await self.db.get(TNBBill, bill_id)
        if bill is None:
            raise BillNotFoundError

        if company_id is not None:
            site = await self.db.get(Site, bill.site_id)
            project = await self.db.get(Project, site.project_id) if site is not None else None
            if project is None or project.company_id != company_id:
                # Bill exists, just not in the caller's company — 404, not 403.
                raise BillNotFoundError

        data = await get_bytes(BILLS_BUCKET, bill.object_key)
        return data, bill.filename

    async def _authorized_site(self, site_id: uuid.UUID, company_id: uuid.UUID | None) -> Site:
        site = await self.db.get(Site, site_id)
        if site is None:
            raise SiteNotFoundError

        if company_id is not None:
            project = await self.db.get(Project, site.project_id)
            if project is None or project.company_id != company_id:
                raise SiteNotFoundError

        return site
