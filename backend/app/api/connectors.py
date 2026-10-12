"""Explicit source configuration; credentials are never serialized or stored in SQL."""
import re
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field, SecretStr
from sqlalchemy import select, update

from app.api.foundation import StrictBody, db
from app.models import Source, SourcePolicy, SyncRun, utcnow
from app.security.http import local_session, source_context
from app.security.policies import BoundaryError, SourceContext, scoped_policy, scoped_source
from app.sources.mcp import LIST_TOOLS, READ_TOOLS
from app.sources.network import endpoint
from app.storage import owned_query

router=APIRouter(prefix="/api")


class ConnectorConfig(StrictBody):
    expected_version:int=Field(ge=1)
    host:str|None=Field(default=None,max_length=253)
    port:int=Field(default=993,ge=1,le=65535)
    username:str|None=Field(default=None,max_length=200)
    folder:str=Field(default="INBOX",max_length=120)
    endpoint:str|None=Field(default=None,max_length=500)
    account_id:str|None=Field(default=None,max_length=150)
    list_tool:str=Field(default="list_emails",max_length=100)
    read_tool:str=Field(default="read_email",max_length=100)
    secret:SecretStr
    persistent:bool=False
    include_unknown_dates:bool=False
    token_for_this_server:bool=False


class SyncRequest(StrictBody):
    mode:Literal["browse","rules"]="browse"
    resume:bool=False


@router.get("/credential-status")
def credential_status(request:Request,session=Depends(local_session)):
    return {"persistent_available":request.app.state.credentials.vault is not None,"default":"session"}


@router.get("/sources/{source_id}/connector")
def connector_info(source_id:str,request:Request,session=Depends(local_session)):
    ctx=SourceContext(session.workspace_id,source_id)
    with db(request).transaction() as transaction:
        source=scoped_source(transaction,ctx)
        allowed={"connector","host","port","username","folder","endpoint","account_id","list_tool","read_tool","include_unknown_dates","connection_tested","paused"}
        return {"kind":source.kind,"config":{key:value for key,value in source.safe_config.items() if key in allowed},
                "credential_storage":source.credential_ref or "none","account_connected":bool(source.safe_config.get("connection_tested"))}


@router.put("/sources/{source_id}/connector")
def configure(source_id:str,body:ConnectorConfig,request:Request,session=Depends(local_session)):
    ctx=SourceContext(session.workspace_id,source_id)
    with db(request).transaction() as transaction:
        source,policy=scoped_source(transaction,ctx),scoped_policy(transaction,ctx)
        if policy.version!=body.expected_version:
            raise BoundaryError("POLICY_VERSION_CHANGED",409)
        if source.kind=="imap":
            if not body.host or not re.fullmatch(r"[A-Za-z0-9.\-]{1,253}",body.host) or not body.username or any(c in body.username for c in "\r\n\0"):
                raise BoundaryError("INVALID_IMAP_CONFIG",422)
            if not re.fullmatch(r"[A-Za-z0-9 /_.&+\-]{1,120}",body.folder):
                raise BoundaryError("UNSUPPORTED_IMAP_FOLDER",422)
            config={"connector":True,"host":body.host.lower(),"port":body.port,"username":body.username,"folder":body.folder}
            identity=("host","port","username")
        elif source.kind=="mcp":
            if not body.endpoint or not body.account_id or body.list_tool not in LIST_TOOLS or body.read_tool not in READ_TOOLS:
                raise BoundaryError("INVALID_MCP_CONFIG",422)
            endpoint(body.endpoint)
            if not body.token_for_this_server:
                raise BoundaryError("MCP_SERVER_TOKEN_CONFIRMATION_REQUIRED",422)
            config={"connector":True,"endpoint":body.endpoint,"account_id":body.account_id,"list_tool":body.list_tool,"read_tool":body.read_tool}
            identity=("endpoint","account_id")
        else:
            raise BoundaryError("NOT_CONNECTOR_SOURCE",422)
        if source.safe_config.get("connector") and any(source.safe_config.get(key)!=config[key] for key in identity):
            raise BoundaryError("ACCOUNT_CHANGE_REQUIRES_NEW_SOURCE",409)
        if source.id in request.app.state.sync.tasks and not request.app.state.sync.tasks[source.id].done():
            raise BoundaryError("SYNC_ALREADY_RUNNING",409)
        storage=request.app.state.credentials.put(ctx,session,body.secret.get_secret_value(),body.persistent)
        source.credential_ref=storage
        source.safe_config={**config,"timezone":source.safe_config.get("timezone"),"include_unknown_dates":body.include_unknown_dates,
                            "connection_tested":False,"paused":False}
        policy.version+=1;source.policy_version=policy.version
        policy.allow_remote_processing=False;policy.consent_fingerprint=None
        return {"configured":True,"credential_storage":storage,"policy_version":policy.version,"connection_tested":False}


