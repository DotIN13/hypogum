import json

from loguru import logger

from hypogum.llm.base import LLMProvider


class OpenAIProvider(LLMProvider):
    """OpenAI LLM via openai SDK. Supports structured outputs with response_format."""

    def __init__(self, *, api_key: str,
                 model: str = "gpt-5.4-mini",
                 embedding_model: str = "text-embedding-3-small"):
        self.model = model
        self.embedding_model = embedding_model
        self._api_key = api_key

    def _client(self):
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=self._api_key)

    async def generate(
        self,
        system_prompt: str,
        parts: list[dict],
        *,
        response_schema: dict | None = None,
        max_tokens: int = 65536,
    ) -> dict:
        client = self._client()
        messages: list[dict] = [{"role": "developer", "content": system_prompt}]

        user_content: list[dict] = []
        for part in parts:
            if part["type"] == "text":
                user_content.append({"type": "text", "text": part["text"]})
            elif part["type"] == "image":
                import base64
                b64 = base64.b64encode(part["data"]).decode("ascii")
                mime = part.get("mime_type", "image/jpeg")
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                })
        messages.append({"role": "user", "content": user_content})

        kwargs: dict = {"model": self.model, "messages": messages, "max_tokens": max_tokens}
        if response_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": response_schema,
                },
            }
        else:
            kwargs["response_format"] = {"type": "json_object"}

        response = await client.chat.completions.create(**kwargs)
        raw = response.choices[0].message.content
        if not raw:
            raise ValueError("Empty response from OpenAI")
        return json.loads(raw)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        client = self._client()
        response = await client.embeddings.create(
            model=self.embedding_model or "text-embedding-3-small",
            input=texts,
        )
        return [d.embedding for d in response.data]
