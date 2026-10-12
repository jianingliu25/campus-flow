import asyncio
from dataclasses import replace
import time

from app.models import utcnow
from tests.test_local_import import parsed


def setup(client):
    source=client.post("/api/sources",json={"kind":"imap","display_name":"fictional cancel test"}).json()["id"]
    assert client.put(f"/api/sources/{source}/connector",json={"expected_version":1,"host":"imap.example.org","username":"fictional@example.org","secret":"fictional-session-secret"}).status_code==200
    client.post(f"/api/sources/{source}/activate");client.headers["X-CampusFlow-Source"]=source
    return source


def poll(client,id):
    for _ in range(100):
        value=client.get(f"/api/sync/{id}").json()
        if value["status"]!="running":return value
        time.sleep(.01)
    raise AssertionError("Sync did not finish")


def test_pause_discards_inflight_result_before_persisting(browser_client):
    client=browser_client;source=setup(client)
    class Reader:
        async def fetch_page(self,*args):
            await asyncio.sleep(.08)
            return [replace(parsed(),received_at=utcnow())],{"uid":1},True,[]
        async def close(self):pass
    client.app.state.sync.factory=lambda *args:Reader()
    id=client.post(f"/api/sources/{source}/sync",json={}).json()["job_id"]
    assert client.post(f"/api/sources/{source}/pause").status_code==200
    result=poll(client,id)
    assert result["status"]=="cancelled" and result["counts"]["saved"]==0
    assert client.get("/api/dashboard").json()["mail_total"]==0
    assert client.post(f"/api/sources/{source}/sync",json={}).status_code==409


def test_scope_change_fences_inflight_sync(browser_client):
    client=browser_client;source=setup(client)
    class Reader:
        async def fetch_page(self,*args):
            await asyncio.sleep(.08)
            return [replace(parsed(),received_at=utcnow())],{"uid":1},True,[]
        async def close(self):pass
    client.app.state.sync.factory=lambda *args:Reader()
    id=client.post(f"/api/sources/{source}/sync",json={}).json()["job_id"]
    client.patch(f"/api/sources/{source}/policy",json={"expected_version":2,"retain_body":False})
    result=poll(client,id)
    assert result["status"]=="failed" and result["error_code"]=="POLICY_VERSION_CHANGED"
    assert client.get("/api/dashboard").json()["mail_total"]==0
