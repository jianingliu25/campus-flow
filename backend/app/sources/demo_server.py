"""Operator-started, loopback-only MCP fixture service. No real accounts or private files."""
from email.utils import format_datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.config import ROOT
from app.sources.local_files import parse_upload

app=FastAPI(title="Fictional Campus Flow MCP service")
app.add_middleware(TrustedHostMiddleware,allowed_hosts=["127.0.0.1","localhost"])
TOKEN="fictional-mcp-demo-token"  # Public dummy token protects no real data.
ACCOUNT="fictional-demo"


@app.post("/mcp")
async def mcp(request:Request):
    if request.headers.get("authorization")!="Bearer "+TOKEN:
        return JSONResponse({"code":"AUTH_REQUIRED"},401)
    if request.headers.get("origin") not in {None,str(request.base_url).rstrip("/")}:
        return JSONResponse({"code":"ORIGIN_REJECTED"},403)
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>262144:
            return JSONResponse({"code":"BODY_TOO_LARGE"},413)
    import json
    try:
        body=json.loads(raw)
        if body.get("jsonrpc")!="2.0":raise ValueError()
        method,params,id=body["method"],body.get("params",{}),body.get("id")
    except (ValueError,KeyError,TypeError,AttributeError):
        return JSONResponse({"code":"INVALID_RPC"},400)
    def response(result):return {"jsonrpc":"2.0","id":id,"result":result}
    if method=="initialize":
        return response({"protocolVersion":"2025-11-25","capabilities":{"tools":{}},"serverInfo":{"name":"CampusFlow fictional mail","version":"1.0"}})
    if method=="notifications/initialized":
        return Response(status_code=202)
    if method=="tools/list":
        common={"account_id":{"type":"string"}}
        return response({"tools":[
            {"name":"list_emails","inputSchema":{"type":"object","properties":{**common,"limit":{"type":"integer"},"recent_days":{"type":"integer"},"cursor":{"type":"string"}},"required":["account_id","limit","recent_days"],"additionalProperties":False}},
            {"name":"read_email","inputSchema":{"type":"object","properties":{**common,"id":{"type":"string"}},"required":["account_id","id"],"additionalProperties":False}}
        ]})
    try:
        if method!="tools/call" or params["arguments"]["account_id"]!=ACCOUNT:raise ValueError()
        arguments=params["arguments"]
        mails,_=parse_upload((ROOT/"fixtures/mail/sample.mbox").read_bytes(),"sample.mbox","Asia/Shanghai")
        if params["name"]=="list_emails":
            limit=int(arguments["limit"]);offset=int(arguments.get("cursor","0"))
            if not 1<=limit<=20 or not 0<=offset<=len(mails):raise ValueError()
            value={"account_id":ACCOUNT,"messages":[{"id":str(index)} for index in range(offset,min(offset+limit,len(mails)))],"next_cursor":str(offset+limit) if offset+limit<len(mails) else None}
        elif params["name"]=="read_email":
            index=int(arguments["id"])
            if not 0<=index<len(mails):raise ValueError()
            mail=mails[index]
            value={"account_id":ACCOUNT,"id":str(index),"subject":mail.subject,"sender":mail.sender,"body_text":mail.body_text,
                   "date_header":format_datetime(mail.received_at) if mail.received_at else None}
        else:raise ValueError()
        return response({"structuredContent":value,"content":[{"type":"text","text":json.dumps(value,ensure_ascii=False)}]})
    except (ValueError,KeyError,TypeError,IndexError):
        return {"jsonrpc":"2.0","id":id,"error":{"code":-32602,"message":"Unsupported fictional mail operation"}}
