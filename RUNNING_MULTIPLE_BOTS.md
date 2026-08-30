# Running Multiple SavantBot Instances with One Shared Ollama

This tutorial shows how to run two independent SavantBot instances — for example, **PippoBot** and **PlutoBot** — on the same machine while sharing a single Ollama server.

Sharing Ollama saves a lot of RAM because each model is loaded only once, even when several bots use it.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Host Machine                        │
│                                                             │
│   ┌─────────────┐      ┌──────────────────────────────┐    │
│   │   Ollama    │◄─────│  PippoBot API  (port 8126)   │    │
│   │  :11434     │      │  + Telegram Bot              │    │
│   └─────────────┘      └──────────────────────────────┘    │
│           ▲                      Redis (port 6392)          │
│           │                                                  │
│           └────────┐  ┌──────────────────────────────┐      │
│                    └──│  PlutoBot API  (port 8127)   │      │
│                       │  + Telegram Bot              │      │
│                       └──────────────────────────────┘      │
│                                  Redis (port 6393)          │
└─────────────────────────────────────────────────────────────┘
```

Each bot gets its own:

- Telegram token
- API port
- Redis port and Redis UI port
- Data directory (for `config.json`, uploaded files, and persistence)
- `config.json` persona / model settings

They all connect to the **same Ollama instance** at your host IP or `host.docker.internal`.

---

## Prerequisites

1. Docker and Docker Compose installed.
2. Ollama running and accessible on your network, e.g.:
   ```bash
   OLLAMA_HOST=0.0.0.0 ollama serve
   ```
   Make sure the required models are already pulled, for example:
   ```bash
   ollama pull qwen2.5:latest
   ollama pull qwen3-embedding:4b
   ```
3. Two Telegram bot tokens from [@BotFather](https://t.me/botfather).
4. Your host machine's local IP address, e.g. `192.168.1.50`.

> **Tip:** On Linux, use your real LAN IP. On macOS/Windows you can often use `host.docker.internal`, but for cross-bot reliability a real IP is recommended.

---

## Step 1: Create the Environment Files

Create one `.env` file per bot.

### `.env.pippobot`

```env
# Telegram Bot Token (from @BotFather)
TELEGRAM_TOKEN=1111111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA

# API authentication token (generate a strong random value)
API_TOKEN=pippo_secure_random_token_123

# Ports on the host machine (must be unique per bot)
API_PORT=8126
REDIS_PORT=6392
REDIS_UI_PORT=8004

# URLs inside Docker
# API_URL is what the bot container uses to reach the API container.
API_URL=http://api:8124/chat

# Shared Ollama instance
# Use your host IP because the bot and API containers must reach Ollama externally.
OLLAMA_BASE_URL=http://192.168.1.50:11434

# Redis connection string inside Docker
REDIS_URL=redis://redis:6379

# Separate data directory so the two bots do not share files
DATA_VOLUME=./data_pippobot

# Comma-separated list of Telegram User IDs allowed to use PippoBot
ALLOWED_USER_IDS=12345678
```

### `.env.plutobot`

```env
# Telegram Bot Token (from @BotFather)
TELEGRAM_TOKEN=2222222222:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB

# API authentication token (must differ from PippoBot)
API_TOKEN=pluto_secure_random_token_456

# Different ports so PippoBot and PlutoBot do not collide
API_PORT=8127
REDIS_PORT=6393
REDIS_UI_PORT=8005

API_URL=http://api:8124/chat

# Same shared Ollama instance
OLLAMA_BASE_URL=http://192.168.1.50:11434

REDIS_URL=redis://redis:6379

DATA_VOLUME=./data_plutobot

# Different whitelist for PlutoBot
ALLOWED_USER_IDS=87654321
```

> **Important:** `API_PORT`, `REDIS_PORT`, and `REDIS_UI_PORT` must be unique across bots. `TELEGRAM_TOKEN` and `API_TOKEN` must also differ.

---

## Step 2: Create Separate Config Files

Each bot can have its own persona, embedding model, and chat model. Place them next to the data directory so they become `data_pippobot/config.json` and `data_plutobot/config.json` after the first run.

Alternatively, create them manually before starting.

### `data_pippobot/config.json`

```json
{
  "rag_template": "You are PippoBot, a friendly coding assistant.\n\nContext:\n{context}\n\nUser Question: {question}\nAnswer:",
  "embedding_model": "qwen3-embedding:4b",
  "default_chat_model": "qwen2.5:latest",
  "top_k": 10,
  "redis_url": "redis://redis:6379",
  "index_name": "pippobot-embeddings",
  "allowed_user_ids": [12345678]
}
```

### `data_plutobot/config.json`

```json
{
  "rag_template": "You are PlutoBot, a sarcastic movie expert.\n\nContext:\n{context}\n\nUser Question: {question}\nAnswer:",
  "embedding_model": "qwen3-embedding:4b",
  "default_chat_model": "qwen2.5:latest",
  "top_k": 10,
  "redis_url": "redis://redis:6379",
  "index_name": "plutobot-embeddings",
  "allowed_user_ids": [87654321]
}
```

> **Note:** `index_name` should differ per bot. If both bots use the same `index_name` inside the same Redis server, their knowledge will mix together.

---

## Step 3: Create Launch Scripts

### `run.pippobot.sh`

```bash
#!/bin/bash
set -e

