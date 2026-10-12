"""Explicit loopback or public HTTPS endpoints, DNS pinned; no proxies or redirects."""
import ipaddress
import json
from urllib.parse import urlsplit

import httpx2

from app.llm.compatible import resolve_public
from app.security.policies import BoundaryError


def endpoint(value):
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise BoundaryError("INVALID_CONNECTOR_ENDPOINT", 422) from None
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise BoundaryError("INVALID_CONNECTOR_ENDPOINT", 422)
    host = "127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = False
    if parsed.scheme not in {"http", "https"} or (not local and parsed.scheme != "https"):
        raise BoundaryError("CONNECTOR_TLS_REQUIRED", 422)
    return parsed, host, port or (443 if parsed.scheme == "https" else 80), local


class JSONTransport:
    def __init__(self, url, secret="", transport=None, resolver=resolve_public):
        self.url, self.secret, self.transport, self.resolver = url, secret, transport, resolver

    async def send(self, message, headers=None, method="POST"):
        parsed, host, port, local = endpoint(self.url)
        target = httpx2.URL(self.url)
        output_headers = {"Accept":"application/json, text/event-stream", **(headers or {})}
        extensions = {}
        if local:
            target=target.copy_with(host=host)
        if not local:
            try:
                addresses = await self.resolver(host, port)
            except (OSError,ValueError):
                raise BoundaryError("CONNECTOR_DNS_UNAVAILABLE",503) from None
            if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
                raise BoundaryError("CONNECTOR_ADDRESS_REJECTED", 403)
            output_headers["Host"] = target.netloc.decode()
            extensions["sni_hostname"] = host
            target = target.copy_with(host=addresses[0])
        if self.secret:
            output_headers["Authorization"] = "Bearer " + self.secret
        try:
            async with httpx2.AsyncClient(transport=self.transport, trust_env=False, follow_redirects=False, timeout=20) as client:
                async with client.stream(method, target, json=message if method=="POST" else None,
                                         headers=output_headers, extensions=extensions) as response:
                    if response.status_code in {401,403}:
                        raise BoundaryError("CONNECTOR_AUTH_FAILED", 403)
                    if 300 <= response.status_code < 400:
                        raise BoundaryError("CONNECTOR_REDIRECT_REJECTED", 502)
                    if not response.is_success:
                        raise BoundaryError("CONNECTOR_REQUEST_FAILED", 502)
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 2*1024*1024:
                            raise BoundaryError("CONNECTOR_RESPONSE_TOO_LARGE", 502)
                    session = response.headers.get("Mcp-Session-Id")
                    if session and (len(session)>200 or any(ord(c)<33 or ord(c)>126 for c in session)):
                        raise BoundaryError("MCP_INVALID_SESSION", 502)
                    if not raw:
                        return None, session
                    if "text/event-stream" in response.headers.get("content-type", ""):
                        values = []
                        for block in raw.decode("utf-8").replace("\r\n","\n").split("\n\n"):
                            lines = [line[5:].lstrip() for line in block.splitlines() if line.startswith("data:")]
                            if lines and "\n".join(lines).strip():
                                values.append(json.loads("\n".join(lines)))
                        matches = [value for value in values if isinstance(value,dict) and value.get("id")==message.get("id") and ("result" in value or "error" in value)]
                        if len(matches)!=1:
                            raise ValueError()
                        return matches[0], session
                    return json.loads(raw), session
        except (httpx2.HTTPError,ValueError,TypeError,UnicodeError):
            raise BoundaryError("CONNECTOR_RESPONSE_INVALID", 502) from None
