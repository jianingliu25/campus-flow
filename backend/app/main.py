"""M3 local import; fixture preview stays separate from private source data."""

from contextlib import asynccontextmanager
import asyncio
from contextlib import suppress
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.api.foundation import router
from app.api.imports import router as import_router
from app.config import ROOT, get_settings
from app.db import Database
from app.demo import demo_payload
from app.llm.compatible import ProviderConfig
from app.ingest.previews import PreviewStore
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
        application.state.timezone = configuration.timezone
        application.state.sessions = SessionManager(workspace_id)
        application.state.provider_config = provider_config or ProviderConfig.from_environment()
        application.state.previews = PreviewStore()
        from app.security.credentials import CredentialStore, WindowsVault
        from app.sources.sync import SyncManager
        try:
            vault=WindowsVault()
        except BoundaryError:
            vault=None
        application.state.credentials=CredentialStore(vault)
        application.state.sync=SyncManager(store,application.state.credentials)
        async def expire_previews():
            while True:
                await asyncio.sleep(30)
                application.state.previews.clear_expired()
                application.state.credentials.clear_expired()
        cleaner = asyncio.create_task(expire_previews())
        try:
            yield
        finally:
            cleaner.cancel()
            with suppress(asyncio.CancelledError):
                await cleaner
            application.state.previews.items.clear()
            await application.state.sync.shutdown()
            application.state.credentials.items.clear()
            if owned_db:
                store.close()

    application = FastAPI(title="Campus Flow — M4 dashboard", version="0.4.0", lifespan=lifespan)
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
    application.include_router(import_router)
    from app.api.dashboard import router as dashboard_router
    application.include_router(dashboard_router)
    from app.api.connectors import router as connector_router
    application.include_router(connector_router)
    from app.api.chat import router as chat_router
    application.include_router(chat_router)
    @application.get("/api/health")
    def health():
        return {"status": "ok", "milestone": "M4", "mode": "local-dashboard", "real_sources_enabled": False, "local_import_enabled": True}

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
