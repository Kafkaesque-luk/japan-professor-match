"""
Text embedding — faithful port of ``php傀儡/app/common/clients/EmbeddingClient.php`` (DashScope
``text-embedding-v4``, 1024-d, batch <= 10, order-preserving) plus an OpenAI adapter.

The provider is selected by ``EMBEDDING_PROVIDER``. DashScope is the default and matches the
production index exactly — if you switch to OpenAI you MUST rebuild the index (different model
and dimensionality), otherwise vectors are incomparable.
"""

from __future__ import annotations

from typing import List

import httpx

from ..config import Settings, get_settings

DASHSCOPE_BATCH = 10  # DashScope text-embedding sync API: max 10 texts per call.


class EmbeddingError(RuntimeError):
    pass


class EmbeddingClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()

    def embed_one(self, text: str) -> List[float]:
        return self.embed([text])[0]

    def embed(self, texts: List[str]) -> List[List[float]]:
        texts = list(texts)
        if not texts:
            return []
        if self.s.embedding_provider == "openai":
            return self._embed_openai(texts)
        return self._embed_dashscope(texts)

    # -- DashScope --------------------------------------------------------------------
    def _embed_dashscope(self, texts: List[str]) -> List[List[float]]:
        key = self.s.effective_embedding_key
        if not key:
            raise EmbeddingError("EMBEDDING_API_KEY / QWEN_API_KEY not configured")
        out: List[List[float]] = []
        for i in range(0, len(texts), DASHSCOPE_BATCH):
            out.extend(self._dashscope_batch(texts[i : i + DASHSCOPE_BATCH], key))
        return out

    def _dashscope_batch(self, chunk: List[str], key: str) -> List[List[float]]:
        payload = {"model": self.s.embedding_model, "input": {"texts": chunk}}
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        try:
            r = httpx.post(self.s.embedding_api_url, json=payload, headers=headers,
                           timeout=self.s.qdrant_timeout)
        except httpx.HTTPError as e:
            raise EmbeddingError(f"embedding HTTP request failed: {e}") from e
        if r.status_code != 200:
            raise EmbeddingError(f"embedding API returned HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        embs = data.get("output", {}).get("embeddings")
        if not isinstance(embs, list):
            raise EmbeddingError("embedding API response missing 'embeddings'")
        # DashScope does not guarantee order — realign by text_index.
        ordered = {}
        for seq, item in enumerate(embs):
            idx = item.get("text_index", seq)
            ordered[idx] = item["embedding"]
        if len(ordered) != len(chunk):
            raise EmbeddingError(f"embedding count mismatch: want {len(chunk)} got {len(ordered)}")
        return [ordered[i] for i in sorted(ordered)]

    # -- OpenAI -----------------------------------------------------------------------
    def _embed_openai(self, texts: List[str]) -> List[List[float]]:
        if not self.s.openai_api_key:
            raise EmbeddingError("OPENAI_API_KEY not configured")
        headers = {"Authorization": f"Bearer {self.s.openai_api_key}",
                   "Content-Type": "application/json"}
        payload = {"model": self.s.openai_embedding_model, "input": texts}
        try:
            r = httpx.post("https://api.openai.com/v1/embeddings", json=payload,
                           headers=headers, timeout=self.s.qdrant_timeout)
        except httpx.HTTPError as e:
            raise EmbeddingError(f"embedding HTTP request failed: {e}") from e
        if r.status_code != 200:
            raise EmbeddingError(f"OpenAI embedding HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        items = sorted(data["data"], key=lambda d: d["index"])
        return [it["embedding"] for it in items]
