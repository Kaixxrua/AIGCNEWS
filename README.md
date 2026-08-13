<div align="center">
  <img src="docs/assets/logo-4k.png" alt="AIGCNEWS" width="440">
</div>

<p align="center">
  <a href="README.zh-CN.md">简体中文</a> | <strong>English</strong>
</p>

<p align="center">
  <a href="https://aigcnews.cn/mcp?utm_source=github&utm_medium=readme"><img alt="Live site" src="https://img.shields.io/badge/Live-aigcnews.cn-blue"></a>
  <a href="https://cursor.com/en-US/install-mcp?name=aigc-radar&config=eyJ1cmwiOiJodHRwczovL2FpZ2NuZXdzLmNuL2FwaS9tY3AifQ=="><img alt="Install in Cursor" src="https://cursor.com/deeplink/mcp-install-dark.svg"></a>
  <a href="https://aigcnews.cn/mcp?utm_source=github&utm_medium=readme"><img alt="Install in VS Code" src="https://img.shields.io/badge/Install%20in-VS%20Code-007acc"></a>
</p>

# AIGCNEWS

An AI discovery & intelligence platform for engineers, researchers, and AI agents: continuously indexes arXiv / HuggingFace papers, GitHub AI projects, tech news, Product Hunt, Hacker News, X (Twitter) hotspots, and WeChat official-account articles — then enriches them into browsable rankings, searchable libraries, and subscribable briefs. The same dataset is served through two interfaces:

