"""Ephemeral previews, bound to session/source/policy and consumed once."""

from dataclasses import dataclass
import hashlib
import secrets
from threading import RLock
import time

from app.security.policies import BoundaryError


@dataclass
class Preview:
    owner: str
    ctx: object
    policy_version: int
    mails: list
    report: dict
    expires: float
    size: int


class PreviewStore:
    def __init__(self, clock=time.monotonic, ttl=600):
        self.clock, self.ttl = clock, ttl
        self.items, self.lock = {}, RLock()

    @staticmethod
    def owner(session):
        return hashlib.sha256(session.csrf_token.encode()).hexdigest()

    def clear_expired(self):
        with self.lock:
            self.items = {id: item for id, item in self.items.items() if item.expires > self.clock()}

    def add(self, session, ctx, version, mails, report):
        self.clear_expired()
        owner = self.owner(session)
        size = sum(len(mail.body_text.encode()) for mail in mails)
        with self.lock:
            if len(self.items) >= 8 or sum(item.owner == owner for item in self.items.values()) >= 2 or sum(item.size for item in self.items.values()) + size > 20 * 1024 * 1024:
                raise BoundaryError("PREVIEW_CAPACITY", 429)
            id = secrets.token_urlsafe(24)
            self.items[id] = Preview(owner, ctx, version, mails, report, self.clock() + self.ttl, size)
            return id

    def take(self, id, session, ctx):
        self.clear_expired()
        with self.lock:
            item = self.items.get(id)
            if item is None or item.owner != self.owner(session) or item.ctx != ctx:
                raise BoundaryError("PREVIEW_NOT_FOUND", 404)
            self.items.pop(id)
            return item

    def discard(self, id, session, ctx):
        self.take(id, session, ctx)


def filter_scope(mails, scope, now):
    from datetime import timedelta
    cutoff = now - timedelta(days=scope["recent_days"])
    included = [mail for mail in mails if mail.received_at is None or cutoff <= mail.received_at <= now]
    return included[:min(scope["max_messages"], 200)], {
        "outside_date_range": len(mails) - len(included),
        "over_message_limit": max(0, len(included) - min(scope["max_messages"], 200)),
        "unknown_dates": sum(mail.received_at is None for mail in included[:min(scope["max_messages"], 200)]),
    }
