from typing import Protocol


class LLMProvider(Protocol):
    async def chat(self, messages: list[dict], *, json_mode: bool = False) -> str: ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
