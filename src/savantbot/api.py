import json
import logging
import os
import shutil
import threading
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from langchain_community.chat_models import ChatOllama
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_ollama import OllamaEmbeddings
from langchain_redis import RedisVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel
from redis import Redis

# Logging setup
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

CONFIG_PATH = "config.json"
DATA_DIR = "data"
# Global state
config = {}
retriever = None
vectorstore = None


def load_config():
    """Loads or initializes the RAG configuration."""
    global config
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                config = json.load(f)
            logger.info("Configuration loaded from config.json")
        except Exception as e:
            logger.error(f"Error loading config.json: {e}. Using defaults.")
            init_defaults()
    else:
        init_defaults()

    # Ensure allowed_user_ids exists
    if "allowed_user_ids" not in config:
        # Bootstrap from env if available
        raw_ids = os.getenv("ALLOWED_USER_IDS", "")
        config["allowed_user_ids"] = [
            int(i.strip()) for i in raw_ids.split(",") if i.strip()
        ]
        save_config()


def init_defaults():
    """Initializes the default configuration if none exists."""
    global config
    config = {
        "rag_template": (
            "You are an AI roleplaying as a specific person based on their message history.\n\n"
            "Past messages:\n{context}\n\n"
            "User Input: {question}\n"
            "Response:"
        ),
        "embedding_model": "bge-m3",
        "default_chat_model": "qwen2.5:latest",
        "redis_url": os.getenv("REDIS_URL", "redis://localhost:6389"),
        "index_name": "savant-embeddings",
        "allowed_user_ids": [],
    }
    save_config()


