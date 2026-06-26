# DeepWhale — DeepSeek Web-to-API Bridge

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker)](https://hub.docker.com/)

> **English** | [Tiếng Việt](README.vi.md)

**DeepWhale** converts [DeepSeek Chat](https://chat.deepseek.com)'s web interface into a fully **OpenAI-compatible API endpoint** with a built-in **admin dashboard** for real-time management, testing, and monitoring.

It uses browser fingerprinting via `cloakbrowser` (Playwright) to bypass Cloudflare and bot-detection, enabling reliable programmatic access to DeepSeek's models.  

**NOTE**: I have no idea why this repo of mine runs perfectly—smooth as butter—on Cline, Roo Code, Continue.dev, and similar tools, yet when I switch to CLI AI agents, it absolutely refuses to work. It can't do a damn thing—creating files, writing code, making folders—nothing works. If you know how to fix this, please feel free to leave suggestions or a solution in the "Issues" section.

---

## Features

- **OpenAI-Compatible API** — Drop-in replacement for `https://api.openai.com/v1`. Works with any OpenAI client (Cline, Roo Code, Continue.dev, OpenRouter, etc.).
- **Admin Dashboard** — Modern web UI with language switcher (English / Vietnamese), real-time logs, multi-turn chat, interactive API tester, and live server/account management.
- **Cloudflare Bypass** — Uses `cloakbrowser` with real Chromium fingerprinting. No manual cookie extraction or CAPTCHA solving.
- **Proof-of-Work Solver** — Automatically solves DeepSeek's PoW challenges using Web Workers in the browser, with a pure-Python fallback.
- **Account Rotation** — Configure multiple DeepSeek accounts; the server rotates them in round-robin, skipping failed logins automatically.
- **Auto-Recovery** — Detects expired or invalid tokens and re-authenticates transparently mid-request.
- **Streaming & Non-Streaming** — Full SSE streaming with `text/event-stream` and standard JSON responses. Supports auto-continue for long responses (up to 8 rounds).
- **Thinking/Reasoning Support** — Models like `deepseek-reasoner` emit thinking content surfaced in responses.
- **Model Aliasing** — Map any model name (`gpt-4o`, `o1`, `qwen-plus`, etc.) to a DeepSeek model.
- **Multi-Turn Chat** — Built-in chat UI with model selection and thinking mode toggle.
- **Real-Time Logs** — Live SSE-streamed logs with color-coded categories and auto-scroll.
- **CORS Enabled** — Access the API from browser-based tools and web UIs.

---

## Quick Start (Docker)

```bash
# Clone and enter the repository
git clone https://github.com/bchhngsaygez/deepwhale.git
cd deepwhale

# Create your .env file
cp .env.example .env
# Edit .env with your DeepSeek email/password

# Start with Docker Compose
docker compose up -d
```

Open `http://localhost:5001/admin/login` (default password: `admin`).

---

## Manual Setup

### Prerequisites

- Python 3.11+
- pip
- ~2 GB free disk space (for Chromium)

### Installation

```bash
pip install -r requirements.txt
```

Download the cloakbrowser Chromium build for your platform from the [CloakBrowser releases page](https://github.com/CloakHQ/cloakbrowser/releases).

### Configuration

```ini
# .env
DEEPSEEK_EMAIL=your_email@example.com
DEEPSEEK_PASSWORD=your_password
API_KEY=sk-my-secret-key-1
PORT=5001
HOST=0.0.0.0
ADMIN_PASSWORD=admin
FLASK_SECRET=your-random-secret-here
```

### Start the Server

```bash
python server.py
```

### Test via Command Line

```bash
curl http://localhost:5001/v1/models \
  -H "Authorization: Bearer sk-my-secret-key-1"

curl http://localhost:5001/v1/chat/completions \
  -H "Authorization: Bearer sk-my-secret-key-1" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

---

## API Endpoints

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/v1/models` | GET | Yes | List available models |
| `/v1/chat/completions` | POST | Yes | Chat completion (OpenAI-compatible) |
| `/chat/completions` | POST | Yes | Alias without version prefix |
| `/healthz`, `/readyz` | GET | No | Health checks |
| `/admin/login` | GET/POST | No | Admin authentication |
| `/admin/dashboard` | GET | Admin | Web dashboard |
| `/admin/api/config` | GET/POST | Admin | Server configuration |
| `/admin/api/logs` | GET | Admin | Captured logs |
| `/admin/api/logs/stream` | GET | Admin | Live log stream (SSE) |
| `/admin/api/accounts-status` | GET | Admin | Account authentication status |

---

## Admin Dashboard

The dashboard features five sections accessible from the sidebar:

| Section | Description |
|---|---|
| **Overview** | Server status, model count, account status, uptime, quick actions |
| **Chat** | Multi-turn dialogue with DeepSeek, model selection, thinking mode |
| **Testing** | Pre-built curl commands with copy buttons + interactive HTTP request builder |
| **Logs** | Real-time log viewer via SSE streaming, color-coded entries, auto-scroll |
| **Settings** | Server config (API key, port, host, admin password) and account management |

Language switching between **English** and **Vietnamese** is available in the top-right corner of the dashboard.

---

## Supported Models

| Model ID | Type | Description |
|---|---|---|
| `deepseek-v4-flash` | Default | Fast general-purpose model |
| `deepseek-v4-pro` | Expert | Higher-quality reasoning |
| `deepseek-chat` | Default | Legacy chat model |
| `deepseek-reasoner` | Expert | With thinking/reasoning output |
| `deepseek-r1` | Expert | DeepSeek R1 (thinking enabled) |
| `deepseek-v3` | Default | DeepSeek V3 |

Built-in aliases: `gpt-4o`, `gpt-4`, `gpt-3.5-turbo` → `deepseek-v4-flash`; `o3` → `deepseek-v4-pro`; `o1` → `deepseek-reasoner`; `qwen-plus`, `qwen-turbo`, etc. → `deepseek-v4-flash`.

---

## Project Structure

```
deepwhale/
├── server.py              # Flask API + admin dashboard
├── deepseek_client.py     # Browser session, login, API calls
├── pow_solver.py          # PoW challenge solver
├── utils.py               # Shared utilities (UTF-8, env loading)
├── test_client.py         # End-to-end test script
├── templates/
│   ├── login.html         # Admin login (dark theme, i18n)
│   └── dashboard.html     # Admin dashboard (i18n EN/VI)
├── Dockerfile             # Containerized deployment
├── docker-compose.yml     # Docker Compose setup
├── requirements.txt       # Python dependencies
├── .env.example           # Environment template
└── README.md              # This file
```

---

## License

[MIT](LICENSE)  

>⭐If you find this repository useful, please give it a star. Thank you for using it.⭐ 
