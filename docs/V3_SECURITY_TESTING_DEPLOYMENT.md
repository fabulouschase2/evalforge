# EvalForge AI V3 — Security, Testing & Deployment

## Security review (`docs/V3_SECURITY.md` summary)

Implemented and tested:
- Password hashing (bcrypt), JWT auth with expiry, account suspension lockout.
- Role-based access on every route (server-side only), project membership checks,
  organization tenant isolation (automated cross-tenant test matrix).
- Rate limiting: login/register (pre-existing) + per-credential external API
  buckets (429).
- Upload validation: extension + magic-byte sniffing for media; parse-time row
  validation for datasets; size limits everywhere.
- Secret handling: API keys stored hashed (sha256, prefix lookup, constant-time
  compare, shown once); webhook signing secrets shown once and never serialized;
  no secrets in logs.
- Webhook SSRF guard: scheme allowlist, IP-literal blocks (private/loopback/
  link-local/reserved/metadata), DNS resolution + delivery-time re-check.
- Append-only history for reviews, adjudications, golden results, messages,
  deliveries; audit log on every privileged action incl. downloads/exports.
- Idempotency-Key reuse with a different body is rejected (422).
- Safe error handling: 422 field errors; 500s log internally and return a generic
  message.

Known limitations (documented, not hidden):
- Webhook signing secrets live in the DB (same trust model as GitHub/Stripe);
  a KMS envelope is the production hardening step.
- External API rate limiting is in-memory per process — use Redis for multi-instance.
- Webhook delivery is an in-process worker — single-node scale; swap for a queue
  (Celery) when needed.
- Email is only sent when SMTP env vars are configured; otherwise in-app only
  (no simulated delivery).

## Testing (`docs/V3_TESTING.md` summary)

Current results on this machine (2026-11-14):

| Suite | Result |
|---|---|
| Backend pytest | **188/188** (131 legacy V2 + 57 V3: tenant isolation, organizations, client portal, golden tasks, qualifications, multimodal, API/webhooks, platform analytics) |
| Frontend Vitest | 9/9 |
| Playwright E2E (V2 workflow) | 3/3 |
| Playwright E2E (V3 client portal) | 4/4 |
| Production build (`tsc -b && vite build`) | success |
| Alembic chain on fresh DB | 7 migrations → 46 tables, clean |

Live verification performed against running servers (see `docs/V3_PROGRESS.md`):
client journey A (org → request → approve → convert → upload → messages →
deliverable publish/download → cross-tenant 404s), worker journey B (assessment →
attempt → pass → verified skill → tier), multimodal journey (upload → tasks →
claim → annotate → save v1 → submit → review).

## Deployment (`docs/V3_DEPLOYMENT.md` summary)

1. **Docker Compose** (PostgreSQL + backend + nginx frontend):
   ```bash
   cp backend/.env.example backend/.env   # set SECRET_KEY!
   docker compose up --build              # backend runs `alembic upgrade head` first
   # frontend :8080, API :8000, docs at /docs
   ```
2. **Local development**: backend venv + `alembic upgrade head` + uvicorn :8000;
   frontend `npm install && npm run dev` :5173 (Vite proxies `/api`).
3. Migrations are additive + idempotent; run `alembic upgrade head` — never
   auto-migrate production without a backup.
4. Backups: `pg_dump evalforge` (all tables above); the `storage/` directory
   (deliverables/attachments/media) must be backed up alongside the DB.
5. Health checks: `GET /api/health` (DB ping).
6. Required production config: `SECRET_KEY`, `DATABASE_URL`, `CORS_ORIGINS`,
   `EVALFORGE_STORAGE_ROOT`; optional `SMTP_*`; see `backend/.env.example`.
7. First account to register becomes super_admin; create the first client
   organization from Admin → Organizations, then invite client members.
