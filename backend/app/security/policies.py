"""Deny by default. Runtime consent is tied to a provider fingerprint."""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select

from app.models import Source, SourcePolicy


class BoundaryError(Exception):
    def __init__(self, code: str, status: int = 403):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class SourceContext:
    workspace_id: str
    source_id: str


Purpose = Literal["ingest", "chat", "summary", "repair", "profile", "qa_memory", "reprocess", "embedding"]


def scoped_source(session, ctx: SourceContext):
    source = session.scalar(select(Source).where(Source.id == ctx.source_id, Source.workspace_id == ctx.workspace_id))
    if source is None:
        raise BoundaryError("SOURCE_NOT_FOUND", 404)
    if source.status in {"deleting", "deleted", "disconnected"}:
        raise BoundaryError("SOURCE_UNAVAILABLE", 409)
    return source


def scoped_policy(session, ctx):
    scoped_source(session, ctx)
    policy = session.scalar(select(SourcePolicy).where(SourcePolicy.source_id == ctx.source_id, SourcePolicy.workspace_id == ctx.workspace_id))
    if policy is None:
        raise BoundaryError("POLICY_MISSING", 409)
    return policy


def authorize_processing(session, ctx, *, purpose: Purpose, provider_mode: str, fingerprint: str, global_remote: bool):
    if purpose not in {"ingest", "chat", "summary", "repair", "profile", "qa_memory", "reprocess", "embedding"}:
        raise BoundaryError("UNKNOWN_PROCESSING_PURPOSE")
    source, policy = scoped_source(session, ctx), scoped_policy(session, ctx)
    if purpose == "profile" and not policy.enable_implicit_profile:
        raise BoundaryError("PROFILE_DISABLED")
    if purpose == "qa_memory" and not policy.enable_qa_memory:
        raise BoundaryError("QA_MEMORY_DISABLED")
    if provider_mode == "fixture" and source.kind != "fixture":
        raise BoundaryError("FIXTURE_PROVIDER_FOR_REAL_SOURCE")
    if provider_mode == "cloud":
        if purpose == "embedding":
            raise BoundaryError("REMOTE_EMBEDDING_DISABLED")
        if not global_remote or not policy.allow_remote_processing:
            raise BoundaryError("REMOTE_PROCESSING_DISABLED")
        if policy.consent_fingerprint != fingerprint:
            raise BoundaryError("PROVIDER_CONSENT_CHANGED")
    elif provider_mode not in {"fixture", "local"}:
        raise BoundaryError("UNKNOWN_PROVIDER_MODE")
    return policy.version
