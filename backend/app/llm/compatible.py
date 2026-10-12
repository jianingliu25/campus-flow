"""Explicit provider identity, consent gate and DNS-pinned compatible requests."""

import asyncio
from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
import os
import socket
from urllib.parse import urlsplit, urlunsplit

import httpx2

from app.security.policies import BoundaryError, authorize_processing


@dataclass(frozen=True)
class ProviderConfig:
    mode: str = "fixture"
    base_url: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    global_remote: bool = False
    supports_json_mode: bool = False

    @classmethod
    def from_environment(cls):
        return cls(os.getenv("LLM_MODE", "fixture"), os.getenv("LLM_BASE_URL", ""), os.getenv("LLM_MODEL", ""),
                   os.getenv("LLM_API_KEY", ""), os.getenv("ALLOW_REMOTE_PROCESSING", "false").lower() == "true",
                   os.getenv("LLM_JSON_MODE", "false").lower() == "true")

    @property
    def fingerprint(self):
        values = [self.mode, self.base_url.rstrip("/"), self.model]
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def normalize_endpoint(config):
    url = urlsplit(config.base_url)
    if url.username or url.password or url.query or url.fragment or not url.hostname:
        raise BoundaryError("INVALID_PROVIDER_ENDPOINT", 422)
    try:
        port = url.port
    except ValueError:
        raise BoundaryError("INVALID_PROVIDER_ENDPOINT", 422) from None
    if config.mode == "local":
        if url.scheme not in {"http", "https"}:
            raise BoundaryError("INVALID_PROVIDER_ENDPOINT", 422)
        host = "127.0.0.1" if url.hostname == "localhost" else url.hostname
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError()
        except ValueError:
            raise BoundaryError("LOCAL_ENDPOINT_MUST_BE_LOOPBACK") from None
        netloc = f"[{host}]" if ":" in host else host
        if port:
            netloc += f":{port}"
        return urlunsplit((url.scheme, netloc, url.path.rstrip("/"), "", ""))
    if config.mode != "cloud" or url.scheme != "https":
        raise BoundaryError("REMOTE_ENDPOINT_REQUIRES_HTTPS")
    return config.base_url.rstrip("/")


async def resolve_public(host, port):
    addresses = await asyncio.to_thread(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
    return sorted({result[4][0] for result in addresses})


class CompatibleProvider:
    def __init__(self, config, transport=None, resolver=resolve_public):
        self.config, self.transport, self.resolver = config, transport, resolver

    async def chat(self, messages, *, json_mode=False):
        config = self.config
        endpoint = normalize_endpoint(config)
        if not config.model or (config.mode == "cloud" and not config.api_key):
            raise BoundaryError("PROVIDER_NOT_CONFIGURED", 409)
        if not messages or len(messages) > 20 or any(set(message) != {"role", "content"} or message["role"] not in {"system", "user", "assistant"} or not isinstance(message["content"], str) for message in messages):
            raise BoundaryError("INVALID_PROVIDER_MESSAGES", 422)
        if sum(len(message["content"]) for message in messages) > 32000:
            raise BoundaryError("PROVIDER_INPUT_TOO_LARGE", 413)
        url = httpx2.URL(endpoint + "/chat/completions")
        headers, extensions = {}, {}
        if config.mode == "cloud":
            try:
                addresses = await self.resolver(url.host, url.port or 443)
                if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
                    raise BoundaryError("REMOTE_ENDPOINT_NOT_PUBLIC")
            except (OSError, ValueError):
                raise BoundaryError("PROVIDER_DNS_UNAVAILABLE", 503) from None
            headers["Host"] = url.netloc.decode()
            extensions["sni_hostname"] = url.host
            url = url.copy_with(host=addresses[0])
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        prepared_messages = messages
        if json_mode and not config.supports_json_mode:
            prepared_messages = [{"role": "system", "content": "Return one valid JSON value only. Do not include Markdown fences."}, *messages]
        payload = {"model": config.model, "messages": prepared_messages, "temperature": 0.2, "max_tokens": 1024}
        if json_mode and config.supports_json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx2.AsyncClient(transport=self.transport, trust_env=False, follow_redirects=False, timeout=30) as client:
                async with client.stream("POST", url, headers=headers, extensions=extensions, json=payload) as response:
                    if 300 <= response.status_code < 400:
                        raise BoundaryError("PROVIDER_REDIRECT_REJECTED", 502)
                    if not response.is_success:
                        raise BoundaryError("PROVIDER_REQUEST_FAILED", 502)
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 524288:
                            raise BoundaryError("PROVIDER_RESPONSE_TOO_LARGE", 502)
            answer = json.loads(content)["choices"][0]["message"]["content"]
            if not isinstance(answer, str):
                raise ValueError()
            if json_mode:
                json.loads(answer)
            return answer
        except (httpx2.HTTPError, ValueError, KeyError, IndexError, TypeError):
            raise BoundaryError("PROVIDER_RESPONSE_INVALID", 502) from None


class FixtureProvider:
    async def chat(self, messages, *, json_mode=False):
        return '{"mode":"fixture","inference":false}' if json_mode else "FixtureProvider：预置演示，不是模型推理。"


class ProcessingGateway:
    """All production processing must use this boundary, including repairs."""
    def __init__(self, database, config, factory=None):
        self.database, self.config = database, config
        self.factory = factory or (lambda config: FixtureProvider() if config.mode == "fixture" else CompatibleProvider(config))

    def check(self, session, ctx, purpose):
        return authorize_processing(session, ctx, purpose=purpose, provider_mode=self.config.mode,
                                    fingerprint=self.config.fingerprint, global_remote=self.config.global_remote)

    async def process(self, ctx, purpose, messages, *, json_mode=False):
        with self.database.transaction() as session:
            version = self.check(session, ctx, purpose)
        if purpose == "embedding":
            raise BoundaryError("USE_LOCAL_EMBEDDING_GATEWAY")
        if self.config.mode != "fixture":
            normalize_endpoint(self.config)
        answer = await self.factory(self.config).chat(messages, json_mode=json_mode)
        with self.database.transaction() as session:
            if self.check(session, ctx, purpose) != version:
                raise BoundaryError("POLICY_CHANGED_DURING_PROCESSING", 409)
        return answer
