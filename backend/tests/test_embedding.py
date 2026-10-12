import pytest

from app.memory.embedding import EmbeddingGateway
from app.security.policies import BoundaryError, SourceContext


def test_embedding_is_local_and_cannot_cross_workspaces(store):
    db, a, _, outside = store
    calls = []

    class LocalStub:
        processing_location = "local"

        def embed(self, texts):
            calls.extend(texts)
            return [[1.0, 0.0] for text in texts]

    gateway = EmbeddingGateway(db, "test-local-only", lambda: LocalStub())
    assert gateway.embed(a, ["fictional"]) == [[1.0, 0.0]]
    with pytest.raises(BoundaryError):
        gateway.embed(SourceContext(a.workspace_id, outside.source_id), ["do not dispatch"])
    assert calls == ["fictional"]


def test_embedding_rejects_remote_factory_and_nonfinite_vectors(store):
    db, a, *_ = store

    class RemoteStub:
        processing_location = "remote"

        def embed(self, texts):
            raise AssertionError("Must never dispatch")

    with pytest.raises(BoundaryError, match="REMOTE_EMBEDDING"):
        EmbeddingGateway(db, "test", RemoteStub).embed(a, ["fictional"])

    class BrokenLocalStub:
        processing_location = "local"

        def embed(self, texts):
            return [[float("nan")]]

    with pytest.raises(BoundaryError, match="INVALID_EMBEDDING_OUTPUT"):
        EmbeddingGateway(db, "test", BrokenLocalStub).embed(a, ["fictional"])
