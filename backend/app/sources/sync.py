"""Manual bounded sync with durable cursors, cancellation and policy fences."""
import asyncio
import time

from sqlalchemy import select, update

from app.ingest.pipeline import import_one, source_timezone
from app.ingest.previews import filter_scope
from app.models import Source, SourcePolicy, SyncCursor, SyncRun, utcnow
from app.security.policies import BoundaryError, scoped_policy, scoped_source
from app.sources.imap import IMAPAdapter
from app.sources.mcp import MCPAdapter
from app.storage import owned_query


def adapter(kind, config, secret):
    return IMAPAdapter(config,secret) if kind=="imap" else MCPAdapter(config,secret)


class SyncManager:
    def __init__(self,database,credentials,factory=adapter):
        self.db,self.credentials,self.factory=database,credentials,factory
        self.tasks={}
        with database.transaction() as session:
            session.execute(update(SyncRun).where(SyncRun.status=="running").values(status="interrupted",error_code="SERVER_RESTARTED"))

    def start(self,ctx,local_session,mode="browse",resume=False):
        with self.db.transaction() as session:
            source,policy=scoped_source(session,ctx),scoped_policy(session,ctx)
            if source.kind not in {"imap","mcp"}:
                raise BoundaryError("NOT_CONNECTOR_SOURCE",422)
            if not source.safe_config.get("connector"):
                raise BoundaryError("CONNECTOR_NOT_CONFIGURED",409)
            if source.safe_config.get("paused") and not resume:
                raise BoundaryError("SYNC_PAUSED",409)
            if source.id in self.tasks and not self.tasks[source.id].done():
                raise BoundaryError("SYNC_ALREADY_RUNNING",409)
            config=dict(source.safe_config)
            self.credentials.get(ctx,local_session,source.credential_ref)
            if resume:
                source.safe_config={**config,"paused":False}
            run=SyncRun(source_id=ctx.source_id,workspace_id=ctx.workspace_id,status="running",
                        counts={"read":0,"saved":0,"unchanged":0,"events":0,"skipped":0,"errors":0})
            session.add(run);session.flush()
            run_id=run.id
            snapshot=(source.kind,config,source.credential_ref,dict(policy.scope),policy.version,source.index_generation,source_timezone(session,ctx))
        self.tasks[ctx.source_id]=asyncio.create_task(self.execute(ctx,local_session,run_id,snapshot,mode))
        return run_id

    def check(self,ctx,run_id,version,generation):
        with self.db.transaction() as session:
            run=session.scalar(owned_query(SyncRun,ctx).where(SyncRun.id==run_id))
            source,policy=scoped_source(session,ctx),scoped_policy(session,ctx)
            if not run or run.cancelled or source.safe_config.get("paused"):
                raise BoundaryError("SYNC_CANCELLED",409)
            if policy.version!=version or source.index_generation!=generation:
                raise BoundaryError("POLICY_VERSION_CHANGED",409)

    async def execute(self,ctx,local_session,run_id,snapshot,mode):
        kind,config,storage,scope,version,generation,zone=snapshot
        reader=None
        counts={"read":0,"saved":0,"unchanged":0,"events":0,"skipped":0,"errors":0}
        status,error="completed",None
        key=config.get("folder","mcp")
        try:
            secret=self.credentials.get(ctx,local_session,storage)
            reader=self.factory(kind,config,secret)
            with self.db.transaction() as session:
                saved=session.scalar(owned_query(SyncCursor,ctx).where(SyncCursor.folder==key))
                cursor=dict(saved.cursor) if saved and saved.cursor.get("policy_version")==version else {}
            maximum=min(scope["max_messages"],200)
            for _ in range(20):
                if counts["read"]>=maximum:
                    break
                if time.monotonic()>=local_session.expires_at:
                    self.credentials.clear_owner(local_session)
                    raise BoundaryError("SESSION_EXPIRED",401)
                self.check(ctx,run_id,version,generation)
                self.credentials.get(ctx,local_session,storage)
                mails,next_cursor,done,errors=await reader.fetch_page({**scope,"max_messages":maximum-counts["read"]},cursor,zone)
                self.check(ctx,run_id,version,generation)
                counts["errors"]+=len(errors)
                processed_page=0
                for parsed in mails:
                    if counts["read"]>=maximum:
                        break
                    self.check(ctx,run_id,version,generation)
                    counts["read"]+=1
                    processed_page+=1
                    included,_=filter_scope([parsed],scope,utcnow())
                    if not included or (parsed.received_at is None and not config.get("include_unknown_dates",False)):
                        counts["skipped"]+=1
                        continue
                    result=import_one(self.db,ctx,parsed,mode,version,allowed_kinds=(kind,))
                    counts["unchanged" if result["action"]=="unchanged" else "saved"]+=1
                    counts["events"]+=result["events"]
                # Only advance whole-page cursors. A partial page is replayed idempotently next time.
                if processed_page==len(mails):
                    cursor={**next_cursor,"policy_version":version}
                    with self.db.transaction() as session:
                        saved=session.scalar(owned_query(SyncCursor,ctx).where(SyncCursor.folder==key))
                        if saved is None:
                            saved=SyncCursor(workspace_id=ctx.workspace_id,source_id=ctx.source_id,folder=key,cursor=cursor)
                            session.add(saved)
                        else:
                            saved.cursor=cursor
                        run=session.get(SyncRun,run_id);run.counts=dict(counts)
                if done:
                    break
            else:
                status,error="partial","SYNC_PAGE_BUDGET"
        except BoundaryError as failure:
            status,error=("cancelled" if failure.code=="SYNC_CANCELLED" else "failed"),failure.code
        except asyncio.CancelledError:
            status,error="interrupted","SERVER_STOPPED"
        except Exception:
            status,error="failed","CONNECTOR_SYNC_FAILED"
        finally:
            if reader:
                try:
                    await reader.close()
                except Exception:
                    pass
            with self.db.transaction() as session:
                run=session.get(SyncRun,run_id)
                if run:
                    run.status,run.error_code,run.counts=status,error,dict(counts)

    async def shutdown(self):
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks.values(),return_exceptions=True)
