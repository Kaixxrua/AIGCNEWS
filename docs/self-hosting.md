# Self-Hosting Guide

> **English** | [简体中文](self-hosting.zh-CN.md)

Full setup, operations, and verification for running AIGCNEWS on Linux / WSL2. The [README](../README.md) carries the fast path; this guide carries the details.

## Prerequisites

| Tool | Version | Notes |
| --- | --- | --- |
| Python | 3.12 | Backend runtime (image pinned by digest to `python:3.12-slim`) |
| Node.js | 22 | Frontend build and tests (matches CI) |
| Docker + Compose | v2 | Infrastructure and production stack orchestration |

## 1) Prepare environment variables

```bash
cp .env.example .env
```

Edit `.env` with your local parameters. **`JWT_SECRET_KEY` must be set to a strong random value** — the application refuses to start if it is missing, equal to the example value, or shorter than 32 characters (see [adr/0001](adr/0001-jwt-secret-rotation-and-startup-guard.md)):

```bash
openssl rand -hex 32
```

## 2) Install dependencies

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd frontend && npm ci && cd ..
```

`requirements-dev.txt` adds pytest / pytest-cov / ruff on top of the locked `requirements.lock`, sharing the same dependency baseline as CI.

## 3) Prepare frontend TLS certificates (self-signed is fine)

The `frontend-web` nginx mounts `frontend/ssl/` as a read-only volume (gitignored; absent on a clean checkout) and fails to start without certificates. For local deployment, generate a self-signed certificate:

```bash
mkdir -p frontend/ssl
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout frontend/ssl/aigcnews.cn.key \
  -out frontend/ssl/aigcnews.cn_bundle.crt \
  -days 3650 -subj "/CN=aigcnews.cn"
# The hardened frontend-web container (cap_drop: ALL) requires the private key to be owned by root
sudo chown root:root frontend/ssl/*.key && sudo chmod 600 frontend/ssl/*.key
```

## 4) Start the core stack

```bash
scripts/manage_main_stack.sh up
```

This reconciles the core Compose stack (backend API, frontend, PostgreSQL, Redis, Milvus, MinIO, etc.) and waits for all health checks to pass — **a clean checkout runs as-is**. Common subcommands: `config` (validates the orchestration without printing secrets), `status`, `logs`.

> Private deployment extensions (sister services, external orchestration networks, private nginx servers, etc.) are not shipped with the repository; they are injected as an overlay: when the script detects `../aigcnews_private/deploy/docker-compose.private.yml` (overridable via `AIGCNEWS_PRIVATE_COMPOSE`), it is merged in automatically; when absent, the core stack works standalone. See the header comments in `docker/docker-compose.yml` for the mechanism.

## 5) Local development (hot reload outside containers)

```bash
# Backend (reads API_HOST / API_PORT from settings, default 8000)
backend/.venv/bin/python run_server.py

# Frontend (Vite dev server, default 5173)
cd frontend && npm run dev
```

## 6) Default admin & SMTP configuration

**Administrator bootstrap is disabled by default.** To initialize an empty installation without SMTP, explicitly configure an owner-controlled password before starting the backend:

- Generate a fresh password with `openssl rand -hex 32` and set `DEFAULT_ADMIN_PASSWORD` in your private environment file. Use a different secret from `JWT_SECRET_KEY`.
- Set `DEFAULT_ADMIN_EMAIL` to your administrator address (default `admin@aigcnews.internal`). Leaving either setting blank disables the seed; the historical public password `admin123456` is refused for new bootstrap accounts.
- The seed runs once and only on an empty database: existing deployments (non-empty users table) are never touched, and a seed failure does not block startup (logged as critical).

After bootstrap, sign in with the configured credentials and change the password using the banner or dock key button; this **does not depend on SMTP**. Remove the bootstrap password from the environment file once setup is complete. Upgrading does not rotate existing accounts: installations still using the historical public credentials must change that password immediately. The warning for those credentials remains active even when the bootstrap password setting is empty.

Registering additional users and password recovery still require email OTPs, so configuring SMTP early is still recommended. Pick one:

- Configure `SMTP_*` in `.env` (see the SMTP block in `.env.example`); or
- Leave `SMTP_HOST` empty for dev mode, which prints verification codes to the backend console logs.

Once an admin logs in, the **Monitor → SMTP email delivery** panel manages the configuration online: it is stored in the database, takes effect immediately (background jobs pick it up within 60 seconds), and **takes precedence over environment variables**; "Send test email" delivers a real message to the current admin's login email using the latest saved configuration. Saving with an empty host deletes the database configuration and reverts to the environment variables.

## Ports & health checks

| Address | Purpose |
| --- | --- |
| `http://localhost` (80/443) | Frontend site (production domain certificates live in `frontend/ssl/`; keys must be `root:root` mode 600) |
| `http://localhost:5173` | Vite dev server |
| `http://127.0.0.1:8000` | Backend API (loopback-only binding; `/api/live`, `/api/ready` health checks) |
| `http://localhost:8000/api/mcp` | Local MCP endpoint |

Infrastructure (PostgreSQL / Redis / Milvus / MinIO / Attu) is only exposed inside the orchestration network and publishes no ports to the host; the backend reaches it by service name. For ad-hoc host-side debugging use `docker exec <container> ...`; operational details are in [linux-server-boot.md](linux-server-boot.md).

## Testing

```bash
# Full backend suite (must run from the repository root, same as CI)
backend/.venv/bin/python -m pytest backend/tests -q

# Backend lint
backend/.venv/bin/python -m ruff check backend/app backend/tests --config backend/pyproject.toml

# Frontend: unit tests, type check, lint, build
cd frontend
npm run test:unit
npm run typecheck
npm run lint
npm run build

# Orchestration validation
docker compose -f docker/docker-compose.yml config --quiet
```

Commit messages follow Conventional Commits (`<type>(<scope>): <subject>`, scope required); details in [git-workflow.md](git-workflow.md).
