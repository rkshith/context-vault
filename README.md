# Context-Vault (rag-ultimate)

Local document intelligence: upload PDF/DOCX/XLSX/CSV/TXT, ask questions, get cited answers. RAG with FastAPI + PostgreSQL + Qdrant + OpenRouter.

## Quickstart

```powershell
cp .env.example .env   # then set JWT_SECRET and OPENROUTER_API_KEY
docker compose up -d --build
docker compose exec -T backend alembic upgrade head
```

- UI: http://localhost:5173
- API: http://localhost:8000/api/health

If you run the backend outside Docker, override `POSTGRES_HOST=localhost`, `QDRANT_URL=http://localhost:6333`, `STORAGE_DIR=./backend/storage`.

## How it works

- **Upload** `POST /api/documents` (202) → file saved to disk, DB row `pending` → background task parses, chunks (~900 chars / 120 overlap, page-safe), embeds locally with FastEmbed (`BAAI/bge-small-en-v1.5`, 384-dim), upserts to Qdrant → `ready`.
- **Chat** `POST /api/chat` (or `/api/chat/stream` for SSE): embed question → Qdrant search filtered by `user_id` (+ optional doc IDs, ownership-checked) → grounded prompt → OpenRouter → answer with `[n]` citations + page numbers. Unrelated questions get an honest "no relevant passages" reply without an LLM call.
- **Vectors** live in Qdrant (`chunks` collection, cosine, keyword indexes on `user_id`/`document_id`); chunk text source of truth is Postgres (`chunks` table).

## API overview

Auth (httpOnly cookie): `POST /api/auth/signup|login|logout|google`, `GET /api/auth/me|config`. Documents: `POST|GET /api/documents`, `GET|DELETE /api/documents/{id}`. Chat: `POST /api/chat|/api/chat/stream`. Conversations: `GET /api/conversations`, `GET .../{id}/messages`, `DELETE .../{id}`.

## Configuration

See `.env.example`. Key vars: `JWT_SECRET` (generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`), `OPENROUTER_API_KEY` + `OPENROUTER_MODEL` (default `openai/gpt-4o-mini`), `TOP_K` (6), `SCORE_THRESHOLD` (0.5), `MAX_UPLOAD_SIZE_MB` (25), `GOOGLE_CLIENT_ID` (empty = Google button hidden; needs a Google Cloud OAuth client ID).

## Tests

```powershell
docker compose exec -T backend pytest
```

Unit tests cover chunking, parsers, password/JWT helpers, and the Qdrant tenant filter. `backend/scripts/test_ingestion.py` is an end-to-end ingestion check run inside the backend container.

## Limits

Prompt injection from document content is a known limitation (mitigated by citation-grounded prompts). Rate limits are in-memory per process (login 10/min, chat 30/min); use Redis when scaling horizontally.
