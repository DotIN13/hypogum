import json
import base64

from loguru import logger

from hypogum.llm.base import LLMProvider


class AnthropicProvider(LLMProvider):
    """Anthropic Claude LLM via anthropic SDK. No native embedding — requires fallback."""

    def __init__(self, *, api_key: str,
                 model: str = "claude-haiku-4-5",
                 embedding_provider: LLMProvider | None = None):
        self.model = model
        self.embedding_model = None
        self._api_key = api_key
        self._embedding_provider = embedding_provider

    def _client(self):
        from anthropic import AsyncAnthropic
        return AsyncAnthropic(api_key=self._api_key)

    async def generate(
        self,
        system_prompt: str,
        parts: list[dict],
        *,
        response_schema: dict | None = None,
        max_tokens: int = 65536,
    ) -> dict:
        client = self._client()
        messages_content: list[dict] = []

        for part in parts:
            if part["type"] == "text":
                messages_content.append({"type": "text", "text": part["text"]})
            elif part["type"] == "image":
                b64 = base64.b64encode(part["data"]).decode("ascii")
                mime = part.get("mime_type", "image/jpeg")
                messages_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": b64,
                    },
                })

        system_text = system_prompt
        if response_schema:
            schema_str = json.dumps(response_schema, indent=2)
            system_text += f"\n\nYou MUST respond with a JSON object matching this schema exactly:\n```json\n{schema_str}\n```\nReturn ONLY valid JSON, no markdown fences."

        response = await client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_text,
            messages=[{"role": "user", "content": messages_content}],
        )

        raw = response.content[0].text
        if not raw:
            raise ValueError("Empty response from Anthropic")

        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            raw = "\n".join(lines).strip()

        return json.loads(raw)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self._embedding_provider is None:
            raise RuntimeError(
                "Anthropic has no embedding API. Set HYPOGUM_EMBEDDING_PROVIDER "
                "or provide an embedding_provider fallback."
            )
        return await self._embedding_provider.embed(texts)
