import os
import pytest
import json
import shutil
import sys
from unittest.mock import MagicMock, patch

# Robust mocking of all LangChain related submodules
sys.modules['langchain_community'] = MagicMock()
sys.modules['langchain_community.document_loaders'] = MagicMock()
sys.modules['langchain_community.chat_models'] = MagicMock()
sys.modules['langchain_text_splitters'] = MagicMock()
sys.modules['langchain_redis'] = MagicMock()
sys.modules['langchain_ollama'] = MagicMock()
sys.modules['langchain_core'] = MagicMock()
sys.modules['langchain_core.documents'] = MagicMock()
sys.modules['langchain_core.prompts'] = MagicMock()
sys.modules['langchain_core.runnables'] = MagicMock()
sys.modules['langchain_core.output_parsers'] = MagicMock()
sys.modules['redis'] = MagicMock()

from fastapi.testclient import TestClient

# Now we can import the app
from savantbot.api import app, DATA_DIR, CONFIG_PATH, config

client = TestClient(app)
API_KEY = "test-secret-key"

@pytest.fixture(autouse=True)
def setup_teardown():
    # Setup: Ensure clean environment
    if os.path.exists(DATA_DIR):
        shutil.rmtree(DATA_DIR)
    os.makedirs(DATA_DIR)
    
    if os.path.exists(CONFIG_PATH):
        os.remove(CONFIG_PATH)
    
    # Initialize global config with all needed keys
    config.clear()
    config.update({
        "rag_template": "template",
        "embedding_model": "bge-m3",
        "default_chat_model": "qwen2.5:latest",
        "redis_url": "redis://localhost:6389",
        "index_name": "savant-embeddings",
        "allowed_user_ids": []
    })
    
    # Set API Key for testing
    os.environ["SAVANT_API_KEY"] = API_KEY
    
    yield
    
    # Teardown
    if os.path.exists(DATA_DIR):
        shutil.rmtree(DATA_DIR)
    if os.path.exists(CONFIG_PATH):
        os.remove(CONFIG_PATH)

def test_auth_missing_key():
    response = client.get("/api/config")
    assert response.status_code == 403

def test_auth_wrong_key():
    response = client.get("/api/config", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 403

def test_auth_success():
    response = client.get("/api/config", headers={"X-API-Key": API_KEY})
    assert response.status_code == 200

def test_path_traversal_upload_prevention():
    traversal_filename = "../traversed.txt"
    files = {'file': (traversal_filename, "content", "text/plain")}
    
    with patch('savantbot.api.setup_vector_db'):
        response = client.post(
            "/api/data/upload", 
            files=files, 
            headers={"X-API-Key": API_KEY}
        )
    
    assert response.status_code == 200
    assert os.path.exists(os.path.join(DATA_DIR, "traversed.txt"))
    assert not os.path.exists("traversed.txt")

def test_path_traversal_append_prevention():
    traversal_filename = "../../evil.txt"
    payload = {"text": "some text", "filename": traversal_filename}
    
    with patch('savantbot.api.setup_vector_db'):
        response = client.post(
            "/api/data/text", 
            json=payload, 
            headers={"X-API-Key": API_KEY}
        )
    
    assert response.status_code == 200
    assert os.path.exists(os.path.join(DATA_DIR, "evil.txt"))
    assert not os.path.exists("evil.txt")

def test_user_management():
    # Add user
    response = client.post(
        "/api/users", 
        json={"user_id": 12345}, 
        headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 200
    assert 12345 in response.json()["users"]
    
    # Check auth
    response = client.get("/api/auth/12345", headers={"X-API-Key": API_KEY})
    assert response.json()["allowed"] is True
    
    # Remove user
    response = client.delete("/api/users/12345", headers={"X-API-Key": API_KEY})
    assert response.status_code == 200
    assert 12345 not in response.json()["users"]
