import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx2
import pytest
from sqlalchemy import select

from app.models import Email, Source, SyncRun, utcnow
from app.security.credentials import CredentialStore, WindowsVault
from app.security.policies import BoundaryError
from app.sources.imap import IMAPAdapter, PinnedIMAP
from app.sources.mcp import MCPAdapter
from app.sources.network import JSONTransport, endpoint
from tests.test_local_import import parsed, raw_mail


def test_credentials_session_ownership_and_no_plaintext_fallback(store):
    _,a,*_=store
    vault=CredentialStore()
    first,other=SimpleNamespace(csrf_token="one"),SimpleNamespace(csrf_token="other")
    assert vault.put(a,first,"fictional-test-secret")=="session"
    assert vault.get(a,first,"session")=="fictional-test-secret"
    with pytest.raises(BoundaryError): vault.get(a,other,"session")
    with pytest.raises(BoundaryError,match="SECURE_STORE_UNAVAILABLE"): vault.put(a,first,"fictional",True)
    vault.clear_owner(first)
    with pytest.raises(BoundaryError): vault.get(a,first,"session")


@pytest.mark.skipif(os.name!="nt",reason="Windows-only native credential vault")
def test_native_windows_vault_roundtrip():
    vault=WindowsVault();key="CampusFlow-test/"+str(uuid4())
    try:
        try: vault.put(key,"fictional-only-credential")
        except BoundaryError: pytest.skip("Runner has no interactive credential set")
        assert vault.get(key)=="fictional-only-credential"
    finally: vault.delete(key)
    with pytest.raises(BoundaryError): vault.get(key)


class FakeIMAP:
    def __init__(self): self.calls=[];self.epoch=b"10"
    def login(self,user,secret): self.calls.append(("login",user));return "OK",[]
    def select(self,mailbox,readonly): self.calls.append(("select",mailbox,readonly));return "OK",[b"2"]
    def response(self,name): return name,[self.epoch]
    def uid(self,command,*args):
        self.calls.append((command,*args))
        if command=="SEARCH": return "OK",[b"1 2"]
        if "SIZE" in args[-1]: return "OK",[b"1 (RFC822.SIZE 500)"]
        return "OK",[(b"1 (UID 1 BODY[] {500})",raw_mail().as_bytes()),b")"]
    def logout(self): self.calls.append(("logout",))


def test_imap_readonly_peek_uid_epoch_and_limits():
    client=FakeIMAP();reader=IMAPAdapter({"host":"imap.example.org","port":993,"username":"fictional@example.org","folder":"INBOX"},"fictional",lambda:client)
    mails,cursor,done,errors=asyncio.run(reader.fetch_page({"recent_days":30,"max_messages":1,"folders":[]},{"uidvalidity":"9","uid":200},"Asia/Shanghai"))
    assert len(mails)==1 and mails[0].external_id.startswith("imap:") and cursor=={"uidvalidity":"10","uid":1}
    assert not done and not errors
    assert ("select",'"INBOX"',True) in client.calls
    assert any(call[0]=="SEARCH" and "1:*" in call for call in client.calls)
    assert any(call[0]=="FETCH" and "BODY.PEEK" in call[-1] for call in client.calls)
    assert not any(call[0] in {"STORE","COPY","MOVE","EXPUNGE","APPEND","CLOSE"} for call in client.calls)
    asyncio.run(reader.close())
    with pytest.raises(BoundaryError): reader.select("INBOX\r\nSTORE")
    with pytest.raises(BoundaryError,match="MESSAGE_TOO_LARGE"): PinnedIMAP.read(object.__new__(PinnedIMAP),1024*1024+1)


@pytest.mark.parametrize("url",["http://remote.example.org/mcp","https://user:secret@example.org/mcp","https://example.org/mcp?token=x","file:///private"])
def test_connector_endpoint_rejects_unsafe_urls(url):
    with pytest.raises(BoundaryError): endpoint(url)


