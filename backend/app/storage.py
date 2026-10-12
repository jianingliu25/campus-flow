"""Scoped data access and transactional email/document/outbox persistence."""

import hashlib
import json

from sqlalchemy import select

from app.models import Email, IndexOutbox, Source, SourcePolicy, VectorDocument, new_id
from app.security.policies import scoped_policy, scoped_source


def create_source(session, workspace_id, kind, display_name):
    source = Source(id=new_id(), workspace_id=workspace_id, kind=kind, display_name=display_name)
    session.add(source)
    session.flush()
    session.add(SourcePolicy(workspace_id=workspace_id, source_id=source.id))
    session.flush()
    return source


def owned_query(model, ctx):
    return select(model).where(model.workspace_id == ctx.workspace_id, model.source_id == ctx.source_id)


def list_emails(session, ctx, limit=50):
    scoped_source(session, ctx)
    return list(session.scalars(owned_query(Email, ctx).order_by(Email.received_at.desc(), Email.id).limit(limit)))


def upsert_email(session, ctx, *, external_id, subject, sender, body_text, received_at, summary=""):
    source, policy = scoped_source(session, ctx), scoped_policy(session, ctx)
    digest = hashlib.sha256(json.dumps([subject, sender, body_text, summary], ensure_ascii=False).encode()).hexdigest()
    retained_body = body_text if policy.retain_body else None
    mail = session.scalar(owned_query(Email, ctx).where(Email.external_id == external_id))
    if mail is None:
        mail = Email(id=new_id(), workspace_id=ctx.workspace_id, source_id=ctx.source_id, external_id=external_id,
                     subject=subject, sender=sender, body_text=retained_body, summary=summary,
                     content_hash=digest, received_at=received_at, revision=1)
        session.add(mail)
        session.flush()
    elif mail.content_hash != digest or mail.body_text != retained_body:
        mail.subject, mail.sender, mail.body_text, mail.summary = subject, sender, retained_body, summary
        mail.content_hash, mail.received_at = digest, received_at
        mail.revision += 1
    text = "\n".join(item for item in [subject, summary, retained_body] if item)
    document = session.scalar(owned_query(VectorDocument, ctx).where(VectorDocument.email_id == mail.id))
    doc_hash = hashlib.sha256(text.encode()).hexdigest()
    if document is None:
        document = VectorDocument(id=new_id(), workspace_id=ctx.workspace_id, source_id=ctx.source_id, kind="email",
                                  foreign_key=mail.id, email_id=mail.id, text=text, content_hash=doc_hash,
                                  generation=source.index_generation, version=1)
        session.add(document)
        session.flush()
    elif document.content_hash != doc_hash or document.generation != source.index_generation or document.deleted_at is not None:
        document.text, document.content_hash, document.generation = text, doc_hash, source.index_generation
        document.version += 1
        document.indexed_version, document.deleted_at = None, None
    existing = session.scalar(owned_query(IndexOutbox, ctx).where(IndexOutbox.document_id == document.id, IndexOutbox.document_version == document.version, IndexOutbox.generation == document.generation, IndexOutbox.operation == "upsert"))
    if existing is None:
        session.add(IndexOutbox(workspace_id=ctx.workspace_id, source_id=ctx.source_id, document_id=document.id,
                                document_version=document.version, generation=document.generation))
    session.flush()
    return mail, document
