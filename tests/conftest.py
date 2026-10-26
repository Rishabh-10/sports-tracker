import re
import zlib

import numpy as np
import pytest

from sports_info.store import db


@pytest.fixture
def temp_db(tmp_path):
    """Point the app at a throwaway SQLite file."""
    engine = db.init_db(tmp_path / "test.db")
    yield engine
    engine.dispose()
    db._engine = None


class FakeEmbedder:
    """Bag-of-words hashed into a small vector: texts sharing words are similar."""

    dim = 256

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        for word in re.findall(r"\w+", text.lower()):
            vector[zlib.crc32(word.encode()) % self.dim] += 1
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def embed_passages(self, texts):
        return np.vstack([self._vector(t) for t in texts])

    def embed_query(self, text):
        return self._vector(text)


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture
def make_user(temp_db):
    """Create a user directly (no password hashing cost) and return its id."""
    from sports_info.store import repo
    from sports_info.store.db import get_session

    def create(username: str) -> int:
        with get_session() as session:
            return repo.create_user(session, username, "unused-hash").id

    return create
