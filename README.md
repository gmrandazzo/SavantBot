# 🧠 SavantBot: General-Purpose RAG Bot

SavantBot is a powerful, flexible Retrieval-Augmented Generation (RAG) system. It combines a **FastAPI backend** for document processing and AI logic with a **Telegram bot frontend** for seamless interaction.

## 🚀 Key Features
- **General-Purpose RAG**: Upload any `.txt` files to give your bot specialized knowledge.
- **Dynamic Configuration**: Change the bot's "style" or "persona" in real-time via API.
- **Secure & Live Auth**: Manage allowed users via API without restarting the bot.
- **Persistent Storage**: All knowledge, users, and configurations survive restarts via `config.json` and the `data/` folder.
- **Docker Ready**: Full containerization support with Docker Compose.

---

## 🛠 Installation & Setup

### 1. Prerequisites
- **Python 3.12+**
- **Docker** (for Redis Stack)
- **Ollama** (Running locally with `qwen2.5:latest` and `bge-m3` models)

### 2. Install
```bash
pip install -e ".[dev]"
```

### 3. Set up pre-commit
To ensure code quality and consistency, install the pre-commit hooks:
```bash
pre-commit install
```
From now on, code checks (Black, Flake8, etc.) will run automatically every time you `git commit`. You can also run them manually on all files:
```bash
pre-commit run --all-files
```

