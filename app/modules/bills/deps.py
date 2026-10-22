from typing import Annotated

from app.core.deps import DBSession
from app.modules.bills.service import BillsService
from fastapi import Depends


def get_bills_service(db: DBSession) -> BillsService:
    return BillsService(db)


BillsServiceDep = Annotated[BillsService, Depends(get_bills_service)]
