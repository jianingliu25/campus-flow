"""M2 local foundation; fixture preview stays separate from private source data."""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.api.foundation import router
from app.config import ROOT, get_settings
from app.db import Database
from app.demo import demo_payload
from app.llm.compatible import ProviderConfig
from app.security.http import LocalBoundaryMiddleware
from app.security.policies import BoundaryError
from app.security.session import SessionManager


def create_app(settings=None, database=None, provider_config=None):
    @asynccontextmanager
    async def lifespan(application):
        configuration = settings or get_settings()
        owned_db = database is None
        store = database or Database(configuration.data_dir)
        store.migrate()
        workspace_id = store.ensure_workspace(configuration.timezone)
        application.state.database = store
        application.state.sessions = SessionManager(workspace_id)
        application.state.provider_config = provider_config or ProviderConfig.from_environment()
        try:
            yield
        finally:
            if owned_db:
                store.close()

    application = FastAPI(title="Campus Flow — M2 local foundation", version="0.2.0", lifespan=lifespan)
    application.add_middleware(LocalBoundaryMiddleware)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @application.exception_handler(BoundaryError)
    async def boundary_error(request, error):
        return JSONResponse({"code": error.code}, error.status, headers={"Cache-Control": "no-store"})

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse({"code": "INVALID_REQUEST", "fields": [list(item["loc"]) for item in error.errors()]}, 422)

    @application.exception_handler(SQLAlchemyError)
    async def storage_error(request, error):
        return JSONResponse({"code": "STORE_UNAVAILABLE"}, 503)

    application.include_router(router)
    @application.get("/api/health")
    def health():
        return {"status": "ok", "milestone": "M2", "mode": "local-foundation", "real_sources_enabled": False}

    @application.get("/api/demo")
    def demo():
        return demo_payload(settings or get_settings())

    dist = ROOT / "frontend/dist"
    if (dist / "assets").is_dir():
        application.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @application.get("/")
    def index():
        path = dist / "index.html"
        if not path.is_file():
            raise HTTPException(503, "Build frontend first: python scripts/manage.py build")
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    @application.get("/favicon.svg", include_in_schema=False)
    def favicon():
        return FileResponse(ROOT / "frontend/public/favicon.svg", media_type="image/svg+xml")
    return application


app = create_app()
