# RopQA — Release Ops QA Autopilot

RopQA automates the quality-assurance gate between artifact production and deployment. You upload a release artifact (XML manifest, JSON bundle, binary, etc.), configure a set of validation rules, and RopQA runs every rule against the artifact inside an async pipeline. Pass/fail findings land in a structured report so your release process never ships a bad build silently.

## What it does

| Capability | Detail |
|---|---|
| **Artifact ingestion** | Upload release files via drag-and-drop or API; stored in S3-compatible storage |
| **Rule engine** | Evaluate XPath, regex, JSONPath, and semver constraints against any artifact |
| **Async pipelines** | Each release triggers a Celery pipeline; tasks run concurrently and report back in real-time |
| **Reports** | Structured pass/fail findings per rule, with trend charts across releases |
| **Auth** | Clerk-powered authentication with per-user access |

## Stack

```
apps/
  web/   — Next.js 14 (App Router) · TypeScript · Tailwind CSS · shadcn/ui
  api/   — FastAPI · SQLAlchemy (async) · Celery · PostgreSQL · Redis
```

## Quick start

### Prerequisites

- Node.js 20+
- Python 3.11+
- Docker & Docker Compose

### 1. Clone and configure

```bash
git clone <repo-url> ropqa && cd ropqa
cp .env.example .env
# Fill in CLERK keys and AWS credentials in .env
```

### 2. Start infrastructure

```bash
docker compose up postgres redis -d
```

### 3. Run the API

```bash
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit as needed
alembic upgrade head
uvicorn main:app --reload
# → http://localhost:8000
# → http://localhost:8000/docs (Swagger UI)
```

### 4. Run the Celery worker

```bash
# in apps/api (same venv)
celery -A tasks.celery_app worker --loglevel=info
```

### 5. Run the web app

```bash
cd apps/web
npm install
cp .env.local.example .env.local   # add your Clerk publishable key
npm run dev
# → http://localhost:3000
```

### 6. Run everything with Docker

```bash
docker compose up --build
```

## Project structure

```
ropqa/
├── apps/
│   ├── web/                    # Next.js frontend
│   │   ├── app/                # App Router pages & layouts
│   │   ├── components/         # UI components
│   │   │   ├── layout/         # Sidebar, Header
│   │   │   └── dashboard/      # Dashboard widgets
│   │   └── lib/                # API client, utilities
│   └── api/                    # FastAPI backend
│       ├── routers/            # Route handlers (releases, pipelines, rules, reports)
│       ├── services/           # Business logic
│       ├── models/             # SQLAlchemy ORM models
│       ├── schemas/            # Pydantic request/response schemas
│       ├── tasks/              # Celery task definitions
│       ├── rules/              # Rules engine (XPath, regex, semver, JSONPath)
│       └── alembic/            # DB migrations
├── docker-compose.yml
└── .env.example
```

## Environment variables

See `.env.example` at the repo root for all required variables. Per-app examples:

- `apps/api/.env.example` — database, Redis, AWS, Clerk secret key
- `apps/web/.env.local.example` — Clerk publishable key, API URL

## Running tests

```bash
# API
cd apps/api
pytest --asyncio-mode=auto

# Web
cd apps/web
npm run type-check
```

## Roadmap

- [ ] S3 artifact upload (wired, not yet implemented)
- [ ] Real-time pipeline progress via SSE / WebSocket
- [ ] Slack / webhook notifications on pipeline completion
- [ ] Rule templates library
- [ ] Role-based access control
- [ ] GitHub Actions integration for CI-triggered pipelines
