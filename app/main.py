from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from app.core.config.app_config import app_config
from app.core.database.database import sessionmanager
from app.core.middlewares import LoggingMiddleware
from app.modules.auth.exceptions import AuthError
from app.modules.auth.router import router as auth_router
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    yield
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
