from fastapi import status


class BenchmarkError(Exception):
    """Base class for benchmark domain errors surfaced over HTTP."""

    status_code: int = status.HTTP_502_BAD_GATEWAY
    detail: str = "Benchmark error"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class BenchmarkUnavailableError(BenchmarkError):
    status_code = status.HTTP_502_BAD_GATEWAY
    detail = "Satellite benchmark data is currently unavailable"