def test_mcp_protocol_sse_whitelist_and_schema():
    calls=[]
    def handler(request):
        assert request.url.host=="127.0.0.1"
        if request.method=="DELETE": return httpx2.Response(202)
        body=json.loads(request.content);calls.append(body)
        method=body["method"]
        if method=="notifications/initialized": return httpx2.Response(202)
        if method=="initialize": result={"protocolVersion":"2025-11-25","capabilities":{"tools":{}},"serverInfo":{"name":"fictional-test"}}
        elif method=="tools/list": result={"tools":[{"name":name,"inputSchema":{"type":"object"}} for name in ["list_emails","read_email","send_email"]]}
        elif body["params"]["name"]=="list_emails": result={"structuredContent":{"account_id":"fictional","messages":[{"id":"one"}],"next_cursor":None}}
        else: result={"content":[{"type":"text","text":json.dumps({"account_id":"fictional","id":"one","subject":"虚构课程","sender":"teacher@example.org","body_text":"课程时间未知"})}]}
        answer={"jsonrpc":"2.0","id":body["id"],"result":result}
        if method=="tools/call":
            return httpx2.Response(200,headers={"content-type":"text/event-stream"},text="data: "+json.dumps(answer)+"\n\n")
        return httpx2.Response(200,headers={"Mcp-Session-Id":"fictional-session"},json=answer)
    transport=JSONTransport("http://localhost:9999/mcp","fictional-token",httpx2.MockTransport(handler))
    reader=MCPAdapter({"endpoint":"http://localhost:9999/mcp","account_id":"fictional","list_tool":"list_emails","read_tool":"read_email"},"",transport)
    async def execute():
        mails,cursor,done,errors=await reader.fetch_page({"recent_days":30,"max_messages":20},{},"UTC")
        assert len(mails)==1 and mails[0].received_at is None and done and not errors
        with pytest.raises(BoundaryError,match="MCP_TOOL_NOT_ALLOWED"): await reader.call("send_email",{})
        await reader.close()
    asyncio.run(execute())
    assert {call.get("params",{}).get("name") for call in calls if call["method"]=="tools/call"}=={"list_emails","read_email"}


def test_mcp_private_dns_and_redirect_are_denied():
    async def private_resolver(host,port):return ["10.0.0.1"]
    async def execute():
        with pytest.raises(BoundaryError,match="CONNECTOR_ADDRESS_REJECTED"):
            await JSONTransport("https://provider.example.org/mcp",resolver=private_resolver).send({"id":1})
        with pytest.raises(BoundaryError,match="CONNECTOR_REDIRECT_REJECTED"):
            await JSONTransport("http://127.0.0.1/mcp",transport=httpx2.MockTransport(lambda request:httpx2.Response(302,headers={"Location":"https://evil.example.org"}))).send({"id":1})
    asyncio.run(execute())


def test_mcp_reference_service_end_to_end_over_http():
    from app.sources.demo_server import app,TOKEN,ACCOUNT
    reader=MCPAdapter({"endpoint":"http://127.0.0.1:8990/mcp","account_id":ACCOUNT,"list_tool":"list_emails","read_tool":"read_email"},TOKEN,
                      JSONTransport("http://127.0.0.1:8990/mcp",TOKEN,httpx2.ASGITransport(app=app)))
    async def execute():
        info=await reader.initialize()
        assert info["server_name"]=="CampusFlow fictional mail"
        mails,_,done,errors=await reader.fetch_page({"recent_days":30,"max_messages":20},{},"Asia/Shanghai")
        assert len(mails)==3 and done and not errors and mails[-1].date_status=="unknown"
        await reader.close()
    asyncio.run(execute())


def test_connector_config_credentials_redaction_sync_and_disconnect(browser_client,store):
    client=browser_client
    _,_,b,outside=store
    source=client.post("/api/sources",json={"kind":"imap","display_name":"fictional IMAP"}).json()["id"]
    body={"expected_version":1,"host":"imap.example.org","username":"fictional@example.org","secret":"fictional-secret-never-echo"}
    response=client.put(f"/api/sources/{source}/connector",json=body)
    assert response.status_code==200 and "fictional-secret-never-echo" not in response.text
    assert "fictional-secret-never-echo" not in client.get(f"/api/sources/{source}/connector").text
    assert client.put(f"/api/sources/{outside.source_id}/connector",json=body).status_code==404
    assert client.put(f"/api/sources/{source}/connector",json={**body,"expected_version":2,"username":"another@example.org"}).status_code==409
    class Reader:
        async def test(self):return {"read_only":True,"account_verified":True}
        async def fetch_page(self,scope,cursor,zone):return [replace(parsed(),received_at=utcnow())],{"uid":1},True,[]
        async def close(self):pass
    client.app.state.sync.factory=lambda *args:Reader()
    assert client.post(f"/api/sources/{source}/test").status_code==200
    client.post(f"/api/sources/{source}/activate");client.headers["X-CampusFlow-Source"]=source
    response=client.post(f"/api/sources/{source}/sync",json={"mode":"browse"})
    assert response.status_code==202
    job=response.json()["job_id"]
    for _ in range(50):
        result=client.get(f"/api/sync/{job}").json()
        if result["status"]!="running":break
        time.sleep(.01)
    assert result["status"]=="completed" and result["counts"]["saved"]==1
    assert client.get("/api/dashboard").json()["mail_total"]==1
    client.post(f"/api/sources/{b.source_id}/activate");client.headers["X-CampusFlow-Source"]=b.source_id
    assert client.get(f"/api/sync/{job}").status_code==404
    assert client.post(f"/api/sources/{source}/disconnect").json()["local_data_retained"]
    assert client.post(f"/api/sources/{source}/test").status_code==409
    with store[0].transaction() as session:
        assert session.scalar(select(Email).where(Email.source_id==source)) is not None
        assert "fictional-secret-never-echo" not in json.dumps(session.get(Source,source).safe_config)