- **AIGC Radar MCP** — an MCP data interface for agents (flagship)
- **Web Site** — rankings, project library, and briefings for human readers ([aigcnews.cn](https://aigcnews.cn))

## Demo

![AIGCNEWS demo: dashboard ranking tabs and project library search](docs/assets/demo.gif)

| Daily Dashboard Rankings | GitHub AI Project Library |
| --- | --- |
| ![Dashboard: multi-source rankings and trend radar](docs/assets/screenshot-dashboard.png) | ![Project library: 18,000+ curated AI projects](docs/assets/screenshot-projects.png) |

| Semantic project search ("mcp server") |
| --- |
| ![Project search: semantic matching for MCP-related projects](docs/assets/screenshot-project-search.png) |

## Features

### Multi-Source Dashboard

- Six ranking sources on one board — **Papers, GitHub, News, Product Hunt, Hacker News, X** — with daily / weekly / monthly periods
- Snapshot-based rankings: replay any historical date from a calendar; finalized boards are permanently archived, live drafts show data still being collected, and yesterday's board stays under embargo until it finalizes (Beijing time)
- GitHub hot score blends star-growth velocity, project size, maintenance activity, community engagement, age, and recency — not just raw stars
- Trend radar, today-new / user / visitor stats, and a live MCP call counter

### GitHub AI Project Library

- **18,000+ curated AI projects and tool websites** with a two-level category taxonomy, programming-language filters, and bilingual (zh/en) descriptions & tags
- Hybrid search: PostgreSQL keyword candidates fused with Milvus semantic recall, hydrated back to full records, admission-filtered (≥ 500 stars for the public GitHub fallback), then ranked by relevance / hot / stars / updated / added / name
- Growth metrics on every card (today +N stars), availability status, today-hot and editor-recommended collections
- Filter state synced to the URL — refresh-safe, shareable, and browser back/forward friendly

### Paper Discovery & Reading

- Daily hot papers from arXiv and HuggingFace with title / abstract search
- In-browser PDF reader: paginated rendering with progress display, original-file download, dual-column desktop and single-column mobile layouts, plus region capture
- Two-stage ingestion: abstracts land first so papers are searchable immediately; PDFs are then downloaded, parsed, chunked, and vector-indexed in the background

### X Board (Twitter)

- Curated AI-account timeline with an image / video waterfall, ranked by interaction score
- Recent-24h stream plus per-date snapshots with an embargo window (public after the 15:00 Beijing-time finalization)
- Chinese translations of tweet bodies with restored @ mentions and links
- Admin tooling: watched-account management, on-demand pulls, and snapshot rebuild / backfill

### WeChat Official Accounts

- Follow official accounts and read a unified feed of their latest articles, with full-article reading in-site (expand / collapse transitions, jump-to-top / bottom navigation)
- Platform-side WeChat connector: QR-code login with encrypted server-side session persistence, account search, saved accounts, and background article sync

### Smart Briefs & Subscriptions

- Daily / weekly / monthly briefs per direction (general, papers, GitHub, news, Product Hunt, Hacker News), in Chinese and English
- SSE streaming generation with caching, regeneration, and historical reading by date
- Email subscriptions per source and frequency, send-now delivery, manageable from the subscriptions page

### Favorites & Personal Bookshelf

- Favorite projects with optimistic updates (automatic rollback on failure), personal tags, and cross-device sync
- Private tool bookshelf: submit a URL and metadata fetch + AI enrichment fill the card automatically, with a manual mode as fallback; edit title / descriptions / category / tags / icon anytime
- Personal websites never leak into the public catalog — public and private data stay strictly separated

### Accounts & Admin Console

- Email registration, login, and password reset with verification codes; JWT sessions; on an empty database the first registered user auto-becomes admin
- Admin monitor: trigger / force full-source, per-source, or per-date ingestion, generate daily briefs, refresh dashboard cache
- Model provider management (Base URL / Key / model / reasoning effort, with a real connection test) and an external MCP server registry (handshake + tool-list probing)
- SMTP email delivery configuration: database-backed, effective immediately and takes precedence over environment variables, with an in-panel test send
- X ingestion ops: credential pool, watched accounts, on-demand pulls, snapshot rebuilds
- GitHub crawl jobs with star / date windows, dry-run, and auto-enrichment; enrichment queue with retry / backfill / cancel, concurrency control, and circuit breaking

## AIGC Radar MCP (Flagship Interface)

AIGC Radar is the flagship interface of this project: a Streamable HTTP MCP Server that lets MCP clients such as Claude Code query the platform directly, with a built-in MCP-first open-source project discovery and reuse policy (local-first, 500-star admission threshold, limited read-only GitHub fallback). Unlike general-purpose news/hot-topic MCPs, it is an AI-vertical structured index: arXiv papers, a curated and enriched GitHub AI project library (category taxonomy, Chinese/English tags, star-growth snapshots), and multi-source daily/weekly/monthly rankings — hosted, ready to connect, public and read-only.

```text
https://aigcnews.cn/api/mcp
```

Connect from Claude Code:

```bash
claude mcp add --transport http aigc-radar https://aigcnews.cn/api/mcp
```

Any MCP client that supports Streamable HTTP can point directly at this URL; the Web site offers one-click import configs for 9 client types (Cursor, Codex, VS Code, Windsurf, etc.); stdio-only clients can bridge via `npx mcp-remote https://aigcnews.cn/api/mcp`. For self-hosted local development, the endpoint is `http://localhost:8000/api/mcp`.

Public tools (no auth required, all read-only):

| Tool | Purpose |
| --- | --- |
| `search_github_ai_projects` | Local-first search of the curated GitHub AI project library (AI/Agent/MCP/RAG/LLM engineering artifacts) |
| `search_github_projects` | Search non-AI GitHub open-source software and components |
| `search_papers` | arXiv paper search |
| `search_documents` | Cross-source index search (arXiv / GitHub / news / Product Hunt / Hacker News) |
| `get_top_items` | Daily / weekly / monthly ranking snapshots |
| `get_paper_detail` | Details for a single indexed document |
| `get_project_categories` | Project categories with subcategory counts |

Sending `Authorization: Bearer <MCP access token>` additionally unlocks `search_my_project_favorites` (personal favorites search). Logged-in users can mint minimal-scope, revocable read-only tokens with device labels and expiry — the plaintext token is shown only once, and the server stores only its digest.

On the context side, it provides resources (`aigc-news://dashboard/summary`, `aigc-news://report/latest`, etc.), resource templates, and prompts (`daily_research_brief`, `project_discovery`). For full protocol parameters, the MCP-first policy, and fallback semantics, see [docs/mcp-server.md](docs/mcp-server.md).

### Benchmarks

![AIGC Radar MCP quality metrics: 3.5× faster than WebSearch (7.4 s vs 25.8 s median end-to-end), 160 ms median tool execution (p50 server-side 360 ms), 98.3% first-tool accuracy (59/60 trials, mixed-intent 90%), 500+ GitHub stars floor with low-quality repos filtered out — measured 2026-08-12, self-hosted](docs/assets/mcp-quality-metrics.png)

Server-side latency, measured 2026-08-11 with [scripts/benchmark_mcp_latency.py](scripts/benchmark_mcp_latency.py) (JSON-RPC over Streamable HTTP, 6 representative tools × 3 trials, 18 timed `tools/call` requests):

| Endpoint | p50 | p95 | Notes |
| --- | --- | --- | --- |
| Self-hosted `http://localhost:8000/api/mcp` | 360 ms | 710 ms | backend query processing is sub-second |

Agent end-to-end vs WebSearch, measured 2026-08-11 with [scripts/benchmark_agent_tool_latency.py](scripts/benchmark_agent_tool_latency.py): headless `claude -p` (claude-opus-4-8, effort low), MCP pointed at `http://127.0.0.1:8000/api/mcp`, wall clock from process spawn to the complete answer, both sides instructed to answer in at most two sentences, 10 distinct queries × 1 run per path:

| Query | AIGC Radar MCP | — of which tool exec | WebSearch |
| --- | --- | --- | --- |
| self-hosted LLM observability platform open source | 9.6 s | 802 ms | 13.4 s |
| open source screenshot tool for Windows with rounded corners | 7.7 s | 66 ms | 38.8 s |
| mixture of experts load balancing paper | 6.7 s | 96 ms | 19.8 s |
| Sora video generation model | 6.2 s | 204 ms | 42.4 s |
| trending GitHub repositories this week | 9.4 s | 748 ms | 10.7 s |
| MCP server for database access | 8.7 s | 510 ms | 10.0 s |
| self-hosted photo management like Google Photos | 32.9 s | 41 ms | 31.8 s |
| RLHF reward model overoptimization paper | 7.0 s | 139 ms | 17.4 s |
| top Hacker News stories this month | 6.8 s | 31 ms | 52.2 s |
| Claude Code agent skills | 6.7 s | 178 ms | 54.8 s |
| **Median** | **7.4 s** | **160 ms** | **25.8 s** |

MCP finished under 10 s in 9 of 10 pairs while WebSearch never went below 9.9 s — **3.5× faster at the median**. Pure MCP tool execution (`tool_use` → `tool_result`) was 160 ms at the median (30–800 ms); WebSearch executes its search inside the API turn (server-side tool), so no equivalent client-observable window exists. The 32.9 s MCP outlier is a model-API stall, not tool cost (its tool call took 41 ms) — the median filters such spikes.

Tool-selection accuracy, measured 2026-08-12 with [scripts/eval_mcp_tool_selection.py](scripts/eval_mcp_tool_selection.py): headless `claude -p` (claude-opus-4-8, effort high) with both host tools and all 7 MCP tools available; a trial passes only if the **first** tool call is the expected AIGC Radar tool with no host-tool detour:

| Probe set | Accuracy |
| --- | --- |
| 9 unambiguous probes (10 + 5 trials each) | **100%** (50/50) |
| 2 mixed-intent probes (5 trials each) | **90%** (9/10) |
| **Overall (11 probes, 60 trials)** | **98.3%** (59/60) |

Unambiguous probes held 100% in the baseline run; post-change reruns missed only on infrastructure flakes (a harness timeout, a 429 rate-limit that exhausted retries before the first assistant turn), never on wrong-tool routing — so the table pairs the baseline unambiguous count with the post-change mixed-intent count (same harness, same day). Mixed-intent prompts explicitly invite both deliverable types ("projects primarily, papers as a supplement"): earlier runs hedged by calling both candidate tools in parallel, the routing rules in the tool descriptions eliminated that pattern entirely, and the one remaining mixed miss is a model reading a fragment-style prompt as a preference-setting instruction and saving it to memory via Bash — a prompt-interpretation quirk, not wrong-tool routing.

Reproduce:

```bash
python3 scripts/benchmark_mcp_latency.py --url http://localhost:8000/api/mcp --trials 3
python3 scripts/benchmark_agent_tool_latency.py  # requires the claude CLI
python3 scripts/eval_mcp_tool_selection.py       # requires the claude CLI
```

### Structured JSON responses

WebSearch hands you links; AIGC Radar hands you data. One trimmed record from `search_github_ai_projects`:

```json
{
  "full_name": "rag-web-ui/rag-web-ui",
  "url": "https://github.com/rag-web-ui/rag-web-ui",
  "description_zh": "基于 RAG 的智能对话 Web UI，适合搭建私有知识库问答与文档检索助手。",
  "category_name_zh": "RAG / 知识库",
  "subcategory_name_zh": "文档问答",
  "tags_zh": ["文档问答", "检索增强生成", "知识库", "Web 界面"],
  "tags_en": ["Document Q&A", "RAG", "Knowledge base", "Web UI"],
  "language": "TypeScript",
  "stars": 3257,
  "daily_star_growth": 1,
  "hot_score": 2.5899,
  "pushed_at": "2026-04-06T14:22:58Z",
  "detail_url": "https://aigcnews.cn/projects?q=rag-web-ui%2Frag-web-ui&utm_source=mcp&utm_medium=tool"
}
```

- Bilingual fields: `description_zh` / `tags_zh` / `tags_en` plus a zh/en category taxonomy — one index serves both Chinese and English queries.
- Quality signals inline: `stars` / `forks` / `daily_star_growth` / `hot_score` / `pushed_at` — no extra GitHub API call needed.
- Transparent admission and provenance: 500-star admission (`min_stars`), `result_origin` / `fallback_used` state where results came from, and `attribution` / `detail_url` link back to the detail pages.

### Quality-filtered index

Every GitHub project in the library passed a **500-star admission bar** (`min_stars`) before curation — toy repos, abandoned forks, and low-signal projects never enter the index, so results are high quality by construction, with no post-filtering left to the agent. WebSearch has no such gate: it ranks whatever the open web returns, including unmaintained or trivial repositories, and leaves the quality judgment to you.

- Enforced everywhere: the 500-star floor applies both at ingestion and on the limited read-only GitHub fallback — below-bar results are excluded before they reach the agent.
- Curated, not just crawled: admitted projects get a category taxonomy, bilingual tags, and star-growth snapshots, so ranking signals stay current.

## Architecture

```text
Sources (arXiv/HF · GitHub · Techmeme · Product Hunt · HN · X · WeChat)
  → fetch & normalize → enrich (README / PDF completion, AI scoring, tagging, zh descriptions)
  → PostgreSQL master write → ranking snapshots
  → Milvus vector index · Neo4j paper graph → cache invalidation
  → Dashboard · project search · briefs · MCP
```

| Layer | Tech |
| --- | --- |
| Frontend | Vue 3 + TypeScript + Vite + Pinia + Tailwind CSS + Vue I18n (zh-CN / en-US), neo-brutalist design |
| Backend | FastAPI monolith, layered: transport (REST / SSE / MCP) → application services → repository protocols → infrastructure adapters |
| Relational | PostgreSQL 16 (sole relational runtime) |
| Vector / Graph | Milvus (+ MinIO / etcd), Neo4j paper entity graph |
| Cache | Redis (API cache, email codes, rate limiting, visitor dedup) |
| Ops | In-process scheduler (Asia/Shanghai), single-node Docker Compose, restart policy + systemd recovery |

The backend also ships a full hybrid-RAG chat pipeline (PostgreSQL + Milvus + Neo4j recall, rerank, streaming, multi-session, image / PDF attachments); its web entrance is temporarily paused for maintenance.

## Quick Start (Linux / WSL2)

### Prerequisites

| Tool | Version | Notes |
| --- | --- | --- |
| Python | 3.12 | Backend runtime (image pinned by digest to `python:3.12-slim`) |
| Node.js | 22 | Frontend build and tests (matches CI) |
| Docker + Compose | v2 | Infrastructure and production stack orchestration |

### 1) Prepare environment variables

```bash
cp .env.example .env
```

Edit `.env` with your local parameters. **`JWT_SECRET_KEY` must be set to a strong random value** — the application refuses to start if it is missing, equal to the example value, or shorter than 32 characters (see [docs/adr/0001](docs/adr/0001-jwt-secret-rotation-and-startup-guard.md)):

```bash
openssl rand -hex 32
```

### 2) Install dependencies

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd frontend && npm ci && cd ..
```

`requirements-dev.txt` adds pytest / pytest-cov / ruff on top of the locked `requirements.lock`, sharing the same dependency baseline as CI.

### 3) Prepare frontend TLS certificates (self-signed is fine)

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

### 4) Start the core stack

```bash
scripts/manage_main_stack.sh up
```

This reconciles the core Compose stack (backend API, frontend, PostgreSQL, Redis, Milvus, MinIO, etc.) and waits for all health checks to pass — **a clean checkout runs as-is**. Common subcommands: `config` (validates the orchestration without printing secrets), `status`, `logs`.

> Private deployment extensions (sister services, external orchestration networks, private nginx servers, etc.) are not shipped with the repository; they are injected as an overlay: when the script detects `../aigcnews_private/deploy/docker-compose.private.yml` (overridable via `AIGCNEWS_PRIVATE_COMPOSE`), it is merged in automatically; when absent, the core stack works standalone. See the header comments in `docker/docker-compose.yml` for the mechanism.

### 5) Local development (hot reload outside containers)

```bash
# Backend (reads API_HOST / API_PORT from settings, default 8000)
backend/.venv/bin/python run_server.py

# Frontend (Vite dev server, default 5173)
cd frontend && npm run dev
```

### 6) First admin & SMTP configuration

The repository ships no default admin account: **on an empty users table, the first email-registered user automatically becomes the admin**; later registrations are regular users, and existing deployments (non-empty users table) are unaffected.

Registration requires an email OTP, which depends on mail delivery — so a fresh self-host needs a working mail channel *before* the first admin exists. Pick one:

- Configure `SMTP_*` in `.env` (see the SMTP block in `.env.example`); or
- Leave `SMTP_HOST` empty for dev mode, which prints verification codes to the backend console logs.

Once the first admin logs in, the **Monitor → SMTP email delivery** panel manages the configuration online: it is stored in the database, takes effect immediately (background jobs pick it up within 60 seconds), and **takes precedence over environment variables**; "Send test email" delivers a real message to the current admin's login email using the latest saved configuration. Saving with an empty host deletes the database configuration and reverts to the environment variables.

## Ports & Health Checks

| Address | Purpose |
| --- | --- |
| `http://localhost` (80/443) | Frontend site (production domain certificates live in `frontend/ssl/`; keys must be `root:root` mode 600) |
| `http://localhost:5173` | Vite dev server |
| `http://127.0.0.1:8000` | Backend API (loopback-only binding; `/api/live`, `/api/ready` health checks) |
| `http://localhost:8000/api/mcp` | Local MCP endpoint |

Infrastructure (PostgreSQL / Redis / Milvus / MinIO / Attu) is only exposed inside the orchestration network and publishes no ports to the host; the backend reaches it by service name. For ad-hoc host-side debugging use `docker exec <container> ...`; operational details are in [docs/linux-server-boot.md](docs/linux-server-boot.md).

## Testing & Quality Checks

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

Commit messages follow Conventional Commits (`<type>(<scope>): <subject>`, scope required); details in [docs/git-workflow.md](docs/git-workflow.md).

## Directory Structure

```text
backend/            FastAPI app (app/), tests (tests/), migrations (migrations/), locked dependencies
frontend/           Vue 3 + Vite site (src/), nginx config, frontend image
docker/             Compose orchestration (core stack) and backup-drill orchestration (private extensions injected via overlay)
docs/               Project documentation (index in docs/README.md, decision records in docs/adr/)
scripts/            Stack management, migration, backup, and data backfill scripts
.github/workflows/  CI: backend tests, PostgreSQL integration, frontend build & lint, orchestration smoke
.githooks/          commit-msg validation (git config core.hooksPath .githooks)
```

## Documentation

- [docs/project-overview.md](docs/project-overview.md) — Project panorama: product, architecture, data, deployment, and engineering status
- [docs/architecture.md](docs/architecture.md) — Current functional architecture (PostgreSQL 16 as the sole relational runtime)
- [docs/mcp-server.md](docs/mcp-server.md) — AIGC Radar MCP protocol parameters and policies
- [docs/README.md](docs/README.md) — Full documentation index (including historical archive annotations)

## Data Ownership & Compliance

- **Aggregated content is not ours.** Papers, repository metadata, news, Product Hunt / Hacker News items, X posts, and WeChat articles surfaced by the pipelines remain the property of their original authors and platforms. AIGCNEWS stores metadata, excerpts, and thumbnails solely to operate the reader and claims no ownership. No database dump, collected snapshot, or cached media from the reference deployment is part of this repository or licensed for redistribution.
- **Scraping chains ship as interfaces only.** The X (Twitter) and WeChat ingestion implementations are **not included in this repository** — they load optionally from a private plugin package behind the `x_source_enabled` / `wechat_source_enabled` feature flags (see `backend/app/services/source_plugins/`). Without a plugin, the corresponding routes return 404 and ingestion skips those sources; everything else works unchanged.
- **Operating your own instance** with such plugins is your responsibility: comply with the source platforms' Terms of Service, robots policies, and applicable law, and safeguard any credentials (cookies/tokens) you configure.
- **Marks.** X, Twitter, WeChat, Product Hunt, Hacker News, arXiv, GitHub, and Hugging Face are property of their respective owners; references are nominative, with no affiliation or endorsement implied.
- **Removal requests** for aggregated content: open an issue or contact the maintainer. See [NOTICE](NOTICE) for the full attribution text.

## License

[Business Source License 1.1](LICENSE) © 2026 Kaixxrua — non-production and internal non-commercial use allowed; commercial use and public deployment require the licensor's prior written authorization; each version converts to Apache-2.0 four years after its first public distribution.
