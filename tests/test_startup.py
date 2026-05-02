import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Robust mocking of all LangChain related submodules
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
from savantbot.api import DATA_DIR, config, setup_vector_db  # noqa: E402


@pytest.fixture(autouse=True)
def reset_state():
    api.is_pulling_models = False
    api.vectorstore = None
    api.retriever = None
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    yield


@patch("httpx.Client")
@patch("threading.Thread")
def test_setup_vector_db_missing_model(mock_thread, mock_httpx_client):
    # Mock Ollama returning empty models list
    mock_client_instance = mock_httpx_client.return_value.__enter__.return_value
    mock_client_instance.get.return_value = MagicMock(status_code=200)
    mock_client_instance.get.return_value.json.return_value = {"models": []}

    config.update(
        {
            "embedding_model": "bge-m3",
            "default_chat_model": "qwen2.5:latest",
            "redis_url": "redis://localhost:6389",
            "index_name": "savant-embeddings",
        }
    )

    with patch("savantbot.api.OllamaEmbeddings") as mock_embeddings:
        setup_vector_db()

        # Verify background thread was started
        mock_thread.assert_called_once()

        # Verify OllamaEmbeddings was NOT initialized (deferred)
        mock_embeddings.assert_not_called()
        assert api.is_pulling_models is True


@patch("httpx.Client")
@patch("threading.Thread")
def test_setup_vector_db_model_present(mock_thread, mock_httpx_client):
    # Mock Ollama returning the required models
    mock_client_instance = mock_httpx_client.return_value.__enter__.return_value
    mock_client_instance.get.return_value = MagicMock(status_code=200)
    mock_client_instance.get.return_value.json.return_value = {
        "models": [{"name": "bge-m3:latest"}, {"name": "qwen2.5:latest"}]
    }

    config.update(
        {
            "embedding_model": "bge-m3",
            "default_chat_model": "qwen2.5:latest",
            "redis_url": "redis://localhost:6389",
            "index_name": "savant-embeddings",
        }
    )

    with patch("savantbot.api.OllamaEmbeddings") as mock_embeddings:
        with patch("savantbot.api.RedisVectorStore"):
            setup_vector_db()

            # Verify background thread was NOT started
            mock_thread.assert_not_called()

            # Verify OllamaEmbeddings WAS initialized
            mock_embeddings.assert_called_once()
            assert api.is_pulling_models is False
