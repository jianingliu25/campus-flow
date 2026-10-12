"""Local embedding boundary. Concrete model loading is a later milestone."""

import hashlib
import math

from app.security.policies import BoundaryError, authorize_processing


class EmbeddingGateway:
    def __init__(self, database, model_id, factory):
        self.database, self.model_id, self.factory = database, model_id, factory
        self.fingerprint = hashlib.sha256(f"local-embedding:{model_id}".encode()).hexdigest()

    def check(self, session, ctx):
        return authorize_processing(session, ctx, purpose="embedding", provider_mode="local", fingerprint=self.fingerprint, global_remote=False)

    def embed(self, ctx, texts):
        with self.database.transaction() as session:
            version = self.check(session, ctx)
        if not texts or len(texts) > 100 or any(not isinstance(text, str) or len(text) > 32000 for text in texts):
            raise BoundaryError("INVALID_EMBEDDING_INPUT", 422)
        provider = self.factory()
        if getattr(provider, "processing_location", None) != "local":
            raise BoundaryError("REMOTE_EMBEDDING_DISABLED")
        try:
            vectors = provider.embed(texts)
            dimensions = {len(vector) for vector in vectors}
            if len(vectors) != len(texts) or len(dimensions) != 1 or 0 in dimensions or any(not math.isfinite(value) for vector in vectors for value in vector):
                raise ValueError()
        except (ValueError, TypeError):
            raise BoundaryError("INVALID_EMBEDDING_OUTPUT", 502) from None
        with self.database.transaction() as session:
            if self.check(session, ctx) != version:
                raise BoundaryError("POLICY_CHANGED_DURING_PROCESSING", 409)
        return vectors
