"""Explicit local export and deletion with a database barrier against late writes."""
import asyncio
import json
from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select, func
from app.api.foundation import StrictBody, db
from app.models import Base, CampusEvent, Email, Source, SyncRun
from app.security.http import source_context, local_session
from app.security.policies import BoundaryError, scoped_source
from app.storage import owned_query
from app.memory.index_worker import IndexWorker

router = APIRouter(prefix="/api")


@router.post("/index/run")
def index_run(request: Request, ctx=Depends(source_context)):
    worker = IndexWorker(db(request), request.app.state.vectors, ctx=ctx)
    completed = 0
    for _ in range(200):
        if not worker.process_one():
            break
        completed += 1
    return {"completed": completed, "mode": request.app.state.vectors.mode, "maximum_jobs": 200}


class Search(StrictBody):
    query: str = Field(min_length=1, max_length=2000)


@router.post("/search")
def search(body: Search, request: Request, ctx=Depends(source_context)):
    return {"items": request.app.state.vectors.search(ctx, body.query), "mode": request.app.state.vectors.mode}


@router.post("/index/rebuild")
def rebuild(request: Request, ctx=Depends(source_context)):
    request.app.state.vectors.rebuild(ctx)
    return {"queued": True}


def counts(session, ctx):
    result = {}
    for table in Base.metadata.sorted_tables:
        if "source_id" in table.c and "workspace_id" in table.c:
            result[table.name] = session.scalar(select(func.count()).select_from(table).where(
                table.c.source_id == ctx.source_id, table.c.workspace_id == ctx.workspace_id))
    return result


@router.get("/data/impact")
def impact(request: Request, ctx=Depends(source_context)):
    with db(request).transaction() as session:
        scoped_source(session, ctx)
        return {"counts": counts(session, ctx), "modified_events": list(session.scalars(
            owned_query(CampusEvent, ctx).where(CampusEvent.user_modified).with_only_columns(CampusEvent.title).limit(100))),
            "includes_manual_edits": True, "remote_mail_deleted": False}


@router.post("/data/export")
def export(request: Request, ctx=Depends(source_context)):
    with db(request).transaction() as session:
        session.connection().exec_driver_sql("BEGIN")
        source = scoped_source(session, ctx)
        sizes = counts(session, ctx)
        if sum(sizes.values()) > 10000:
            raise BoundaryError("EXPORT_TOO_LARGE", 413)
        output = {}
        byte_count = 0
        # Account configuration, credentials, vector text copies and operational metadata are excluded.
        for table_name in ["emails", "events", "calendar_selections", "profiles", "qa_logs"]:
            table = Base.metadata.tables[table_name]
            output[table_name] = []
            for row in session.execute(select(table).where(
                    table.c.source_id == ctx.source_id, table.c.workspace_id == ctx.workspace_id)).mappings():
                item = dict(row)
                byte_count += len(json.dumps(item, ensure_ascii=False, default=str).encode('utf-8'))
                if byte_count > 20 * 1024 * 1024:
                    raise BoundaryError("EXPORT_TOO_LARGE", 413)
                output[table_name].append(item)
        return {"format": "campusflow-local-export-v1", "source": source.display_name, "private_data": True, "data": output}


class DeleteSource(StrictBody):
    confirm_source_id: str = Field(min_length=36, max_length=36)


@router.post("/data/delete")
async def delete_source(body: DeleteSource, request: Request, ctx=Depends(source_context), owner=Depends(local_session)):
    if body.confirm_source_id != ctx.source_id:
        raise BoundaryError("DELETE_CONFIRMATION_MISMATCH", 422)
    database = db(request)
    # Barrier is committed first. All ingestion/index writes must re-check source availability.
    with database.transaction() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        source = session.scalar(select(Source).where(Source.id == ctx.source_id, Source.workspace_id == ctx.workspace_id))
        if source is None:
            raise BoundaryError("SOURCE_NOT_FOUND", 404)
        source.status = "deleting"
        source.index_generation += 1
        for run in session.scalars(owned_query(SyncRun, ctx)):
            run.cancelled = True
    request.app.state.credentials.delete(ctx)
    task = request.app.state.sync.tasks.get(ctx.source_id)
    if task and not task.done():
        # Do not cancel to_thread IMAP work: let its per-command guard stop it.
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=45)
        except asyncio.TimeoutError:
            raise BoundaryError("DELETE_WAITING_FOR_SYNC", 409) from None
    with request.app.state.vectors.lock:
        request.app.state.vectors.drop(ctx)
        with database.transaction() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            source = session.scalar(select(Source).where(Source.id == ctx.source_id, Source.workspace_id == ctx.workspace_id))
            if source:
                session.delete(source)
                session.flush()
            remaining = counts(session, ctx)
            if any(remaining.values()):
                raise BoundaryError("DELETE_INCOMPLETE", 503)
    request.app.state.previews.clear_owner(owner)
    owner.active_source_id = None
    maintenance = "completed"
    try:
        with database.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            checkpoint = connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)").first()
            if checkpoint and checkpoint[0]:
                maintenance = "pending"
            else:
                connection.exec_driver_sql("VACUUM")
    except Exception:
        maintenance = "pending"
    return {"deleted": True, "remaining_owned_rows": sum(remaining.values()), "storage_compaction": maintenance,
            "remote_mail_deleted": False, "forensic_erasure_guaranteed": False}
