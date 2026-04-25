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

### 4. Run with Docker Compose (Recommended)
```bash
docker-compose up --build
```
> **Note for Linux users**: If Ollama is running on your host machine, you may need to set the environment variable `OLLAMA_HOST=0.0.0.0` on your host to allow the Docker container to connect to it.

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

### 📂 Data & Knowledge Management
- **`POST /api/data/upload`**: Upload a `.txt` file (Multipart/form-data). It is saved to `data/` and indexed.
- **`POST /api/data/text`**: Append a snippet of text to a file (default `messages.txt`) and index it.
    - *Payload*: `{"text": "Python is better than Java", "filename": "notes.txt"}`
- **`POST /api/data/rebuild`**: Wipes the Redis index and re-processes every file inside the `data/` folder. Use this if you manually move files into the folder.

---

## 🎓 Tutorial: Creating Your "Savant"

### Step 1: Give it Knowledge
Place any text file containing facts, chat history, or documentation into the `data/` folder, or use the `upload` endpoint.

### Step 2: Set the Persona
Use the `PUT /api/config` endpoint to tell the bot how to behave.
*Example Persona*: "You are a professional chef. Use culinary terms and keep answers concise. Context: {context} Question: {question}"

### Step 3: Authorize Yourself
If you didn't use the `.env` file, go to `/docs`, use `POST /api/users`, and enter your Telegram ID. You can find your ID by messaging [@userinfobot](https://t.me/userinfobot).

### Step 4: Chat!
Message your bot on Telegram. It will retrieve the most relevant facts from your files and respond using the persona you defined.
