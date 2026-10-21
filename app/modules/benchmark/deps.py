from typing import Annotated

from app.core.deps import DBSession
from app.modules.benchmark.service import BenchmarkService
from fastapi import Depends


def get_benchmark_service(db: DBSession) -> BenchmarkService:
    return BenchmarkService(db)


BenchmarkServiceDep = Annotated[BenchmarkService, Depends(get_benchmark_service)]
