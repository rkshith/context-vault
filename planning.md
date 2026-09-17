# DocIntel (rag-ultimate) — Planning & Architecture

Local, production-oriented document intelligence system.
Stack: React (Vite) + FastAPI + PostgreSQL + Qdrant + OpenRouter. Auth: email/password now, Google OAuth optional.

## 1. Architecture & Data Flow

```
React (5173) --/api--> FastAPI (8000) --+--> PostgreSQL (users, docs, chunks, conversations, messages)
  Vite proxy /api -> backend:8000       +--> Qdrant (vectors + payload)
                                        +--> OpenRouter (chat completions only)
                                        +--> FastEmbed local ONNX (embeddings, no API key)
```

Two separated paths:

- **Ingestion (async):** upload → validate → save disk → DB row `pending` → BackgroundTask: parse → chunk → embed → upsert Qdrant + chunk rows → `ready` / `failed`.
- **Chat (sync):** embed question (same model) → Qdrant filtered search → build prompt → OpenRouter → answer + citations → persist messages.

## 2. Folder Structure (actual)

```
rag-ultimate/
├── docker-compose.yml      # postgres, qdrant, backend, frontend + volumes
├── .env / .env.example
├── planning.md
├── backend/
│   ├── Dockerfile / requirements.txt / alembic.ini
│   ├── alembic/versions/c04c3b9c5971_initial_schema.py
│   ├── scripts/test_ingestion.py
│   └── app/
│       ├── main.py                 # lifespan (ensure Qdrant collection), CORS, routers
│       ├── core/config.py          # pydantic-settings, all secrets from env
│       ├── core/security.py        # argon2, JWT, httpOnly cookie helpers
│       ├── db/base.py, db/session.py
│       ├── models/models.py        # User, Document, Chunk, Conversation, Message
│       ├── schemas/auth.py, document.py, chat.py
│       ├── api/deps.py             # DbDep, get_current_user, UserDep
│       ├── api/routes/health.py, auth.py, documents.py, chat.py, conversations.py
│       ├── services/storage.py, embedding.py, llm.py
│       ├── ingestion/parsers.py, chunker.py, pipeline.py
│       └── vectorstore/client.py, qdrant_repo.py
└── frontend/
    ├── package.json / vite.config.ts / tsconfig.json / index.html
    └── src/
        ├── main.tsx, App.tsx, index.css
        ├── api/client.ts, api/types.ts
        ├── lib/auth.tsx, hooks/useDocuments.ts
        ├── components/Layout.tsx, Spinner.tsx, StatusBadge.tsx
        └── pages/LoginPage.tsx, ChatPage.tsx, DocumentsPage.tsx
```

## 3. PostgreSQL Schema (migration c04c3b9c5971, applied)

- **users:** id uuid pk, email (lowercased, unique), hashed_password nullable, name, avatar_url nullable, auth_provider (`email`|`google`), google_sub unique nullable, created_at, updated_at.
- **documents:** id, user_id fk→users cascade (indexed), original_filename, storage_path, file_type, size_bytes, sha256 (indexed), status enum `pending|processing|ready|failed` (indexed), error nullable, page_count, chunk_count, timestamps.
- **chunks:** id, document_id fk cascade (indexed), user_id fk cascade denormalized (indexed), chunk_index, page_number, content, created_at. Unique(document_id, chunk_index). Source of truth for text; Qdrant rebuildable from this table.
- **conversations:** id, user_id fk cascade (indexed), title, timestamps.
- **messages:** id, conversation_id fk cascade (indexed), role enum `user|assistant`, content, citations JSONB nullable, created_at.

## 4. Qdrant Structure

- Collection `chunks`, 384-dim, Cosine (BAAI/bge-small-en-v1.5 via FastEmbed).
- Payload per point: `user_id, document_id, chunk_id, filename, page_number, chunk_index, text`.
- Keyword payload indexes on `user_id`, `document_id`.
- Every search/delete uses mandatory server-side filter `user_id == current_user` (+ optional `document_id in [...]`). Ownership re-checked in Postgres before search. Point IDs = chunk UUIDs.
- Verified: 384/Cosine, indexes present, delete-by-filter works (16→11 points after doc delete).

## 5. Ingestion Pipeline

`POST /api/documents` (202) → `BackgroundTasks(process_document)`:

1. Validate extension (pdf,docx,xlsx,csv,txt) → 415; stream-save with 25 MB cap → 413; sha256 while streaming; row `pending`.
2. `processing` → parse (pypdf per page; python-docx paragraphs+tables → page 1; openpyxl per sheet; csv row-groups of 100 with header; txt page 1).
3. Chunk: ~900 chars, ~120 overlap, sentence accumulation, word hard-split, never across pages (`chunker.py`).
4. Embed batches via FastEmbed in `to_thread` (model cached in `modelcache` volume).
5. Insert chunk rows + Qdrant upsert with full payload → `ready` (+page/chunk counts) or `failed` + error.
6. Verified end-to-end via `scripts/test_ingestion.py` (docx 10 chunks, xlsx 1, txt 5).

