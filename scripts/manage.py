"""Cross-platform development entry point. Run from any working directory."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(command, cwd=ROOT, env=None):
    subprocess.run([str(value) for value in command], cwd=cwd, env=env, check=True)


def npm():
    executable = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not executable:
        raise RuntimeError("Install Node.js >=22.12 and npm first.")
    return executable


def require_environment():
    if not PYTHON.exists():
        raise RuntimeError("Run: python scripts/manage.py setup")


def setup():
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11+ is required.")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Install Node.js >=22.12 first.")
    version = subprocess.check_output([node, "--version"], text=True).strip().lstrip("v")
    major, minor, *_ = map(int, version.split("."))
    if (major, minor) < (22, 12):
        raise RuntimeError("Node.js >=22.12 is required.")
    if not PYTHON.exists():
        run([sys.executable, "-m", "venv", ROOT / ".venv"])
    run([PYTHON, "-m", "pip", "install", "-r", ROOT / "backend/requirements.txt"])
    run([npm(), "ci"], cwd=ROOT / "frontend")
    print("Setup complete. No mailbox, model download, or API key is required.")


def build():
    run([npm(), "run", "build"], cwd=ROOT / "frontend")


def validate():
    # Import using the project environment, keeping validation independent of the caller.
    code = """
import json
from pathlib import Path
from app.demo import load_fixtures
from app.schemas import FixtureBundle, QAFixture
bundle = load_fixtures()
root = Path.cwd().parent
qas = json.loads((root / 'eval/development/qa_set.json').read_text(encoding='utf-8'))
for value in qas:
    QAFixture.model_validate(value)
schemas = root / 'fixtures/schemas'
schemas.mkdir(exist_ok=True)
for filename, model in [('bundle.schema.json', FixtureBundle), ('qa.schema.json', QAFixture)]:
    (schemas / filename).write_text(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + '\\n', encoding='utf-8')
print(f'Validated {len(bundle.emails)} fictional emails, {len(bundle.events)} events, {len(qas)} development questions.')
"""
    run([PYTHON, "-c", code], cwd=ROOT / "backend")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["setup", "build", "validate", "test", "demo", "migrate", "db-status", "import", "mcp-demo", "evaluate"])
    parser.add_argument("--file")
    parser.add_argument("--directory")
    parser.add_argument("--source-id")
    parser.add_argument("--label", default="本地导入")
    parser.add_argument("--mode", choices=["browse", "rules"], default="browse")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--port", type=int, default=8000, help="Demo server port (loopback only)")
    parser.add_argument("--no-build", action="store_true", help="Serve an existing frontend build")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    try:
        if args.command == "setup":
            setup()
        elif args.command == "build":
            build()
        else:
            require_environment()
            if args.command == "validate":
                validate()
            elif args.command == "import":
                if not args.file and not args.directory:
                    parser.error("import requires --file or --directory")
                command = [PYTHON, "-m", "app.ingest.cli", "--mode", args.mode, "--label", args.label]
                if args.file:
                    command += ["--file", Path(args.file).absolute()]
                if args.directory:
                    command += ["--directory", Path(args.directory).absolute()]
                if args.source_id:
                    command += ["--source-id", args.source_id]
                if args.dry_run:
                    command += ["--dry-run"]
                run(command, cwd=ROOT / "backend")
            elif args.command == "evaluate":
                run([PYTHON, ROOT / "scripts/evaluate.py"])
            elif args.command == "test":
                run([PYTHON, "-m", "pytest"], cwd=ROOT / "backend")
                build()
            elif args.command in {"migrate", "db-status"}:
                code = """
from app.config import get_settings
from app.db import Database
from sqlalchemy import inspect, text
settings = get_settings()
db = Database(settings.data_dir)
try:
    db.migrate()
    db.ensure_workspace(settings.timezone)
    with db.engine.connect() as connection:
        print('Schema revision:', connection.scalar(text('SELECT version_num FROM alembic_version')))
        print('Application tables:', len(inspect(connection).get_table_names()) - 1)
        print('Foreign keys:', bool(connection.scalar(text('PRAGMA foreign_keys'))))
        print('Connectors: explicit configuration and manual sync; indexing: manual')
finally:
    db.close()
"""
                run([PYTHON, "-c", code], cwd=ROOT / "backend")
            elif args.command == "mcp-demo":
                port = 8990 if args.port == 8000 else args.port
                print(f"Fictional MCP service: http://127.0.0.1:{port}/mcp", flush=True)
                run([PYTHON, "-m", "uvicorn", "app.sources.demo_server:app", "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT / "backend")
            elif args.command == "demo":
                if not args.no_build:
                    build()
                if not (ROOT / "frontend/dist/index.html").is_file():
                    raise RuntimeError("Frontend build missing. Run without --no-build.")
                print(f"Local app (fictional preview or selected mail): http://127.0.0.1:{args.port}", flush=True)
                run([PYTHON, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", args.port], cwd=ROOT / "backend")
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Campus Flow: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Demo stopped.")


if __name__ == "__main__":
    main()
