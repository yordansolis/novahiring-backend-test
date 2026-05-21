import logging
import sys
import time
import uuid

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.auth import require_admin, require_candidate
from api.interviews import router as interviews_router
from api.jobs import router as jobs_router
from config import get_settings


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
    )


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_logging(settings.LOG_LEVEL)

    app = FastAPI(
        title="NovaHiring API",
        version="0.1.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.middleware("http")
    async def logging_middleware(request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)
        logging.getLogger("nova.access").info(
            "%s %s %s %dms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    app.include_router(jobs_router, prefix="/api/v1/jobs", dependencies=[Depends(require_admin)])
    app.include_router(interviews_router, prefix="/api/v1/interviews", dependencies=[Depends(require_candidate)])

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
