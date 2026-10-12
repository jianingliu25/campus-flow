from typing import Literal
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import Field

from app.api.foundation import StrictBody, db
from app.config import ROOT
from app.ingest.pipeline import import_one, reprocess, source_timezone
from app.ingest.previews import filter_scope
from app.models import utcnow
from app.security.http import local_session, source_context
from app.security.policies import BoundaryError, scoped_policy, scoped_source
from app.sources.local_files import parse_upload

router = APIRouter(prefix="/api")


class CommitImport(StrictBody):
    selected: list[int] = Field(max_length=200, min_length=1)
    mode: Literal["browse", "rules"] = "browse"


class ReprocessMail(StrictBody):
    mode: Literal["rules", "model"]


@router.post("/imports/preview")
async def preview(request: Request, ctx=Depends(source_context), session=Depends(local_session)):
    with db(request).transaction() as transaction:
        source = scoped_source(transaction, ctx)
        if source.kind != "local_files":
            raise BoundaryError("NOT_LOCAL_FILE_SOURCE")
        policy = scoped_policy(transaction, ctx)
        version, scope, zone = policy.version, dict(policy.scope), source_timezone(transaction, ctx)
    filename = unquote(request.headers.get("x-mail-filename", ""))
    mails, report = parse_upload(await request.body(), filename, zone)
    mails, filtered = filter_scope(mails, scope, utcnow())
    report.update(filtered)
    if not mails:
        return {"preview_id": None, "mails": [], "report": report}
    id = request.app.state.previews.add(session, ctx, version, mails, report)
    return {"preview_id": id, "expires_seconds": 600, "report": report,
            "mails": [{"id": index, "subject": mail.subject, "sender": mail.sender, "received_at": mail.received_at,
                       "date_status": mail.date_status, "warnings": mail.warnings} for index, mail in enumerate(mails)]}


@router.delete("/imports/{preview_id}", status_code=204)
def discard(preview_id: str, request: Request, ctx=Depends(source_context), session=Depends(local_session)):
    request.app.state.previews.discard(preview_id, session, ctx)


@router.post("/imports/{preview_id}/commit")
def commit(preview_id: str, body: CommitImport, request: Request, ctx=Depends(source_context), session=Depends(local_session)):
    item = request.app.state.previews.take(preview_id, session, ctx)
    if len(set(body.selected)) != len(body.selected) or any(index < 0 or index >= len(item.mails) for index in body.selected):
        raise BoundaryError("INVALID_SELECTION", 422)
    report = {"imported": 0, "updated": 0, "unchanged": 0, "events": 0, "errors": [], "processed": 0}
    for index in body.selected:
        try:
            result = import_one(db(request), ctx, item.mails[index], body.mode, item.policy_version)
            report[result["action"]] += 1
            report["events"] += result["events"]
            report["processed"] += 1
            report["errors"].extend({"position": index, "code": warning} for warning in result["warnings"])
        except BoundaryError as error:
            report["errors"].append({"position": index, "code": error.code})
            if error.code in {"POLICY_VERSION_CHANGED", "SOURCE_UNAVAILABLE", "SOURCE_NOT_FOUND"}:
                break
    return report


@router.post("/emails/{mail_id}/reprocess")
async def extract(mail_id: str, body: ReprocessMail, request: Request, ctx=Depends(source_context)):
    return await reprocess(db(request), ctx, mail_id, body.mode, request.app.state.provider_config)


@router.get("/import-examples/{filename}")
def example(filename: str, session=Depends(local_session)):
    if filename not in {"sample.eml", "sample.mbox"}:
        raise BoundaryError("EXAMPLE_NOT_FOUND", 404)
    return FileResponse(ROOT / "fixtures/mail" / filename, media_type="application/octet-stream", filename=filename)
