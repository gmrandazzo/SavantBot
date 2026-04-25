import json
import logging
import os
import shutil
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
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


def setup_vector_db(rebuild=False):
    """Initializes or rebuilds the Redis vector database."""
    global retriever, vectorstore
    logger.info(f"Setting up Redis Vector Store (rebuild={rebuild})")

    os.makedirs(DATA_DIR, exist_ok=True)
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    logger.info(f"Connecting to Ollama at: {ollama_base_url}")
    embeddings = OllamaEmbeddings(
        model=config["embedding_model"], base_url=ollama_base_url
    )

    if rebuild:
        try:
            r = Redis.from_url(config["redis_url"])
            try:
                r.ft(config["index_name"]).dropindex(delete_documents=True)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Could not connect to Redis: {e}")

    loader = DirectoryLoader(
        DATA_DIR,
        glob="**/*.txt",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
    )
    docs = loader.load()

    if docs:
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        splits = text_splitter.split_documents(docs)
        vectorstore = RedisVectorStore.from_documents(
            documents=splits,
            embedding=embeddings,
            redis_url=config["redis_url"],
            index_name=config["index_name"],
        )
    else:
        vectorstore = RedisVectorStore(
            embeddings=embeddings,
            redis_url=config["redis_url"],
            index_name=config["index_name"],
        )

    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_config()
    setup_vector_db()
    yield


app = FastAPI(title="SavantBot API", lifespan=lifespan)


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


# API Endpoints
@app.get("/api/config")
async def get_config():
    return config


@app.put("/api/config")
async def update_config(update: ConfigUpdate):
    if update.rag_template is not None:
        config["rag_template"] = update.rag_template
    if update.default_chat_model is not None:
        config["default_chat_model"] = update.default_chat_model
    save_config()
    return config


# User Management Endpoints
@app.get("/api/auth/{user_id}")
async def check_auth(user_id: int):
    # If list is empty, we consider it open (or you can change this to closed by default)
    is_allowed = not config["allowed_user_ids"] or user_id in config["allowed_user_ids"]
    return {"allowed": is_allowed}


@app.get("/api/users")
async def list_users():
    return {"allowed_user_ids": config["allowed_user_ids"]}


@app.post("/api/users")
async def add_user(user: UserUpdate):
    if user.user_id not in config["allowed_user_ids"]:
        config["allowed_user_ids"].append(user.user_id)
        save_config()
    return {
        "message": f"User {user.user_id} added",
        "users": config["allowed_user_ids"],
    }


@app.delete("/api/users/{user_id}")
async def remove_user(user_id: int):
    if user_id in config["allowed_user_ids"]:
        config["allowed_user_ids"].remove(user_id)
        save_config()
    return {"message": f"User {user_id} removed", "users": config["allowed_user_ids"]}


# Data Endpoints
@app.post("/api/data/upload")
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


@app.post("/api/data/text")
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


@app.post("/api/data/rebuild")
async def rebuild_db():
    setup_vector_db(rebuild=True)
    return {"message": "Database rebuild complete"}


@app.post("/chat", response_model=QueryResponse)
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
