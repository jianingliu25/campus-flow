import asyncio
from dataclasses import replace

import httpx2
import pytest
from sqlalchemy import select

from app.llm.compatible import CompatibleProvider, ProcessingGateway, ProviderConfig, normalize_endpoint
from app.models import SourcePolicy
from app.security.policies import BoundaryError

MESSAGES = [{"role": "user", "content": "fictional question"}]


@pytest.mark.parametrize("purpose", ["ingest", "chat", "summary", "repair", "reprocess", "profile", "qa_memory", "embedding"])
def test_cloud_disabled_prevents_provider_creation_in_every_branch(store, purpose):
    db, a, *_ = store
    calls = []
    config = ProviderConfig("cloud", "https://provider.example.org/v1", "test-model", "fictional-key", False)
    with db.transaction() as session:
        policy = session.scalar(select(SourcePolicy).where(SourcePolicy.source_id == a.source_id))
        policy.allow_remote_processing, policy.consent_fingerprint = True, config.fingerprint
        policy.enable_implicit_profile, policy.enable_qa_memory = True, True
    gateway = ProcessingGateway(db, config, factory=lambda config: calls.append(config))
    with pytest.raises(BoundaryError):
        asyncio.run(gateway.process(a, purpose, MESSAGES))
    assert calls == []


def test_consent_is_source_and_provider_specific_and_revocation_blocks_return(store):
    db, a, b, _ = store
    config = ProviderConfig("cloud", "https://provider.example.org/v1", "model-a", "fictional-key", True)
    calls = []

    class Stub:
        async def chat(self, messages, **kwargs):
            calls.append(messages)
            return "fictional answer"

    gateway = ProcessingGateway(db, config, lambda config: Stub())
    with pytest.raises(BoundaryError):
        asyncio.run(gateway.process(a, "chat", MESSAGES))
    with db.transaction() as session:
        policy = session.scalar(select(SourcePolicy).where(SourcePolicy.source_id == a.source_id))
        policy.allow_remote_processing, policy.consent_fingerprint = True, config.fingerprint
    assert asyncio.run(gateway.process(a, "chat", MESSAGES)) == "fictional answer"
    with pytest.raises(BoundaryError):
        asyncio.run(gateway.process(b, "chat", MESSAGES))
    changed = ProcessingGateway(db, replace(config, model="model-b"), lambda config: Stub())
    with pytest.raises(BoundaryError):
        asyncio.run(changed.process(a, "chat", MESSAGES))
    assert len(calls) == 1

    class RevokingProvider:
        async def chat(self, messages, **kwargs):
            with db.transaction() as session:
                policy = session.scalar(select(SourcePolicy).where(SourcePolicy.source_id == a.source_id))
                policy.allow_remote_processing = False
                policy.version += 1
            return "must not be returned"

    with pytest.raises(BoundaryError):
        asyncio.run(ProcessingGateway(db, config, lambda config: RevokingProvider()).process(a, "chat", MESSAGES))


def test_fixture_provider_cannot_process_real_sources(store):
    db, a, _, outside = store
    gateway = ProcessingGateway(db, ProviderConfig())
    with pytest.raises(BoundaryError, match="FIXTURE_PROVIDER_FOR_REAL_SOURCE"):
        asyncio.run(gateway.process(a, "chat", MESSAGES))
    assert "不是模型推理" in asyncio.run(gateway.process(outside, "chat", MESSAGES))


@pytest.mark.parametrize("url", ["https://cloud.example.org/v1", "http://192.168.1.2/v1", "http://127.0.0.1@evil.example.org/v1", "file:///mail", "http://127.0.0.1/v1?key=bad"])
def test_local_label_never_allows_remote_or_ambiguous_endpoint(url):
    with pytest.raises(BoundaryError):
        normalize_endpoint(ProviderConfig("local", url, "test"))
    assert normalize_endpoint(ProviderConfig("local", "http://localhost:11434/v1", "test")) == "http://127.0.0.1:11434/v1"


def test_cloud_dns_pinning_and_redirect_rejection():
    seen = []

    def response(request):
        seen.append(request)
        return httpx2.Response(200, json={"choices": [{"message": {"content": "mock answer"}}]})

    async def public(host, port):
        return ["8.8.8.8"]  # mock transport, never an actual network request

    config = ProviderConfig("cloud", "https://provider.example.org/v1", "test", "fixture-secret", True)
    provider = CompatibleProvider(config, httpx2.MockTransport(response), public)
    assert asyncio.run(provider.chat(MESSAGES)) == "mock answer"
    assert seen[0].url.host == "8.8.8.8"
    assert seen[0].headers["host"] == "provider.example.org"
    assert seen[0].extensions["sni_hostname"] == "provider.example.org"
    assert "fixture-secret" not in repr(config)
    redirect = CompatibleProvider(config, httpx2.MockTransport(lambda request: httpx2.Response(302, headers={"location": "http://127.0.0.1/secret"})), public)
    with pytest.raises(BoundaryError, match="REDIRECT"):
        asyncio.run(redirect.chat(MESSAGES))


def test_private_dns_resolution_does_not_reach_transport():
    calls = []

    async def private(host, port):
        return ["169.254.169.254"]

    config = ProviderConfig("cloud", "https://provider.example.org/v1", "test", "fictional-key", True)
    provider = CompatibleProvider(config, httpx2.MockTransport(lambda request: calls.append(request)), private)
    with pytest.raises(BoundaryError, match="NOT_PUBLIC"):
        asyncio.run(provider.chat(MESSAGES))
    assert calls == []


def test_local_compatible_transport_and_safe_errors():
    config = ProviderConfig("local", "http://127.0.0.1:11434/v1", "test")
    import json
    requests = []
    def reply(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json={"choices": [{"message": {"content": '{"category":"academic"}'}}]})
    provider = CompatibleProvider(config, httpx2.MockTransport(reply))
    assert '"academic"' in asyncio.run(provider.chat(MESSAGES, json_mode=True))
    assert "response_format" not in requests[0]
    assert "JSON" in requests[0]["messages"][0]["content"]
    native = CompatibleProvider(replace(config, supports_json_mode=True), httpx2.MockTransport(reply))
    asyncio.run(native.chat(MESSAGES, json_mode=True))
    assert requests[1]["response_format"]["type"] == "json_object"
    invalid = CompatibleProvider(config, httpx2.MockTransport(lambda request: httpx2.Response(401, text="fictional-sensitive-body")))
    with pytest.raises(BoundaryError) as error:
        asyncio.run(invalid.chat(MESSAGES))
    assert "fictional-sensitive-body" not in str(error.value)
