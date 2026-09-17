# Context-Vault (rag-ultimate)

Private document intelligence: upload PDF, DOCX, XLSX, CSV, and TXT files, then ask questions and get answers grounded in your own documents — with page-level citations.

**Stack:** React 19 + Vite + Tailwind CSS · FastAPI · PostgreSQL · Qdrant · OpenRouter · FastEmbed (local embeddings)

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Data model](#data-model)
- [Pipelines](#pipelines)
- [Quickstart (local)](#quickstart-local)
- [Cloud databases](#cloud-databases)
- [Deploy (Render + Vercel)](#deploy-render--vercel)
- [Configuration](#configuration)
- [API overview](#api-overview)
- [Performance notes](#performance-notes)
- [Security](#security)
- [Testing](#testing)
- [Limitations](#limitations)

## Features

- **Email/password auth** with httpOnly cookie sessions; **Google sign-in** (GIS token flow) activates automatically when `GOOGLE_CLIENT_ID` is set.
- **Document upload** (PDF, DOCX, XLSX, CSV, TXT; 25 MB cap) with visible processing states: `pending → processing → ready / failed`.
- **RAG chat** with numbered citations (`[1]`, `[2]`) mapped to a Sources list showing filename and page. Answers stream token-by-token over SSE.
- **Document-scoped search** — tick specific files in the chat sidebar, or search across everything.
- **Conversations** persist with full history; the last 8 messages are included as context for follow-up questions.
- **Strict tenant isolation** — every row and every vector carries `user_id`; retrieval filters are built server-side from the session, never from client input.

## Architecture

```
┌────────────┐   /api/*    ┌────────────┐
│   React    ├────────────►│  FastAPI   │
│  (Vite)    │◄────────────┤  backend   │
└────────────┘  SSE/JSON   └─────┬──────┘
                                 ├──────────► PostgreSQL   users, documents,
                                 │             chunks, conversations, messages
                                 ├──────────► Qdrant       384-dim vectors + payload
                                 └──────────► OpenRouter   chat completions only
                                              FastEmbed     local ONNX embeddings
                                              (in-process)
```

The system has exactly **two paths**, kept strictly separate:

| | Ingestion path (async) | Chat path (sync) |
|---|---|---|
| Trigger | `POST /api/documents` returns `202` immediately | `POST /api/chat` or `/api/chat/stream` |
| Steps | validate → save file → DB row (`pending`) → background task: parse → chunk → embed → upsert | embed question → filtered vector search → grounded prompt → LLM → persist |
| Failure mode | Document marked `failed` with a message; uploader never sees a 500 | Honest "no relevant passages" reply when nothing scores above threshold — no hallucinated answers, no wasted LLM call |

**Deliberate choices:**

- **FastEmbed instead of an embeddings API.** OpenRouter is chat-focused and doesn't reliably offer embeddings. A local ONNX model (`BAAI/bge-small-en-v1.5`) means no second API key, no per-call cost, and documents never leave your infrastructure for embedding. Both chunks and questions use the same model — a hard requirement, since vectors from different models live in incomparable spaces.
- **Postgres + Qdrant, not one database.** Postgres is the source of truth (chunk text, metadata, ownership); Qdrant does what it's built for (filtered vector search with payload indexes). Qdrant can always be rebuilt from the `chunks` table.
- **No queue, no object storage, no orchestrator.** A background task plus a storage-module boundary is enough at this scale; both have clean swap points (`ingestion/pipeline.py`, `services/storage.py`) when growth demands more.

## Repository layout

```
├── docker-compose.yml      # backend + frontend (DBs are cloud; volumes kept as rollback)
├── .env / .env.example
├── backend/
│   ├── Dockerfile / requirements.txt / requirements-dev.txt
│   ├── alembic/            # versioned schema migrations
│   └── app/
│       ├── main.py         # lifespan (Qdrant collection init), CORS, routers
│       ├── core/           # config (env-only secrets), JWT/cookies, rate limiting
│       ├── db/             # async engine + session
│       ├── models/         # SQLAlchemy: User, Document, Chunk, Conversation, Message
│       ├── schemas/        # Pydantic request/response contracts
│       ├── api/routes/     # health, auth, documents, chat, conversations
│       ├── services/       # storage, embedding, llm, google_auth
│       ├── ingestion/      # parsers, chunker, pipeline
│       └── vectorstore/    # Qdrant client + filtered operations
└── frontend/
    └── src/
        ├── api/            # typed fetch client (VITE_API_BASE_URL aware) + types
        ├── lib/auth.tsx    # session context
        ├── hooks/useDocuments.ts
        ├── components/     # Layout, Spinner, StatusBadge
        └── pages/          # Login, Chat, Documents
```

## Data model

**PostgreSQL** (migration `c04c3b9c5971`):

- `users` — id, lowercased unique email, nullable password hash (Google-only users have none), name, avatar, `auth_provider`, unique `google_sub`.
- `documents` — id, `user_id` (FK cascade), original filename, storage path, file type, size, SHA-256, `status` enum, error, page/chunk counts.
- `chunks` — id, `document_id` + denormalized `user_id` (both FK cascade, indexed), `chunk_index` (unique per document), `page_number`, full text.
- `conversations` — id, `user_id`, title (from first message).
- `messages` — id, `conversation_id` (FK cascade), `user`/`assistant` role, content, structured `citations` JSONB.

**Qdrant** — one `chunks` collection, 384 dimensions, cosine distance. Every point payload: `user_id`, `document_id`, `chunk_id`, `filename`, `page_number`, `chunk_index`, `text`. Keyword indexes on `user_id` and `document_id`; point IDs are the chunk UUIDs, so deletes are exact and idempotent.

## Pipelines

**Ingestion** (`upload → parse → chunk → embed → upsert`):

1. Extension and size enforced during streaming save; SHA-256 computed inline; row created as `pending`.
2. Parsing preserves meaningful page units: PDF physical pages, DOCX as page 1 (paragraphs + tables), XLSX per worksheet, CSV in 100-row groups with the header repeated, TXT as page 1.
3. Chunking (~900 chars, ~120 overlap) accumulates whole sentences and hard-splits only oversized ones — chunks never cross pages, so citations stay exact.
4. Embeddings run in batches off the event loop; chunk rows and Qdrant points are written together, then the document flips to `ready` with page/chunk counts.

**Retrieval** (`question → search → prompt → answer`):

1. Selected document IDs are ownership-checked in Postgres first; an empty selection searches everything the user owns.
2. The question is embedded and searched with a mandatory `user_id` filter (`top_k=6`, cosine threshold `0.5` — calibrated so unrelated text at ~0.35 is rejected while relevant passages at 0.6+ pass).
3. The system prompt constrains the model to the numbered passages, demands `[n]` citations, and forbids inventing facts (temperature 0.2).
4. Both messages persist with structured citations; the non-streaming endpoint returns them as JSON, the streaming endpoint emits `citations → token* → done` SSE events.

## Quickstart (local)

```powershell
cp .env.example .env   # set JWT_SECRET and OPENROUTER_API_KEY inside
docker compose up -d --build
docker compose exec -T backend alembic upgrade head
```

- UI: http://localhost:5173 · API health: http://localhost:8000/api/health
- Sign up, upload a file, wait for `ready`, ask a question.

## Cloud databases

The backend talks to Postgres and Qdrant purely through env vars — local or cloud, no code changes:

```env
DATABASE_URL="postgresql://postgres.REF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres"
QDRANT_URL="https://xxxx.cloud.qdrant.io:6333"
QDRANT_API_KEY="..."
```

Notes: use Supabase's **Connection pooling** (Supavisor, port 6543) rather than the direct connection — the direct hostname is IPv6-only and unreachable from IPv4-only Docker networks. Passwords with special characters are auto-encoded by the backend.

## Deploy (Render + Vercel)

**Render — backend** (Free Web Service, root `backend/`):

- Build: `pip install -r requirements.txt`
- Start: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT` (keep a single worker — extra workers duplicate the embedding model in RAM)
- Env: `DATABASE_URL`, `QDRANT_URL`, `QDRANT_API_KEY`, `JWT_SECRET`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, plus `ENVIRONMENT=production`, `COOKIE_SAMESITE=none`, `CORS_ORIGINS=https://YOUR-APP.vercel.app`

**Vercel — frontend** (root `frontend/`):

- Env: `VITE_API_BASE_URL=https://YOUR-BACKEND.onrender.com` (baked in at build time, so set it before deploying)

Expect slow cold starts on free tiers (model download on first boot, service sleep after idle). Uploaded files live on ephemeral disk — fine for evaluation; wire object storage before trusting it with real data.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `JWT_SECRET` | — (required) | Session signing; generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | `openai/gpt-4o-mini` | Answer generation; chat returns 503 without a key |
| `DATABASE_URL` | — (falls back to `POSTGRES_*` parts) | Managed Postgres URI (SSL + pooler handled automatically) |
| `QDRANT_URL` / `QDRANT_API_KEY` | `http://qdrant:6333` / empty | Vector store endpoint |
| `EMBEDDING_MODEL` / `EMBED_DIM` | `BAAI/bge-small-en-v1.5` / `384` | Must stay in sync with the Qdrant collection |
| `TOP_K` / `SCORE_THRESHOLD` | `6` / `0.5` | Retrieval depth and relevance cutoff |
| `MAX_UPLOAD_SIZE_MB` / `STORAGE_DIR` | `25` / `/app/storage` | Upload cap and file location |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed frontend origins |
| `COOKIE_SAMESITE` | `lax` | Set `none` for cross-domain (Vercel + Render) deployments |
| `GOOGLE_CLIENT_ID` | empty (Google hidden) | Enables the Google sign-in button when set |

## API overview

Auth uses an httpOnly `SameSite` cookie (`POST /auth/signup|login|logout|google`, `GET /auth/me|config`).

| Area | Endpoints |
|---|---|
| Documents | `POST /api/documents` (202) · `GET /api/documents` · `GET /api/documents/{id}` · `DELETE /api/documents/{id}` (removes file, rows, and vectors) |
| Chat | `POST /api/chat` (JSON answer + citations) · `POST /api/chat/stream` (SSE) |
| Conversations | `GET /api/conversations` · `GET /api/conversations/{id}/messages` · `DELETE /api/conversations/{id}` |
| Health | `GET /api/health` (reports Postgres + Qdrant connectivity) |

Cross-user access returns `404` (not `403`) to avoid leaking document existence; login failures use one generic message to prevent user enumeration.

## Performance notes

The backend is tuned for small instances: FastEmbed/onnxruntime imports lazily (stays out of boot time and base RAM until first use), heavy document parsers import per-format on demand, the DB pool is capped at 3+2 connections for transaction poolers, and `OMP_NUM_THREADS=1` avoids thread oversubscription on shared CPUs. Deploy images exclude tests and scripts via `.dockerignore`, and test dependencies live in `requirements-dev.txt`, not the production install.

## Security

Secrets only via environment (`.env` is gitignored); Argon2id password hashing; short-lived JWTs; strict CORS; upload type/size caps with sanitized filenames; ORM-parameterized queries; login 10/min and chat 30/min in-memory rate limits (swap for Redis when scaling horizontally).

## Testing

```powershell
cd backend
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest
```

Unit tests cover the chunker, parsers, password/JWT helpers, and the Qdrant tenant filter. `backend/scripts/test_ingestion.py` exercises the full ingestion path inside a running backend container.

## Limitations

- Retrieved document text is untrusted model input — prompt injection from malicious files is a known, only partially mitigated risk (grounded prompts + citations).
- File storage is local disk; use object storage for any deployment where uploads must survive restarts.
- Single-process background ingestion: fine for personal/small-team use; move to a task queue if uploads become concurrent and heavy.
