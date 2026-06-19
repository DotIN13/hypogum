from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract LLM provider — generate text + embed text."""

    model: str
    embedding_model: str | None

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        parts: list[dict],
        *,
        response_schema: dict | None = None,
        max_tokens: int = 65536,
    ) -> dict:
        """Generate structured output.

        `parts` is a list of content parts:
          {"type": "text", "text": "..."}
          {"type": "image", "data": bytes, "mime_type": "image/jpeg"}
        Returns the parsed JSON dict from the LLM response.
        """
        ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed one or more text strings. Returns a list of float vectors."""
        ...
