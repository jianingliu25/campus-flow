"""Bounded Streamable HTTP MCP mail contract; remote content never selects tools."""
from dataclasses import replace
from email.message import EmailMessage
import hashlib
import json
import re

from app.security.policies import BoundaryError
from app.sources.local_files import decode_message
from app.sources.network import JSONTransport

LIST_TOOLS={"list_emails","mail.list","list_messages","GMAIL_FETCH_EMAILS"}
READ_TOOLS={"read_email","mail.read","get_email","GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID"}


class MCPAdapter:
    def __init__(self, config, secret, transport=None):
        self.config=config
        self.transport=transport or JSONTransport(config["endpoint"],secret)
        self.session=None
        self.serial=0
        self.version="2025-11-25"
        self.tools={}
        self.guard=lambda:None

    async def rpc(self,method,params=None,notification=False):
        self.guard()
        self.serial+=1
        message={"jsonrpc":"2.0","method":method,"params":params or {}}
        if not notification:
            message["id"]=self.serial
        headers={"MCP-Protocol-Version":self.version}
        if self.session:
            headers["Mcp-Session-Id"]=self.session
        answer, session = await self.transport.send(message,headers)
        if session:
            self.session=session
        if notification:
            if answer is not None:
                raise BoundaryError("MCP_NOTIFICATION_INVALID",502)
            return None
        if not isinstance(answer,dict) or answer.get("jsonrpc")!="2.0" or answer.get("id")!=self.serial or "error" in answer or not isinstance(answer.get("result"),dict):
            raise BoundaryError("MCP_PROTOCOL_INVALID",502)
        return answer["result"]

    async def initialize(self):
        result=await self.rpc("initialize",{"protocolVersion":self.version,"capabilities":{},"clientInfo":{"name":"CampusFlow","version":"0.9.0"}})
        if result.get("protocolVersion") not in {"2025-11-25","2025-06-18","2025-03-26"} or "tools" not in result.get("capabilities",{}):
            raise BoundaryError("MCP_CAPABILITY_UNSUPPORTED",422)
        self.version=result["protocolVersion"]
        await self.rpc("notifications/initialized",notification=True)
        cursor=None
        for _ in range(10):
            page=await self.rpc("tools/list",{"cursor":cursor} if cursor else {})
            if not isinstance(page.get("tools"),list) or len(page["tools"])>100:
                raise BoundaryError("MCP_TOOL_LIST_INVALID",502)
            for tool in page["tools"]:
                if isinstance(tool,dict) and tool.get("name") in LIST_TOOLS|READ_TOOLS:
                    self.tools[tool["name"]]=tool.get("inputSchema",{})
            cursor=page.get("nextCursor")
            if not cursor:
                break
        else:
            raise BoundaryError("MCP_TOOL_LIST_LIMIT",502)
        if self.config["list_tool"] not in self.tools or self.config["read_tool"] not in self.tools:
            raise BoundaryError("MCP_MAIL_TOOLS_MISSING",422)
        return {"read_only":True,"server_name":str(result.get("serverInfo",{}).get("name","unknown"))[:100],
                "protocol_version":self.version,"account_verified":False,"expected_contract":"campusflow-mail-v1","mail_schema_validated":False}

    async def test(self):
        try:
            return await self.initialize()
        finally:
            await self.close()

    async def call(self,name,args):
        if name not in {self.config["list_tool"],self.config["read_tool"]} or name not in LIST_TOOLS|READ_TOOLS:
            raise BoundaryError("MCP_TOOL_NOT_ALLOWED",403)
        schema=self.tools[name]
        if any(key not in args for key in schema.get("required",[])):
            raise BoundaryError("MCP_MAIL_SCHEMA_UNSUPPORTED",422)
        if schema.get("additionalProperties") is False and any(key not in schema.get("properties",{}) for key in args):
            raise BoundaryError("MCP_MAIL_SCHEMA_UNSUPPORTED",422)
        result=await self.rpc("tools/call",{"name":name,"arguments":args})
        if result.get("isError"):
            raise BoundaryError("MCP_TOOL_FAILED",502)
        value=result.get("structuredContent")
        if value is None:
            content=result.get("content",[])
            if len(content)!=1 or content[0].get("type")!="text":
                raise BoundaryError("MCP_MAIL_SCHEMA_UNSUPPORTED",422)
            try:
                value=json.loads(content[0]["text"])
            except (ValueError,KeyError,TypeError):
                raise BoundaryError("MCP_MAIL_SCHEMA_UNSUPPORTED",422) from None
        if not isinstance(value,dict):
            raise BoundaryError("MCP_MAIL_SCHEMA_UNSUPPORTED",422)
        if value.get("account_id") and value["account_id"]!=self.config["account_id"]:
            raise BoundaryError("MCP_ACCOUNT_MISMATCH",403)
        return value

    async def fetch_page(self,scope,cursor,timezone_name):
        if not self.tools:
            await self.initialize()
        # v1 exact contract; vendor-specific meta-tool routers are deliberately rejected.
        limit=min(scope["max_messages"],20)
        args={"account_id":self.config["account_id"],"limit":limit,"recent_days":scope["recent_days"]}
        if cursor.get("cursor"):
            args["cursor"]=cursor["cursor"]
        page=await self.call(self.config["list_tool"],args)
        ids=page.get("messages")
        if not isinstance(ids,list) or len(ids)>limit or any(not isinstance(item,dict) or not isinstance(item.get("id"),str) or len(item["id"])>200 for item in ids):
            raise BoundaryError("MCP_MAIL_SCHEMA_UNSUPPORTED",422)
        mails=[]
        for item in ids:
            mail=await self.call(self.config["read_tool"],{"account_id":self.config["account_id"],"id":item["id"]})
            if mail.get("id")!=item["id"] or not all(isinstance(mail.get(key),str) for key in ["subject","sender","body_text"]):
                raise BoundaryError("MCP_MAIL_SCHEMA_UNSUPPORTED",422)
            if any(len(mail.get(key,""))>limit for key,limit in [("subject",1000),("sender",300),("body_text",32000)]):
                raise BoundaryError("MCP_MAIL_TOO_LARGE",413)
            eml=EmailMessage()
            try:
                eml["From"]=mail["sender"];eml["Subject"]=mail["subject"]
                if mail.get("date_header"):
                    eml["Date"]=mail["date_header"]
                eml.set_content(mail["body_text"])
                parsed=decode_message(eml.as_bytes(),timezone_name,"MCP message "+item["id"])
            except (ValueError,TypeError):
                raise BoundaryError("MCP_MAIL_SCHEMA_UNSUPPORTED",422) from None
            stable=hashlib.sha256((self.config["account_id"]+":"+item["id"]).encode()).hexdigest()
            mails.append(replace(parsed,external_id="mcp:"+stable))
        next_cursor=page.get("next_cursor")
        if next_cursor is not None and (not isinstance(next_cursor,str) or len(next_cursor)>300):
            raise BoundaryError("MCP_CURSOR_INVALID",502)
        if next_cursor and next_cursor==cursor.get("cursor"):
            raise BoundaryError("MCP_CURSOR_STALLED",502)
        return mails,{"cursor":next_cursor},not bool(next_cursor),[]

    async def close(self):
        if self.session:
            try:
                await self.transport.send({}, {"Mcp-Session-Id":self.session,"MCP-Protocol-Version":self.version},method="DELETE")
            except BoundaryError:
                pass
        self.session=None
