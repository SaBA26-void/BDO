"""Embedding the chunks (with an on-disk cache) and finding the ones closest to a question."""

import hashlib
import json
import math
import os
import time
from typing import List, Tuple

from openai import OpenAI, RateLimitError

from src.rag.chunking import DocumentChunk

EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
# Small batches + retry keep us inside the free-tier tokens-per-minute quota.
EMBEDDING_BATCH_SIZE = 20
EMBEDDING_DIMENSIONS = 768
RATE_LIMIT_RETRIES = 6
RATE_LIMIT_WAIT_SECONDS = 20

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EMBEDDING_CACHE_FILE = os.path.join(PROJECT_ROOT, "data", "embeddings_cache.json")


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class PolicyRetriever:
    def __init__(self, chunks: List[DocumentChunk], client: OpenAI):
        self.chunks = chunks
        self.client = client
        self._embed_chunks()

    def retrieve(self, query: str, top_k: int = 3) -> List[Tuple[DocumentChunk, float]]:
        query_embedding = self._embed([query])[0]
        scored_chunks = [(chunk, cosine_similarity(query_embedding, chunk.embedding)) for chunk in self.chunks]
        scored_chunks.sort(key=lambda x: x[1], reverse=True)

        # Relevance picks the chunks; priority orders them so the newest policy comes first.
        # Multiplying similarity by priority would drown relevant lower-priority documents,
        # since embedding similarities fall in a narrow range.
        top = scored_chunks[:top_k]
        top.sort(key=lambda x: (x[0].priority, x[1]), reverse=True)
        return top

    def _embed_chunks(self) -> None:
        """Embed chunks, reusing cached vectors so unchanged documents are embedded only once."""
        cache = _load_cache()
        keys = [_cache_key(chunk.text) for chunk in self.chunks]

        missing = [i for i, key in enumerate(keys) if key not in cache]
        if missing:
            new_embeddings = self._embed([self.chunks[i].text for i in missing])
            for i, embedding in zip(missing, new_embeddings):
                cache[keys[i]] = embedding
            _save_cache({key: cache[key] for key in keys})

        for chunk, key in zip(self.chunks, keys):
            chunk.embedding = cache[key]

    def _embed(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start:start + EMBEDDING_BATCH_SIZE]
            embeddings.extend(self._embed_batch_with_retry(batch))
        return embeddings

    def _embed_batch_with_retry(self, batch: List[str]) -> List[List[float]]:
        for attempt in range(RATE_LIMIT_RETRIES):
            try:
                response = self.client.embeddings.create(
                    model=EMBEDDING_MODEL, input=batch, dimensions=EMBEDDING_DIMENSIONS
                )
                return [item.embedding for item in response.data]
            except RateLimitError:
                if attempt == RATE_LIMIT_RETRIES - 1:
                    raise
                time.sleep(RATE_LIMIT_WAIT_SECONDS)
        return []  # unreachable: the loop either returns or raises


def _cache_key(text: str) -> str:
    return hashlib.sha256(f"{EMBEDDING_MODEL}:{text}".encode("utf-8")).hexdigest()


def _load_cache() -> dict:
    if not os.path.exists(EMBEDDING_CACHE_FILE):
        return {}
    with open(EMBEDDING_CACHE_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(EMBEDDING_CACHE_FILE), exist_ok=True)
    with open(EMBEDDING_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)
