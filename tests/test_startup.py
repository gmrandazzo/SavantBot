import json
import os
import shutil
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
sys.modules["langchain_core.document_loaders"] = MagicMock()
sys.modules["langchain_core.documents"] = MagicMock()
sys.modules["langchain_core.prompts"] = MagicMock()
sys.modules["langchain_core.runnables"] = MagicMock()
sys.modules["langchain_core.output_parsers"] = MagicMock()
sys.modules["redis"] = MagicMock()

import savantbot.api as api  # noqa: E402
from savantbot.api import CONFIG_PATH, DATA_DIR, config, load_config, setup_vector_db  # noqa: E402


@pytest.fixture(autouse=True)
def reset_state():
    api.is_pulling_models = False
    api.vectorstore = None
    api.retriever = None
    if os.path.exists(DATA_DIR):
        shutil.rmtree(DATA_DIR)
    os.makedirs(DATA_DIR)
    if os.path.exists(CONFIG_PATH):
        os.remove(CONFIG_PATH)
    config.clear()
    yield


def test_load_config_fresh_creates_allowed_user_ids():
    """A missing allowed_user_ids key must not raise KeyError on startup."""
    api.config.clear()
    with open(CONFIG_PATH, "w") as f:
        json.dump(
            {
                "rag_template": "template",
                "embedding_model": "bge-m3",
                "default_chat_model": "qwen2.5:latest",
                "redis_url": "redis://localhost:6389",
                "ollama_base_url": "http://localhost:11434",
                "index_name": "savant-embeddings",
            },
            f,
        )

    load_config()

    assert "allowed_user_ids" in api.config
    assert api.config["allowed_user_ids"] == []


def test_load_config_migrates_string_user_ids():
    """Existing string user IDs must be converted to integers."""
    api.config.clear()
    with open(CONFIG_PATH, "w") as f:
        json.dump(
            {
                "rag_template": "template",
                "embedding_model": "bge-m3",
                "default_chat_model": "qwen2.5:latest",
                "redis_url": "redis://localhost:6389",
                "ollama_base_url": "http://localhost:11434",
                "index_name": "savant-embeddings",
                "allowed_user_ids": ["123", "456"],
            },
            f,
        )

    load_config()

    assert api.config["allowed_user_ids"] == [123, 456]


@patch.dict(os.environ, {"ALLOWED_USER_IDS": "111,222"}, clear=False)
def test_load_config_bootstraps_allowed_user_ids_from_env():
    """When allowed_user_ids is absent, env var should seed the whitelist."""
    api.config.clear()
    with open(CONFIG_PATH, "w") as f:
        json.dump(
            {
                "rag_template": "template",
                "embedding_model": "bge-m3",
                "default_chat_model": "qwen2.5:latest",
                "redis_url": "redis://localhost:6389",
                "ollama_base_url": "http://localhost:11434",
                "index_name": "savant-embeddings",
            },
            f,
        )

    load_config()

    assert api.config["allowed_user_ids"] == [111, 222]


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
            "ollama_base_url": "http://localhost:11434",
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
            "ollama_base_url": "http://localhost:11434",
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
