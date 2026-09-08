import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.chat import router
from app.config import get_settings
from app.database.connection import engine
from app.database.migrations import migrate_schema


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(migrate_schema)
    yield
    await engine.dispose()


app = FastAPI(title=os.getenv("APP_NAME", "Rook"), lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().frontend_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-CSRF-Protection"],
)
app.include_router(auth_router)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_, exc: RequestValidationError):
    # Pydantic's default error payload echoes inputs, including login passwords.
    return JSONResponse(
        status_code=422,
        content={"detail": [
            {key: error[key] for key in ("loc", "msg", "type")}
            for error in exc.errors()
        ]},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