def save_config():
    """Saves the current configuration to disk."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


is_pulling_models = False


def pull_models_background(model_names: list[str], ollama_base_url: str):
    """Pulls missing Ollama models in a background thread."""
    global is_pulling_models

    def _pull():
        global is_pulling_models
        try:
            for model in model_names:
                logger.info(f"Attempting to pull model '{model}' from Ollama...")
                with httpx.Client(timeout=None) as client:
                    response = client.post(
                        f"{ollama_base_url}/api/pull",
                        json={"model": model, "stream": False},
                    )
                    if response.status_code == 200:
                        logger.info(f"Successfully pulled model '{model}'.")
                    else:
                        logger.error(
                            f"Failed to pull model '{model}'. Status: {response.status_code}"
                        )

            logger.info("All missing models pulled. Initializing vector store...")
            setup_vector_db()
        except Exception as e:
            logger.error(f"Error while pulling models: {e}")
        finally:
            is_pulling_models = False

    threading.Thread(target=_pull, daemon=True).start()


def setup_vector_db(rebuild=False):
    """Initializes or rebuilds the Redis vector database."""
    global retriever, vectorstore, is_pulling_models
    logger.info(f"Setting up Redis Vector Store (rebuild={rebuild})")

    os.makedirs(DATA_DIR, exist_ok=True)
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    logger.info(f"Target Ollama URL: {ollama_base_url}")

    # Check model availability
    required_models = [config["embedding_model"], config["default_chat_model"]]
    missing_models = []
    try:
        with httpx.Client() as client:
            response = client.get(f"{ollama_base_url}/api/tags")
            if response.status_code == 200:
                available_models = [
                    m["name"] for m in response.json().get("models", [])
                ]
                for model in required_models:
                    if (
                        model not in available_models
                        and f"{model}:latest" not in available_models
                    ):
                        missing_models.append(model)
            else:
                logger.warning(
                    f"Could not check Ollama models. Status: {response.status_code}"
                )
    except Exception as e:
        logger.warning(f"Failed to connect to Ollama to check models: {e}")

    if missing_models:
        if not is_pulling_models:
            is_pulling_models = True
            pull_models_background(missing_models, ollama_base_url)

        if config["embedding_model"] in missing_models:
            logger.info(
                f"Embedding model '{config['embedding_model']}' is missing. Deferring vector store setup."
            )
            return

    embeddings = OllamaEmbeddings(
        model=config["embedding_model"], base_url=ollama_base_url
    )

    if rebuild:
        try:
            r = Redis.from_url(config["redis_url"])
            try:
                r.ft(config["index_name"]).dropindex(delete_documents=True)
                logger.info("Redis index dropped successfully")
            except Exception as e:
                logger.info(f"Index drop skipped or failed: {e}")
        except Exception as e:
            logger.error(f"Could not connect to Redis: {e}")

    loader = DirectoryLoader(
        DATA_DIR,
        glob="**/*.txt",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
    )
    
    try:
        docs = loader.load()
        logger.info(f"Loaded {len(docs)} documents from {DATA_DIR}")
    except Exception as e:
        logger.warning(f"Error loading documents: {e}")
        docs = []

    try:
        if docs:
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
            splits = text_splitter.split_documents(docs)
            logger.info(f"Split into {len(splits)} chunks")
            vectorstore = RedisVectorStore.from_documents(
                documents=splits,
                embedding=embeddings,
                redis_url=config["redis_url"],
                index_name=config["index_name"],
            )
        else:
            logger.info("No documents found. Initializing empty vector store.")
            vectorstore = RedisVectorStore(
                embeddings=embeddings,
                redis_url=config["redis_url"],
                index_name=config["index_name"],
            )
    except Exception as e:
        logger.error(f"CRITICAL: Failed to initialize RedisVectorStore: {e}")
        # We don't raise here to allow API to at least start, but chat will fail
        return

    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
    logger.info("Vector DB setup complete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_config()
    setup_vector_db()
    yield


app = FastAPI(title="SavantBot API", lifespan=lifespan)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")


# Pydantic Models
class QueryRequest(BaseModel):
    message: str
    model: Optional[str] = None


class QueryResponse(BaseModel):
    response: str
    model_used: str


class ConfigUpdate(BaseModel):
    rag_template: Optional[str] = None
    default_chat_model: Optional[str] = None


class UserUpdate(BaseModel):
    user_id: int


class TextAppendRequest(BaseModel):
    text: str
    filename: str = "messages.txt"


class ModelActionRequest(BaseModel):
    model_name: str


# API Endpoints
@app.get("/api/config", tags=["Configuration"])
async def get_config():
    return config


@app.put("/api/config", tags=["Configuration"])
async def update_config(update: ConfigUpdate):
    if update.rag_template is not None:
        config["rag_template"] = update.rag_template
    if update.default_chat_model is not None:
        config["default_chat_model"] = update.default_chat_model
    save_config()
    return config


# User Management Endpoints
@app.get("/api/auth/{user_id}", tags=["User Management"])
async def check_auth(user_id: int):
    # If list is empty, we consider it open (or you can change this to closed by default)
    is_allowed = not config["allowed_user_ids"] or user_id in config["allowed_user_ids"]
    return {"allowed": is_allowed}


@app.get("/api/users", tags=["User Management"])
async def list_users():
    return {"allowed_user_ids": config["allowed_user_ids"]}


@app.post("/api/users", tags=["User Management"])
async def add_user(user: UserUpdate):
    if user.user_id not in config["allowed_user_ids"]:
        config["allowed_user_ids"].append(user.user_id)
        save_config()
    return {
        "message": f"User {user.user_id} added",
        "users": config["allowed_user_ids"],
    }


@app.delete("/api/users/{user_id}", tags=["User Management"])
async def remove_user(user_id: int):
    if user_id in config["allowed_user_ids"]:
        config["allowed_user_ids"].remove(user_id)
        save_config()
    return {"message": f"User {user_id} removed", "users": config["allowed_user_ids"]}


# Health Endpoints
@app.get("/api/health/vectorstore", tags=["Health"])
async def vectorstore_health():
    if not vectorstore:
        return {
            "status": "uninitialized",
            "records": 0,
            "message": "Vector store not yet initialized",
        }

    try:
        r = Redis.from_url(config["redis_url"])
        info = r.ft(config["index_name"]).info()
        num_docs = int(info.get("num_docs", 0))
        return {
            "status": "ready",
            "records": num_docs,
            "index_name": config["index_name"],
            "embedding_model": config["embedding_model"],
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "records": 0}


# Ollama Management
@app.get("/api/ollama/models", tags=["Ollama Management"])
async def list_ollama_models():
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{ollama_base_url}/api/tags")
            return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ollama Error: {str(e)}")


@app.post("/api/ollama/pull", tags=["Ollama Management"])
async def pull_ollama_model(request: ModelActionRequest):
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    # We use a background thread for pulling to avoid blocking the API
    pull_models_background([request.model_name], ollama_base_url)
    return {
        "message": f"Started pulling model '{request.model_name}' in the background."
    }


@app.delete("/api/ollama/models/{model_name}", tags=["Ollama Management"])
async def delete_ollama_model(model_name: str):
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        async with httpx.AsyncClient() as client:
            # Note: Ollama expects DELETE /api/delete with a JSON body
            response = await client.request(
                "DELETE", f"{ollama_base_url}/api/delete", json={"name": model_name}
            )
            if response.status_code == 200:
                return {"message": f"Model '{model_name}' deleted successfully."}
            else:
                return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ollama Error: {str(e)}")


# Data Endpoints
@app.post("/api/data/upload", tags=["Data & Knowledge"])
async def upload_file(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".txt"):
        raise HTTPException(status_code=400, detail="Only .txt files are supported")

    # Path Traversal Prevention: Sanitize filename
    safe_filename = os.path.basename(file.filename)
    file_path = os.path.join(DATA_DIR, safe_filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    loader = TextLoader(file_path, encoding="utf-8")
    docs = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    splits = text_splitter.split_documents(docs)

    if vectorstore:
        vectorstore.add_documents(splits)
    else:
        setup_vector_db()

    return {"message": f"File {safe_filename} uploaded and indexed successfully"}


@app.post("/api/data/text", tags=["Data & Knowledge"])
async def append_text(request: TextAppendRequest):
    # Path Traversal Prevention: Sanitize filename
    safe_filename = os.path.basename(request.filename)
    file_path = os.path.join(DATA_DIR, safe_filename)

    with open(file_path, "a", encoding="utf-8") as f:
        f.write("\n" + request.text)

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    new_doc = Document(page_content=request.text, metadata={"source": safe_filename})
    splits = text_splitter.split_documents([new_doc])

    if vectorstore:
        vectorstore.add_documents(splits)
    else:
        setup_vector_db()

    return {"message": "Text appended and indexed successfully"}


@app.post("/api/data/rebuild", tags=["Data & Knowledge"])
async def rebuild_db():
    setup_vector_db(rebuild=True)
    return {"message": "Database rebuild complete"}


@app.post("/chat", response_model=QueryResponse, tags=["Chat"])
async def chat_endpoint(request: QueryRequest):
    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")

    model = request.model or config.get("default_chat_model", "qwen2.5:latest")
    prompt = ChatPromptTemplate.from_template(config["rag_template"])
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    llm = ChatOllama(model=model, base_url=ollama_base_url)

    def format_docs(docs):
        return "\n\n".join(doc.page_content for doc in docs)

    from langchain_core.runnables import Runnable

    rag_chain: Runnable = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )

    try:
        # Prompt Injection Mitigation: Wrap user input in delimiters
        # Note: This depends on the template using {question}
        # A more robust fix involves sanitizing request.message or using few-shot
        safe_message = f"<user_input>\n{request.message}\n</user_input>"

        response_text = rag_chain.invoke(safe_message)
        return QueryResponse(response=response_text, model_used=model)
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Ollama Error: {str(e)}")


def main():
    import uvicorn

    uvicorn.run("savantbot.api:app", host="0.0.0.0", port=8124, reload=True)


if __name__ == "__main__":
    main()
