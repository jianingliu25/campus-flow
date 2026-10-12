from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.llm.compatible import ProviderConfig
from app.main import create_app
from app.models import Workspace
from app.security.policies import SourceContext
from app.storage import create_source


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "private")
    db.migrate()
    workspace = db.ensure_workspace("Asia/Shanghai")
    with db.transaction() as session:
        a = create_source(session, workspace, "local_files", "虚构来源 A")
        b = create_source(session, workspace, "local_files", "虚构来源 B")
        other = Workspace(name="另一个测试工作区", timezone="UTC")
        session.add(other)
        session.flush()
        foreign = create_source(session, other.id, "fixture", "工作区外来源")
    yield db, SourceContext(workspace, a.id), SourceContext(workspace, b.id), SourceContext(other.id, foreign.id)
    db.close()


@pytest.fixture
def browser_client(store, tmp_path):
    db, *_ = store
    app = create_app(Settings("Asia/Shanghai", tmp_path / "unused", date(2026, 10, 12)), database=db, provider_config=ProviderConfig())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.headers.update({"Origin": "http://127.0.0.1", "Sec-Fetch-Site": "same-origin"})
        response = client.post("/api/session")
        assert response.status_code == 200
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        yield client
