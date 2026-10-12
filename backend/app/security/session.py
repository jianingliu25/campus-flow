"""Ephemeral local sessions: restart invalidates cookies. Never persisted to disk."""

from dataclasses import dataclass
import hashlib
import secrets
from threading import RLock
import time

from app.security.policies import BoundaryError

COOKIE_NAME = "campus_flow_session"


@dataclass
class LocalSession:
    workspace_id: str
    csrf_token: str
    expires_at: float
    active_source_id: str | None = None


class SessionManager:
    def __init__(self, workspace_id, ttl=3600, clock=time.monotonic, capacity=64):
        self.workspace_id, self.ttl, self.clock, self.capacity = workspace_id, ttl, clock, capacity
        self._sessions = {}
        self._lock = RLock()

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def create(self):
        with self._lock:
            now = self.clock()
            self._sessions = {key: session for key, session in self._sessions.items() if session.expires_at > now}
            if len(self._sessions) >= self.capacity:
                raise BoundaryError("SESSION_LIMIT", 429)
            token = secrets.token_urlsafe(32)
            session = LocalSession(self.workspace_id, secrets.token_urlsafe(32), now + self.ttl)
            self._sessions[self.digest(token)] = session
            return token, session

    def get(self, token):
        if not token or len(token) > 200:
            raise BoundaryError("SESSION_REQUIRED", 401)
        with self._lock:
            key = self.digest(token)
            session = self._sessions.get(key)
            if session is None or session.expires_at <= self.clock():
                self._sessions.pop(key, None)
                raise BoundaryError("SESSION_EXPIRED", 401)
            return session

    def revoke(self, token):
        with self._lock:
            self._sessions.pop(self.digest(token), None)


def validate_csrf(session, token):
    if not token or len(token) > 200 or not secrets.compare_digest(session.csrf_token, token):
        raise BoundaryError("CSRF_REQUIRED")
