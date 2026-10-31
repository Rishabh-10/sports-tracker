import os
import re
import zlib

import numpy as np
import pytest
from sqlmodel import SQLModel

from sports_info.store import db

# Set to run the suite against Postgres, e.g. postgresql://postgres:test@localhost:5432/sports_test.
# Every table in that database is dropped after each test, so use a database just for tests.
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")


@pytest.fixture
def temp_db(tmp_path):
    """Point the app at a throwaway database: a SQLite file, or Postgres if TEST_DATABASE_URL is set."""
    engine = db.init_db(url=TEST_DATABASE_URL) if TEST_DATABASE_URL else db.init_db(tmp_path / "test.db")
    yield engine
    if TEST_DATABASE_URL:
        SQLModel.metadata.drop_all(engine)
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
    """Create a user directly (as if they'd signed in with Google) and return its id."""
    from sports_info.store import repo
    from sports_info.store.db import get_session

    def create(name: str) -> int:
        with get_session() as session:
            return repo.create_user(session, f"google-{name}", f"{name}@example.com", name.title()).id

    return create
