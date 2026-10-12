"""TLS-only IMAP reader: EXAMINE plus UID BODY.PEEK; never STORE/EXPUNGE."""
import asyncio
from dataclasses import replace
from datetime import timedelta
import hashlib
import imaplib
import ipaddress
import re
import socket
import ssl

from app.models import utcnow
from app.security.policies import BoundaryError
from app.sources.local_files import decode_message, MAX_MESSAGE


class PinnedIMAP(imaplib.IMAP4_SSL):
    def __init__(self, host, port, address):
        self.address = address
        super().__init__(host, port, ssl_context=ssl.create_default_context(), timeout=15)

    def _create_socket(self, timeout):
        sock = socket.create_connection((self.address, self.port), timeout)
        try:
            return self.ssl_context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise

    def read(self,size):
        if size>MAX_MESSAGE:
            raise BoundaryError("MESSAGE_TOO_LARGE",413)
        return super().read(size)


class IMAPAdapter:
    def __init__(self, config, secret, factory=None):
        self.config, self.secret, self.factory = config, secret, factory
        self.client = None

    def connect(self):
        if self.factory:
            self.client = self.factory()
        else:
            addresses = {row[4][0] for row in socket.getaddrinfo(self.config["host"],self.config["port"],0,socket.SOCK_STREAM)}
            if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
                raise BoundaryError("CONNECTOR_ADDRESS_REJECTED",403)
            self.client = PinnedIMAP(self.config["host"], self.config["port"], sorted(addresses)[0])
        try:
            kind, _ = self.client.login(self.config["username"],self.secret)
            if kind != "OK":
                raise BoundaryError("CONNECTOR_AUTH_FAILED",403)
        except imaplib.IMAP4.error:
            self.close_sync()
            raise BoundaryError("CONNECTOR_AUTH_FAILED",403) from None

    def close_sync(self):
        if self.client:
            try:
                self.client.logout()  # no CLOSE or expunge
            except (OSError,imaplib.IMAP4.error):
                pass
            self.client = None

    async def close(self):
        await asyncio.to_thread(self.close_sync)

    def select(self, folder):
        if not re.fullmatch(r"[A-Za-z0-9 /_.&+\-]{1,120}",folder):
            raise BoundaryError("UNSUPPORTED_IMAP_FOLDER",422)
        kind, _ = self.client.select('"'+folder+'"',readonly=True)
        if kind != "OK":
            raise BoundaryError("MAILBOX_UNAVAILABLE",403)
        _, values = self.client.response("UIDVALIDITY")
        epoch = values[0].decode() if values and values[0] else ""
        if not epoch.isdigit():
            raise BoundaryError("IMAP_UIDVALIDITY_MISSING",502)
        return epoch

    async def test(self):
        try:
            await asyncio.to_thread(self.connect)
            epoch = await asyncio.to_thread(self.select,self.config.get("folder","INBOX"))
            return {"read_only":True,"uidvalidity":epoch,"account_verified":True,"transport":"IMAPS with verified TLS"}
        except (OSError,ssl.SSLError,imaplib.IMAP4.error):
            raise BoundaryError("IMAP_CONNECTION_FAILED",502) from None
        finally:
            await self.close()

    def fetch_sync(self, scope, cursor, timezone_name):
        if self.client is None:
            self.connect()
        folder = self.config.get("folder","INBOX")
        if scope.get("folders") and folder not in scope["folders"]:
            raise BoundaryError("FOLDER_OUTSIDE_SCOPE",403)
        epoch = self.select(folder)
        uid = cursor.get("uid",0) if cursor.get("uidvalidity")==epoch else 0
        since = (utcnow()-timedelta(days=scope["recent_days"])).strftime("%d-%b-%Y")
        kind, result = self.client.uid("SEARCH",None,"SINCE",since,"UID",f"{uid+1}:*")
        if kind!="OK" or not result or not isinstance(result[0],bytes) or len(result[0])>1024*1024:
            raise BoundaryError("IMAP_SEARCH_INVALID",502)
        limit=min(scope["max_messages"],20)
        identifiers = sorted({int(value) for value in result[0].split() if value.isdigit() and int(value)>uid})[:limit]
        mails, errors = [], []
        for identifier in identifiers:
            kind, sizes = self.client.uid("FETCH",str(identifier),"(RFC822.SIZE)")
            size_bytes = b" ".join(value for value in sizes if isinstance(value,bytes))
            size_match = re.search(rb"RFC822.SIZE (\d+)",size_bytes)
            if kind!="OK" or not size_match:
                raise BoundaryError("IMAP_SIZE_MISSING",502)
            if int(size_match[1])>MAX_MESSAGE:
                errors.append("MESSAGE_TOO_LARGE")
                continue
            kind, values = self.client.uid("FETCH",str(identifier),"(UID BODY.PEEK[])")
            parts = [value for value in values if isinstance(value,tuple) and len(value)==2 and isinstance(value[1],bytes)]
            if kind!="OK" or len(parts)!=1:
                raise BoundaryError("IMAP_FETCH_INVALID",502)
            try:
                mail=decode_message(parts[0][1],timezone_name,f"IMAP {folder} UID {identifier}")
                stable=hashlib.sha256(f"{folder}:{epoch}:{identifier}".encode()).hexdigest()
                mails.append(replace(mail,external_id="imap:"+stable))
            except BoundaryError as error:
                errors.append(error.code)
        return mails, {"uidvalidity":epoch,"uid":max(identifiers,default=uid)}, len(identifiers)<limit, errors

    async def fetch_page(self, scope, cursor, timezone_name):
        try:
            return await asyncio.to_thread(self.fetch_sync,scope,cursor,timezone_name)
        except (OSError,ssl.SSLError,imaplib.IMAP4.error,ValueError,TypeError):
            raise BoundaryError("IMAP_READ_FAILED",502) from None
