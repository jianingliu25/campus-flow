"""Explicit local-file scope only, default browse; no cloud dispatch."""
import argparse
import json
from pathlib import Path

from app.config import get_settings
from app.db import Database
from app.ingest.pipeline import import_one, source_timezone
from app.ingest.previews import filter_scope
from app.models import utcnow
from app.security.policies import BoundaryError, SourceContext, scoped_policy
from app.sources.local_files import parse_upload, selected_files
from app.storage import create_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--file", type=Path)
    inputs.add_argument("--directory", type=Path)
    parser.add_argument("--source-id")
    parser.add_argument("--label", default="本地导入")
    parser.add_argument("--mode", choices=["browse", "rules"], default="browse")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    files = selected_files(args.file.parent if args.file else args.directory, [args.file] if args.file else None)
    if not files:
        parser.error("No supported EML/MBOX files in the selected scope")
    if args.dry_run:
        count = 0
        for file in files:
            mails, report = parse_upload(file.read_bytes(), file.name, settings.timezone)
            count += len(mails)
        print(json.dumps({"dry_run": True, "files": len(files), "valid_messages": count}))
        return
    db = Database(settings.data_dir)
    try:
        db.migrate()
        workspace = db.ensure_workspace(settings.timezone)
        with db.transaction() as session:
            id = args.source_id or create_source(session, workspace, "local_files", args.label).id
            ctx = SourceContext(workspace, id)
            policy = scoped_policy(session, ctx)
            version, scope, zone = policy.version, dict(policy.scope), source_timezone(session, ctx)
        totals = {"imported": 0, "updated": 0, "unchanged": 0, "events": 0, "errors": 0}
        mails = []
        for file in files:
            parsed, report = parse_upload(file.read_bytes(), file.name, zone)
            mails.extend(parsed)
            totals["errors"] += len(report["errors"])
        mails, filtered = filter_scope(mails, scope, utcnow())
        for mail in mails:
            result = import_one(db, ctx, mail, args.mode, version)
            totals[result["action"]] += 1
            totals["events"] += result["events"]
        print(json.dumps({"source_id": id, "mode": args.mode, **totals, **filtered}))
    except BoundaryError as error:
        parser.exit(1, f"Import stopped: {error.code}\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