### 4. Environment Configuration
Copy `.env.example` to `.env` and fill in your details:
```bash
cp .env.example .env
```
- **`TELEGRAM_TOKEN`**: Your bot token from [@BotFather](https://t.me/botfather).
- **`ALLOWED_USER_IDS`**: (Optional) A comma-separated list of IDs to "seed" the bot on its first run.
- **`OLLAMA_BASE_URL`**: (Optional) The URL of your Ollama server. Default: `http://ollama:11434`.
### 4. Run with Docker Compose (Recommended)

SavantBot supports two ways of running with Docker, depending on where your Ollama server is located.

#### Option A: Integrated Ollama (Default)
Use this to run a dedicated Ollama instance inside a Docker container.
```bash
docker-compose up --build
```
> **Note**: On the first run, SavantBot will detect if the required models are missing and pull them automatically.

#### Option B: External Ollama (Predefined)
Use this if you already have Ollama running on your host or a remote server. This version does **not** start an internal Ollama container.
```bash
docker-compose -f docker-compose.external.yml up --build
```
- **Local-Host (Mac/Win)**: Set `OLLAMA_BASE_URL=http://host.docker.internal:11434` in your `.env`.
- **Local-Host (Linux)**: Set `OLLAMA_BASE_URL=http://172.17.0.1:11434` in your `.env`.
- **Remote**: Set `OLLAMA_BASE_URL=http://your-server-ip:11434` in your `.env`.

#### Option C: Linux Host Networking (Best for Linux + Host Ollama)
If you are on Linux and Ollama is running on your host, use this mode to bypass Docker bridge networking issues.
```bash
docker-compose -f docker-compose.linux-host.yml up --build
```
- In this mode, set `OLLAMA_BASE_URL=http://localhost:11434` in your `.env`.

#### Option D: Remote or Manual Configuration (Legacy Approach)
You can also use the default `docker-compose.yml` but start only specific services:
```bash
docker-compose up redis api bot
```

### 👥 Running Multiple Instances
You can run multiple independent bots on the same machine by using **Docker Project Names** and unique ports.

1.  **Create separate env files**: (e.g., `.env.bot1` and `.env.bot2`) with different `TELEGRAM_TOKEN`s.
2.  **Launch Instance 1**:
    ```bash
    export ENV_FILE=.env.bot1
    export API_PORT=8125
    export DATA_VOLUME=./data_bot1
    docker-compose -p bot1 up -d --build
    ```
3.  **Launch Instance 2**:
    ```bash
    # You can set variables in terminal OR directly in .env.bot2
    export ENV_FILE=.env.bot2
    export DATA_VOLUME=./data_bot2
    docker-compose -p bot2 up -d --build
    ```

**Pro Tip**: Instead of using `export` in your terminal, you can simply add these variables directly into your custom `.env` file (e.g., `.env.bot2`) for a cleaner setup:
```env
# Inside .env.bot2
TELEGRAM_TOKEN=...
API_PORT=8126
DATA_VOLUME=./data_bot2
REDIS_PORT=6391
REDIS_UI_PORT=8004
REDIS_URL=redis://redis:6379
```

#### 🧠 Managing the AI Engine (Ollama)
When running multiple instances, you have two choices for the AI engine:

*   **Isolated AI (Safe but Heavy)**: Each bot gets its own Ollama container. This uses more RAM but keeps bots totally separate. To do this, ensure each bot has a unique `OLLAMA_PORT` (e.g., `11434`, `11435`).
*   **Shared AI (Recommended)**: Multiple bots connect to a single Ollama instance. This saves massive amounts of RAM as the model is only loaded once. To do this:
    1. Start Bot 1 normally.
    2. For Bot 2+, set `OLLAMA_BASE_URL=http://host.docker.internal:11434` in your `.env` and launch without the ollama service:
       `docker-compose -p bot2 up -d redis api bot`

---

## 🚦 Understanding Authentication (The "Bootstrap" Logic)
...
4. **Whitelisted Mode**: As soon as **one or more IDs** are added, the bot becomes "Private," and only those IDs can interact with it.

---

## ⚙️ Configuration File (`config.json`)

SavantBot uses a `config.json` file for persistent settings. If it doesn't exist, it is created automatically on the first run.

| Field | Description |
| :--- | :--- |
| `rag_template` | The prompt used by the AI. Must include `{context}` and `{question}` placeholders. |
| `embedding_model` | The Ollama model used to turn text into vectors (default: `bge-m3`). |
| `default_chat_model` | The default Ollama model for generating responses (default: `qwen2.5:latest`). |
| `redis_url` | The connection string for the Redis Vector Database. |
| `index_name` | The internal name of the search index inside Redis. |
| `allowed_user_ids` | A JSON list of numeric Telegram User IDs authorized to use the bot. |

---

## 📖 API Documentation & Endpoints

Once running, access the interactive documentation at: `http://localhost:8124/docs`

### ⚙️ Configuration
- **`GET /api/config`**: Returns the entire current configuration (template, models, user list).
- **`PUT /api/config`**: Update the RAG persona or default model.
    - *Payload*: `{"rag_template": "...", "default_chat_model": "..."}`

### 👥 User Management (Live Updates)
*No bot restart required! Changes take effect instantly.*
- **`GET /api/users`**: Returns the list of all authorized User IDs.
- **`POST /api/users`**: Add a new user to the whitelist.
    - *Payload*: `{"user_id": 12345678}`
- **`DELETE /api/users/{user_id}`**: Revoke a user's access immediately.
- **`GET /api/auth/{user_id}`**: Used by the bot to check if a specific ID is allowed.

### 🦙 Ollama Management
- **`GET /api/ollama/models`**: List all models currently available in Ollama.
- **`POST /api/ollama/pull`**: Download a new model to Ollama in the background.
    - *Payload*: `{"model_name": "llama3"}`
- **`DELETE /api/ollama/models/{model_name}`**: Remove a model from Ollama.

### 🏥 Health & Monitoring
- **`GET /api/health/vectorstore`**: Check the status of the Redis vector index and see the number of indexed records.

### 📂 Data & Knowledge Management
- **`POST /api/data/upload`**: Upload a `.txt` or `.pdf` file (Multipart/form-data). It is saved to `data/` and indexed.
- **`POST /api/data/text`**: Append a snippet of text to a file (default `messages.txt`) and index it.
    - *Payload*: `{"text": "Python is better than Java", "filename": "notes.txt"}`
- **`POST /api/data/rebuild`**: Wipes the Redis index and re-processes every file (`.txt` and `.pdf`) inside the `data/` folder. Use this if you manually move files into the folder.

---

## 🎓 Tutorial: Creating Your "Savant"

### Step 1: Give it Knowledge
Place any `.txt` or `.pdf` file containing facts, chat history, or documentation into the `data/` folder, or use the `upload` endpoint.

### Step 2: Set the Persona
Use the `PUT /api/config` endpoint to tell the bot how to behave.
*Example Persona*: "You are a professional chef. Use culinary terms and keep answers concise. Context: {context} Question: {question}"

### Step 3: Authorize Yourself
If you didn't use the `.env` file, go to `/docs`, use `POST /api/users`, and enter your Telegram ID. You can find your ID by messaging [@userinfobot](https://t.me/userinfobot).

### Step 4: Chat!
Message your bot on Telegram. It will retrieve the most relevant facts from your files and respond using the persona you defined.