@router.post("/sources/{source_id}/test")
async def test_connection(source_id:str,request:Request,session=Depends(local_session)):
    ctx=SourceContext(session.workspace_id,source_id)
    with db(request).transaction() as transaction:
        source=scoped_source(transaction,ctx)
        if source.kind not in {"imap","mcp"} or not source.safe_config.get("connector"):
            raise BoundaryError("CONNECTOR_NOT_CONFIGURED",409)
        kind,config,version=source.kind,dict(source.safe_config),source.policy_version
        secret=request.app.state.credentials.get(ctx,session,source.credential_ref)
    reader=request.app.state.sync.factory(kind,config,secret)
    result=await reader.test()
    with db(request).transaction() as transaction:
        source=scoped_source(transaction,ctx)
        if source.policy_version!=version:
            raise BoundaryError("POLICY_VERSION_CHANGED",409)
        source.safe_config={**source.safe_config,"connection_tested":True}
    return result


@router.post("/sources/{source_id}/sync",status_code=202)
async def start_sync(source_id:str,body:SyncRequest,request:Request,ctx=Depends(source_context),session=Depends(local_session)):
    if ctx.source_id!=source_id:
        raise BoundaryError("SOURCE_SELECTION_CHANGED",409)
    return {"job_id":request.app.state.sync.start(ctx,session,body.mode,body.resume)}


@router.get("/sync/{job_id}")
def sync_status(job_id:str,request:Request,ctx=Depends(source_context)):
    with db(request).transaction() as transaction:
        run=transaction.scalar(owned_query(SyncRun,ctx).where(SyncRun.id==job_id))
        if run is None:
            raise BoundaryError("SYNC_NOT_FOUND",404)
        return {"id":run.id,"status":run.status,"counts":run.counts,"error_code":run.error_code,"cancelled":run.cancelled}


@router.get("/sources/{source_id}/sync-status")
def latest_sync(source_id:str,request:Request,ctx=Depends(source_context)):
    if ctx.source_id!=source_id:
        raise BoundaryError("SOURCE_SELECTION_CHANGED",409)
    with db(request).transaction() as transaction:
        run=transaction.scalar(owned_query(SyncRun,ctx).order_by(SyncRun.started_at.desc()).limit(1))
        return None if run is None else {"id":run.id,"status":run.status,"counts":run.counts,"error_code":run.error_code,"cancelled":run.cancelled}


@router.post("/sources/{source_id}/pause")
def pause(source_id:str,request:Request,session=Depends(local_session)):
    ctx=SourceContext(session.workspace_id,source_id)
    with db(request).transaction() as transaction:
        source=scoped_source(transaction,ctx)
        source.safe_config={**source.safe_config,"paused":True}
        transaction.execute(update(SyncRun).where(SyncRun.source_id==source_id,SyncRun.workspace_id==ctx.workspace_id,SyncRun.status=="running").values(cancelled=True))
    return {"paused":True}


@router.post("/sources/{source_id}/disconnect")
def disconnect(source_id:str,request:Request,session=Depends(local_session)):
    pause(source_id,request,session)
    ctx=SourceContext(session.workspace_id,source_id)
    request.app.state.credentials.delete(ctx)
    with db(request).transaction() as transaction:
        source=scoped_source(transaction,ctx)
        source.credential_ref=None
        source.safe_config={**source.safe_config,"connection_tested":False}
        source.policy_version+=1
        policy=scoped_policy(transaction,ctx)
        policy.version=source.policy_version;policy.allow_remote_processing=False;policy.consent_fingerprint=None
    return {"disconnected":True,"local_data_retained":True,"remote_token_revoked":False}
