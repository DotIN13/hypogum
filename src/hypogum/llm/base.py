from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract LLM provider — generate text or structured JSON."""

    model: str

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        parts: list[dict],
        *,
        response_schema: dict | None = None,
        max_tokens: int = 65536,
    ) -> dict:
        """Generate output.

        `parts` is a list of content parts:
          {"type": "text", "text": "..."}
          {"type": "image", "data": bytes, "mime_type": "image/jpeg"}

        When response_schema is provided, returns the parsed JSON dict.
        When response_schema is None, returns {"text": raw_response_text}.
        """
        ...
