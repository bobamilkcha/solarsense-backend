"""Integration tests for BillsService (DB side), with object storage faked out."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from app.modules.bills.exceptions import BillNotFoundError, InvalidPDFError
from app.modules.bills.parser import ParsedBillFields
from app.modules.bills.service import BillsService
from app.modules.readings.exceptions import SiteNotFoundError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.test_readings_service import _make_site


class _FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    async def ensure_bucket(self, bucket: str) -> None:
        pass

    async def upload_bytes(
        self, bucket: str, object_name: str, data: bytes, content_type: str
    ) -> None:
        self.objects[(bucket, object_name)] = data

    async def get_bytes(self, bucket: str, object_name: str) -> bytes:
        return self.objects[(bucket, object_name)]


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> _FakeStorage:
    storage = _FakeStorage()
    monkeypatch.setattr("app.modules.bills.service.ensure_bucket", storage.ensure_bucket)
    monkeypatch.setattr("app.modules.bills.service.upload_bytes", storage.upload_bytes)
    monkeypatch.setattr("app.modules.bills.service.get_bytes", storage.get_bytes)
    return storage


@pytest.fixture
def fake_parser(monkeypatch: pytest.MonkeyPatch) -> ParsedBillFields:
    fields = ParsedBillFields(
        billing_period_start=date(2026, 9, 1),
        billing_period_end=date(2026, 9, 30),
        kwh_used=350.5,
        tariff_category="Domestic (Tariff A)",
        amount_due=185.40,
        current_charges=180.00,
    )
    monkeypatch.setattr("app.modules.bills.service.parse_bill_pdf", lambda pdf_bytes: fields)
    return fields


async def test_upload_bill_stores_file_and_parsed_fields(
    db: AsyncSession, fake_storage: _FakeStorage, fake_parser: ParsedBillFields
) -> None:
    site = await _make_site(db)
    svc = BillsService(db)

    bill = await svc.upload_bill(
        site.id, company_id=None, filename="sep2026.pdf", pdf_bytes=b"%PDF-fake"
    )

    assert bill.site_id == site.id
    assert bill.filename == "sep2026.pdf"
    assert bill.kwh_used == Decimal("350.50")
    assert bill.amount_due == Decimal("185.40")
    assert bill.current_charges == Decimal("180.00")
    assert bill.billing_period_start == date(2026, 9, 1)


async def test_upload_bill_unknown_site_raises(
    db: AsyncSession, fake_storage: _FakeStorage, fake_parser: ParsedBillFields
) -> None:
    svc = BillsService(db)
    with pytest.raises(SiteNotFoundError):
        await svc.upload_bill(uuid.uuid4(), company_id=None, filename="x.pdf", pdf_bytes=b"x")


async def test_upload_bill_other_company_raises(
    db: AsyncSession, fake_storage: _FakeStorage, fake_parser: ParsedBillFields
) -> None:
    site = await _make_site(db)
    svc = BillsService(db)
    with pytest.raises(SiteNotFoundError):
        await svc.upload_bill(site.id, company_id=uuid.uuid4(), filename="x.pdf", pdf_bytes=b"x")


async def test_upload_bill_parse_failure_raises_invalid_pdf(
    db: AsyncSession, fake_storage: _FakeStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = await _make_site(db)

    def boom(pdf_bytes: bytes) -> ParsedBillFields:
        raise ValueError("not a pdf")

    monkeypatch.setattr("app.modules.bills.service.parse_bill_pdf", boom)

    svc = BillsService(db)
    with pytest.raises(InvalidPDFError):
        await svc.upload_bill(site.id, company_id=None, filename="x.pdf", pdf_bytes=b"not-a-pdf")


async def test_list_bills_returns_uploaded(
    db: AsyncSession, fake_storage: _FakeStorage, fake_parser: ParsedBillFields
) -> None:
    site = await _make_site(db)
    svc = BillsService(db)
    await svc.upload_bill(site.id, company_id=None, filename="a.pdf", pdf_bytes=b"x")
    await svc.upload_bill(site.id, company_id=None, filename="b.pdf", pdf_bytes=b"y")

    bills = await svc.list_bills(site.id, company_id=None)
    assert len(bills) == 2


async def test_get_bill_file_roundtrips_bytes(
    db: AsyncSession, fake_storage: _FakeStorage, fake_parser: ParsedBillFields
) -> None:
    site = await _make_site(db)
    svc = BillsService(db)
    bill = await svc.upload_bill(
        site.id, company_id=None, filename="a.pdf", pdf_bytes=b"original-bytes"
    )

    data, filename = await svc.get_bill_file(bill.id, company_id=None)
    assert data == b"original-bytes"
    assert filename == "a.pdf"


async def test_get_bill_file_unknown_raises(db: AsyncSession, fake_storage: _FakeStorage) -> None:
    svc = BillsService(db)
    with pytest.raises(BillNotFoundError):
        await svc.get_bill_file(uuid.uuid4(), company_id=None)


async def test_get_bill_file_other_company_raises(
    db: AsyncSession, fake_storage: _FakeStorage, fake_parser: ParsedBillFields
) -> None:
    site = await _make_site(db)
    svc = BillsService(db)
    bill = await svc.upload_bill(site.id, company_id=None, filename="a.pdf", pdf_bytes=b"x")

    with pytest.raises(BillNotFoundError):
        await svc.get_bill_file(bill.id, company_id=uuid.uuid4())
