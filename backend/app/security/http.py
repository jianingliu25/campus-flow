"""Exact origin, fetch-metadata and bounded-body checks before private routes."""

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.security.policies import BoundaryError
from app.security.session import COOKIE_NAME, validate_csrf


class LocalBoundaryMiddleware:
    def __init__(self, app, max_body=262144):
        self.app, self.max_body = app, max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        private = request.url.path.startswith("/api/") and request.url.path not in {"/api/health", "/api/demo"}
        unsafe = request.method not in {"GET", "HEAD", "OPTIONS"}
        async def guarded_send(message):
            if private and message["type"] == "http.response.start":
                message = {**message, "headers": [(key, value) for key, value in message.get("headers", []) if key.lower() != b"cache-control"] + [(b"cache-control", b"no-store")]}
            await send(message)
        if private:
            origin = request.headers.get("origin")
            expected = str(request.base_url).rstrip("/")
            if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"} or (origin is not None and origin != expected) or (unsafe and origin is None):
                return await JSONResponse({"code": "ORIGIN_REJECTED"}, 403)(scope, receive, send)
        if unsafe:
            limit = self.max_body
            if request.url.path == "/api/imports/preview":
                try:
                    source_context(request)  # before allocating a large upload buffer
                except BoundaryError as error:
                    return await JSONResponse({"code": error.code}, error.status)(scope, receive, send)
                limit = 10 * 1024 * 1024
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > limit:
                    return await JSONResponse({"code": "BODY_TOO_LARGE"}, 413)(scope, receive, send)
                if not message.get("more_body", False):
                    break
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            return await self.app(scope, replay, guarded_send)
        return await self.app(scope, receive, guarded_send)


def local_session(request: Request):
    manager = getattr(request.app.state, "sessions", None)
    if manager is None:
        raise BoundaryError("SESSION_REQUIRED", 401)
    session = manager.get(request.cookies.get(COOKIE_NAME))
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        validate_csrf(session, request.headers.get("x-csrf-token"))
    return session


def source_context(request: Request):
    from app.security.policies import SourceContext
    session = local_session(request)
    if session.active_source_id is None:
        raise BoundaryError("SELECT_SOURCE_FIRST", 409)
    if request.headers.get("x-campusflow-source") != session.active_source_id:
        raise BoundaryError("SOURCE_SELECTION_CHANGED", 409)
    return SourceContext(session.workspace_id, session.active_source_id)
