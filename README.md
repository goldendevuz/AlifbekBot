# AlifbekBot

Telegram bot for transliterating Uzbek text between Cyrillic, Old Latin, and New Latin (Ö Ğ Ş Ç).
Powered by [aiogram 3](https://github.com/aiogram/aiogram), [alifbo](https://pypi.org/project/alifbo/), and [FastAPI](https://fastapi.tiangolo.com/).

---

## Architecture

- **Local Telegram Bot API (`telegram-bot-api`)**: Connects directly to Telegram via MTProto protocol without cloud rate limits, supports files up to 2000 MB, and forwards updates internally via Webhook.
- **FastAPI Webhook Server (`bot`)**: High-performance asynchronous HTTP server powered by Uvicorn and aiogram 3. Automatically registers the webhook upon startup and unregisters on shutdown.
- **SQLite Database**: Persisted in a dedicated Docker named volume (`alifbek_bot_data`).
- **Security & Efficiency**: Non-root container (`appuser`, UID 1000), CPU and memory limits, rotated JSON logs, and HTTP `/health` check.

---

## Quick Start with Docker Compose

### 1. Environment Setup

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Configure `.env`:
```env
BOT_TOKEN=your-telegram-bot-token
ADMIN_ID=557407324
DB_PATH=/data/stats.db

# Telegram App credentials (from https://my.telegram.org)
TELEGRAM_API_ID=your-api-id
TELEGRAM_API_HASH=your-api-hash
TELEGRAM_BOT_API_PORT=8083

# FastAPI Webhook configuration
PORT=8000
HOST=0.0.0.0
WEBHOOK_HOST=http://bot:8000
WEBHOOK_PATH=/webhook
WEBHOOK_SECRET=your-secret-token
```

> **Note**: `.env` is ignored by git to keep your secrets protected.

### 2. Build and Start Services

```bash
docker compose up -d --build
```

This starts two containers:
1. `alifbek_telegram_bot_api`: Local Telegram Bot API server.
2. `alifbek_bot`: FastAPI application & bot logic.

### 3. Check Status and Logs

- Service status:
  ```bash
  docker compose ps
  ```
- Bot logs:
  ```bash
  docker compose logs -f bot
  ```
- Bot API logs:
  ```bash
  docker compose logs -f telegram-bot-api
  ```
- Health check endpoint:
  ```bash
  curl http://localhost:8000/health
  ```

### 4. Admin Commands (Telegram)

- `/stats` — Total conversions, unique users (7-day and returning), and large texts count.
- `/export` — Download complete conversion events history in CSV format (no user texts stored).

### 5. Update the Bot

```bash
git pull && docker compose up -d --build
```

### 6. Stop or Restart

- Stop all services:
  ```bash
  docker compose down
  ```
- Restart bot:
  ```bash
  docker compose restart bot
  ```

---

## License & Attribution

This project is licensed under the **MIT License with Attribution** (see [`LICENSE`](LICENSE)).

You are free to use, modify, distribute, fork, and integrate this software for **any purpose** (commercial, personal, or educational), under the condition that the original author attribution and copyright notice (**Abdulmajid Yunus / [@goldendevuz](https://github.com/goldendevuz)**) are preserved and displayed in the `README.md` file of any copies, forks, or derivative works.