export ENV_FILE=.env.pippobot

docker compose \
  -p pippobot \
  -f docker-compose.external.yml \
  --env-file .env.pippobot \
  up --build -d
```

### `run.plutobot.sh`

```bash
#!/bin/bash
set -e

export ENV_FILE=.env.plutobot

docker compose \
  -p plutobot \
  -f docker-compose.external.yml \
  --env-file .env.plutobot \
  up --build -d
```

Make them executable:

```bash
chmod +x run.pippobot.sh run.plutobot.sh
```

> We use `docker-compose.external.yml` because it does **not** start an internal Ollama container. Both bots will instead connect to the shared Ollama on the host.

---

## Step 4: Start the Shared Ollama Instance

On the host:

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

Verify it is reachable from another machine or container:

```bash
curl http://192.168.1.50:11434/api/tags
```

Pull the models both bots will use:

```bash
ollama pull qwen2.5:latest
ollama pull qwen3-embedding:4b
```

---

## Step 5: Launch the Bots

Start PippoBot:

```bash
./run.pippobot.sh
```

Start PlutoBot:

```bash
./run.plutobot.sh
```

Each bot runs in its own Docker project (`-p pippobot`, `-p plutobot`) with isolated Redis and data volumes, but both connect to the same Ollama server.

---

## Step 6: Verify Everything

Check that both API containers are listening on the host ports:

```bash
curl http://localhost:8126/api/health/vectorstore
curl http://localhost:8127/api/health/vectorstore
```

Check running containers:

```bash
docker ps
```

You should see containers named like:

```
pippobot-api-1
pippobot-redis-1
pippobot-bot-1
plutobot-api-1
plutobot-redis-1
plutobot-bot-1
```

Send `/start` to each Telegram bot. If you get a whitelist error, add your Telegram user ID to the correct `.env` file and restart:

```bash
docker compose -p pippobot -f docker-compose.external.yml --env-file .env.pippobot up -d
```

---

## Step 7: Add Knowledge

Upload documents via the API docs:

- PippoBot: `http://localhost:8126/docs`
- PlutoBot: `http://localhost:8127/docs`

Or drop `.txt`/`.pdf` files into:

```
data_pippobot/
data_plutobot/
```

Then call `POST /api/data/rebuild` from the docs for the relevant bot.

---

## Stopping a Bot

To stop PippoBot without affecting PlutoBot:

```bash
docker compose -p pippobot -f docker-compose.external.yml --env-file .env.pippobot down
```

To stop PlutoBot:

```bash
docker compose -p plutobot -f docker-compose.external.yml --env-file .env.plutobot down
```

To stop everything:

```bash
docker compose -p pippobot -f docker-compose.external.yml --env-file .env.pippobot down
docker compose -p plutobot -f docker-compose.external.yml --env-file .env.plutobot down
```

---

## Troubleshooting

### "Unauthorized" on Telegram

The bot container cannot reach the API container, or your Telegram user ID is not whitelisted. Check the bot logs:

```bash
docker logs pippobot-bot-1
```

### Ollama connection errors

Make sure `OLLAMA_BASE_URL` in each `.env` file points to an address reachable from inside the Docker containers. `localhost` inside a container refers to the container itself, not the host. Use the host LAN IP (`192.168.1.50:11434`) or ensure Ollama is bound to `0.0.0.0`.

### Port already in use

If Docker complains about a port, one of `API_PORT`, `REDIS_PORT`, or `REDIS_UI_PORT` is already taken. Change it in the corresponding `.env` file and restart.

### Redis indexes mixed up

Ensure each bot has a unique `index_name` in its `config.json`. Using the same `index_name` across bots causes them to share the same vector data inside Redis.

---

## Summary Checklist

- [ ] Ollama running on the host with `OLLAMA_HOST=0.0.0.0`
- [ ] Models pulled in Ollama
- [ ] `.env.pippobot` and `.env.plutobot` created with unique ports/tokens
- [ ] `data_pippobot/config.json` and `data_plutobot/config.json` created with unique `index_name`
- [ ] `run.pippobot.sh` and `run.plutobot.sh` created and made executable
- [ ] Both bots launched with `docker-compose.external.yml`
- [ ] Health endpoints respond
- [ ] Telegram `/start` works for both bots
