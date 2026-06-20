import asyncio
import json

from loguru import logger

from hypogum.llm.base import LLMProvider


class GeminiProvider(LLMProvider):
    """Gemini LLM via google-genai SDK."""

    def __init__(self, *, api_key: str,
                 model: str = "gemini-3.1-flash-lite",
                 embedding_model: str = "gemini-embedding-2"):
        self.model = model
        self.embedding_model = embedding_model
        self._api_key = api_key

    def _client(self):
        from google import genai
        return genai.Client(api_key=self._api_key)

    async def generate(
        self,
        system_prompt: str,
        parts: list[dict],
        *,
        response_schema: dict | None = None,
        max_tokens: int = 65536,
    ) -> dict:
        from google.genai import types

        client = self._client()
        contents: list = [system_prompt]
        for part in parts:
            if part["type"] == "text":
                contents.append(part["text"])
            elif part["type"] == "image":
                contents.append(types.Part.from_bytes(
                    data=part["data"], mime_type=part.get("mime_type", "image/jpeg"),
                ))

        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
            response_mime_type="application/json",
            max_output_tokens=max_tokens,
        )
        if response_schema:
            config.response_json_schema = response_schema

        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            ),
            timeout=90,
        )

        raw = response.text
        if not raw:
            raise ValueError("Empty response from Gemini")
        return json.loads(raw)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        client = self._client()
        tasks = [
            asyncio.wait_for(
                client.aio.models.embed_content(
                    model=self.embedding_model or "gemini-embedding-2",
                    contents=text,
                ),
                timeout=30,
            )
            for text in texts
        ]
        results = await asyncio.gather(*tasks)
        return [r.embeddings[0].values for r in results if r and r.embeddings]
