import sys
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

# Mock LangChain
sys.modules["langchain_community"] = MagicMock()
sys.modules["langchain_community.document_loaders"] = MagicMock()
sys.modules["langchain_community.chat_models"] = MagicMock()
sys.modules["langchain_text_splitters"] = MagicMock()
sys.modules["langchain_redis"] = MagicMock()
sys.modules["langchain_ollama"] = MagicMock()
sys.modules["langchain_core"] = MagicMock()
sys.modules["langchain_core.documents"] = MagicMock()
sys.modules["langchain_core.prompts"] = MagicMock()
sys.modules["langchain_core.runnables"] = MagicMock()
sys.modules["langchain_core.output_parsers"] = MagicMock()
sys.modules["redis"] = MagicMock()

import savantbot.api as api  # noqa: E402
from savantbot.api import app, config  # noqa: E402

client = TestClient(app)


def test_root_redirect():
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


@patch("savantbot.api.Redis.from_url")
def test_vectorstore_health_ready(mock_redis_from_url):
    # Setup mocks
    mock_redis = mock_redis_from_url.return_value
    mock_redis.ft.return_value.info.return_value = {"num_docs": 42}

    api.vectorstore = MagicMock()
    config.update(
        {
            "redis_url": "redis://localhost:6389",
            "index_name": "savant-embeddings",
            "embedding_model": "bge-m3",
        }
    )

    response = client.get("/api/health/vectorstore")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["records"] == 42
    assert data["index_name"] == "savant-embeddings"


def test_vectorstore_health_uninitialized():
    api.vectorstore = None
    response = client.get("/api/health/vectorstore")
    assert response.status_code == 200
    assert response.json()["status"] == "uninitialized"
