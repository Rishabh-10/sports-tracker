"""Local text embeddings (fastembed + ONNX, no GPU or API needed)."""

from functools import cache
from pathlib import Path
from typing import Protocol

import numpy as np

from sports_info import config


class Embedder(Protocol):
    def embed_passages(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return (vectors / np.where(norms == 0, 1, norms)).astype(np.float32)


class LocalEmbedder:
    def __init__(self, model_name: str = config.EMBEDDING_MODEL, cache_dir: Path = config.MODELS_DIR):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding  # slow import; only pay for it when used

            self._model = TextEmbedding(self.model_name, cache_dir=str(self.cache_dir))
        return self._model

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        return _normalize(np.array(list(self._load().passage_embed(texts))))

    def embed_query(self, text: str) -> np.ndarray:
        return _normalize(np.array(list(self._load().query_embed(text)))[0])


@cache
def get_embedder() -> Embedder:
    return LocalEmbedder()


def to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def from_blobs(blobs: list[bytes]) -> np.ndarray:
    return np.vstack([np.frombuffer(b, dtype=np.float32) for b in blobs]) if blobs else np.zeros((0, 0), np.float32)
