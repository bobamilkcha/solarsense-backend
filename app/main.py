import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from app.core.config.app_config import app_config
from app.core.database.database import sessionmanager
from app.core.deps import logger
from app.core.middlewares import LoggingMiddleware
from app.core.storage.object_storage import ensure_bucket
from app.modules.auth.exceptions import AuthError
from app.modules.auth.router import router as auth_router
from app.modules.benchmark.exceptions import BenchmarkError
from app.modules.benchmark.router import router as benchmark_router
from app.modules.bills.exceptions import BillsError
from app.modules.bills.router import bills_router
from app.modules.bills.router import router as bills_sites_router
from app.modules.bills.service import BILLS_BUCKET
from app.modules.projects.exceptions import ProjectsError
from app.modules.projects.router import router as projects_router
from app.modules.readings.exceptions import ReadingsError
from app.modules.readings.mqtt import MQTTSubscriber
from app.modules.readings.router import router as readings_router
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    mqtt_subscriber = MQTTSubscriber(asyncio.get_running_loop())
    mqtt_subscriber.connect()

    try:
        await ensure_bucket(BILLS_BUCKET)
    except Exception as exc:
        # Don't take the whole app down if MinIO isn't reachable yet (e.g.
        # local dev before `docker compose up` has finished).
        await logger.a_error("minio_bucket_setup_failed", error=str(exc))

    yield
    mqtt_subscriber.disconnect()
    await sessionmanager.close()


app = FastAPI(
    title=app_config.PROJECT_NAME,
    lifespan=lifespan,
    docs_url="/docs" if app_config.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if app_config.ENVIRONMENT != "production" else None,
)


@app.exception_handler(AuthError)
async def auth_error_handler(_: Request, exc: AuthError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(ReadingsError)
async def readings_error_handler(_: Request, exc: ReadingsError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(ProjectsError)
async def projects_error_handler(_: Request, exc: ProjectsError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(BenchmarkError)
async def benchmark_error_handler(_: Request, exc: BenchmarkError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(BillsError)
async def bills_error_handler(_: Request, exc: BillsError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.add_middleware(LoggingMiddleware)

if app_config.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_config.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(readings_router)
app.include_router(benchmark_router)
app.include_router(bills_sites_router)
app.include_router(bills_router)