## 6. RAG Retrieval Pipeline

`POST /api/chat {message, conversation_id?, document_ids?}`:

1. Validate selected doc IDs belong to user (404 otherwise); empty = search all user's docs.
2. Get/create conversation (title = first message ≤80 chars); history = last 8 messages.
3. `embed_query` → `search_chunks(user_id, vector, doc_ids, top_k=6, threshold=0.5)`.
4. No hits → honest `NO_CONTEXT_REPLY`, no LLM call, messages still persisted.
5. Hits → system prompt (grounded-only, `[n]` citations, no invention) + numbered blocks `filename · page N` + history → OpenRouter (`openai` SDK, base_url override, temperature 0.2, max 1024).
6. Persist user + assistant messages (citations JSON) → return `{conversation_id, answer, citations[]}`.
7. Score calibration: unrelated ~0.33–0.36, relevant 0.6–0.86 → threshold 0.5 (env `SCORE_THRESHOLD`).
8. Requires `OPENROUTER_API_KEY` in `.env`, else 503. Conversations: list/get-messages/delete with ownership checks.

## 7. Dependencies & Why

Backend (`requirements.txt`): fastapi, uvicorn[standard], sqlalchemy[asyncio]+asyncpg, alembic, pydantic(+settings)+email-validator, argon2-cffi, pyjwt[crypto], python-multipart, pypdf, python-docx, openpyxl, fastembed, qdrant-client, openai, httpx, pytest(+asyncio).
Frontend: react, react-dom, react-router-dom, react-markdown+remark-gfm (clean answers), @tailwindcss/vite+tailwindcss, vite, @vitejs/plugin-react, typescript.
Infra: postgres:16-alpine, qdrant/qdrant:latest, python:3.12-slim, node:22-alpine. Volumes: pgdata, qdrantdata, filedata, modelcache.

## 8. Security & Scalability Notes

- JWT in httpOnly SameSite=Lax cookie (secure in production); generic login errors (no enumeration); 404 not 403 on cross-user doc access.
- Qdrant/Postgres only on docker network; files under random `{user_id}/{doc_id}/`, sanitized filenames; size/type caps; ORM-parameterized SQL; secrets via env only.
- Retrieved text treated as untrusted data in prompts (documented prompt-injection limitation).
- Scale-up later (no code churn): BackgroundTasks→queue (ingestion is one module), disk→S3 (storage.py interface), Qdrant sharding, streaming answers, login rate-limit.

## 9. Milestones — Status & Remaining Work

| # | Milestone | Status | Remaining |
|---|---|---|---|
| 0 | Scaffold, compose, config, health | DONE, verified `/api/health` ok | – |
| 1 | Email/password auth + full schema migration | DONE, verified (signup/login/me/logout, 401/409) | – |
| 2 | Upload, storage, documents CRUD | DONE, verified (202/415/404 isolation/delete) | – |
| 3 | Ingestion (parsers/chunker/FastEmbed/Qdrant) | DONE, verified (ready statuses, Qdrant counts) | – |
| 4 | Chat/RAG + conversations | DONE except live LLM call | Add `OPENROUTER_API_KEY` to `.env`, `docker compose restart backend`, ask a matching question, confirm cited answer |
| 5 | React frontend (login/chat/documents) | BUILT, Vite serves :5173, proxy wired | Manual browser pass: login, upload, poll statuses, select docs, send chat, check citations; run `npm run build` in frontend container to typecheck |
| 6 | Google OAuth (GIS ID-token, env-gated) | DONE (code) | Set `GOOGLE_CLIENT_ID`, restart backend, verify Google button on login + sign-in flow |
| 7 | Polish: streaming, rate-limit, tests, README | DONE (code) | Run `pytest` in backend container; `npm run build` in frontend container for typecheck |
| 8 | Final E2E verification | BLOCKED on Docker daemon | Start Docker Desktop, `docker compose up --build`, migrate, signup→upload→ready→chat with citations→delete |

## 10. How to Run / Verify

```powershell
docker compose up -d --build        # postgres, qdrant, backend :8000, frontend :5173
docker compose exec -T backend alembic upgrade head
# UI: http://localhost:5173   API: http://localhost:8000/api/health
```

Key env vars (`.env`, gitignored): POSTGRES_*, QDRANT_URL, JWT_SECRET, OPENROUTER_API_KEY / OPENROUTER_MODEL, EMBEDDING_MODEL / EMBED_DIM, TOP_K / SCORE_THRESHOLD (0.5), MAX_UPLOAD_SIZE_MB, STORAGE_DIR, CORS_ORIGINS, GOOGLE_CLIENT_ID (empty = Google off).
