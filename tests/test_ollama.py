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
sys.modules["langchain_core.document_loaders"] = MagicMock()
sys.modules["langchain_core.documents"] = MagicMock()
sys.modules["langchain_core.prompts"] = MagicMock()
sys.modules["langchain_core.runnables"] = MagicMock()
sys.modules["langchain_core.output_parsers"] = MagicMock()
sys.modules["redis"] = MagicMock()

import pytest  # noqa: E402

from savantbot.api import app, config  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_config():
    config.update({"ollama_base_url": "http://localhost:11434"})
    yield


@patch("httpx.AsyncClient.get")
def test_list_ollama_models(mock_get):
    mock_get.return_value = MagicMock(status_code=200)
    mock_get.return_value.json.return_value = {"models": [{"name": "test-model"}]}

    response = client.get("/api/ollama/models")
    assert response.status_code == 200
    assert response.json()["models"][0]["name"] == "test-model"


@patch("savantbot.api.pull_models_background")
def test_pull_ollama_model(mock_pull):
    response = client.post("/api/ollama/pull", json={"model_name": "new-model"})
    assert response.status_code == 200
    assert "Started pulling" in response.json()["message"]
    mock_pull.assert_called_once_with(["new-model"], "http://localhost:11434")


@patch("httpx.AsyncClient.request")
def test_delete_ollama_model(mock_request):
    mock_request.return_value = MagicMock(status_code=200)

    response = client.delete("/api/ollama/models/old-model")
    assert response.status_code == 200
    assert "deleted successfully" in response.json()["message"]

    # Verify the call to Ollama API
    args, kwargs = mock_request.call_args
    assert args[0] == "DELETE"
    assert "api/delete" in args[1]
    assert kwargs["json"] == {"name": "old-model"}
