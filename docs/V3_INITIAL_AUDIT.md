# EvalForge AI V3 — Initial Audit (Phase 0)

**Audit date:** 2026-11-13
**Auditor:** V3 implementation agent (independent verification — no reliance on prior completion reports)
**Repository:** `C:\Users\chase\.zcode\workspace\evalforge` (backend FastAPI/Python 3.12, frontend React 18/TS/Vite)

---

## 1. Executive summary

The EvalForge AI v2 codebase is **present, coherent and working**. Every claim in the v2 completion
report that could be re-verified independently was reproduced during this audit:

| Check | Command / method | Result |
|---|---|---|
| Backend unit/integration tests | `pytest` (backend venv) | **131/131 pass** |
| Frontend tests | `npm test` (Vitest + RTL) | **9/9 pass** (2 files) |
| API smoke test (fresh DB) | `smoke_test.py` against a fresh SQLite instance on :8001 | **42/42 pass** |
| API smoke test (existing dev DB) | `smoke_test.py` against :8000 (dirty DB) | 36/38 — both failures traced to stale demo state, not code (see §5) |
| Playwright E2E | `npx playwright test` with dev servers running | **3/3 pass** (multi-role browser workflow) |
| Production build | `npm run build` (tsc -b && vite build) | **succeeds** (964 KB JS bundle, no code splitting) |
| Alembic migration on fresh DB | `alembic upgrade head` against empty SQLite | **clean** |
| Live server | `uvicorn app.main:app` + `/api/health`, smoke pipeline | **works** |

**Conclusion: V2 is a valid, functional baseline. V3 will extend it, not rebuild it.**

## 2. What exists (verified)

### 2.1 Backend architecture (`backend/app/`)
- **FastAPI** app (`main.py`) with 16 routers, CORS, structured error handlers, `/api/health`.
- **Core:** `config.py` (pydantic-settings, env-driven), `security.py` (bcrypt hashing, HS256 JWT via
  PyJWT, `get_current_user` dependency, `RoleChecker`), `logging.py`.
- **Models (11 files):** User (6 roles), Organization (minimal — name/description only),
  Project (+ProjectMember w/ per-project role), Dataset → DatasetVersion → DatasetRecord (immutable
  versions, custom field definitions), Rubric → RubricVersion (append-only), EvaluationRun →
  EvaluationResult → EvaluationFinding, Task (+TaskAssignment history), Submission →
  SubmissionReview (append-only) → SubmissionAdjudication, Notification, AuditLog, Setting.
- **Engine:** deterministic evaluation engine — 14 check types, reference-based factuality
  heuristics, weighted scoring, borderline classification, runner with immutable findings.
- **Services:** datasets (parse/validate/version), rubrics (validate/version), reviews (blind review,
  adjudication), analytics (sklearn/scipy: accuracy/precision/recall/F1/Cohen's κ/Fleiss' κ),
  audit, demo seed, notifications.
- **Tests:** 16 test files / 131 tests incl. auth, platform roles, project isolation, concurrent task
  claiming, submission validation, blind reviews, immutability, adjudication, agreement metrics,
  rate limiting, audit, RBAC.

### 2.2 Frontend architecture (`frontend/src/`)
- React 18 + TypeScript + Vite + Tailwind (dark enterprise theme), TanStack Query, React Router 6,
  Radix primitives, Recharts, React Hook Form + Zod.
- Role-aware layout/sidebar; pages for login/register, dashboards (admin/tester/reviewer/quality),
  projects, datasets (+detail, data collection), rubrics (+builder), evaluations, task marketplace /
  my tasks / task workspace, review queue / submission review, quality pages, analytics, audit logs,
  notifications, profile, settings.
- API layer in `src/api` with JWT bearer handling.

### 2.3 Infrastructure
- `docker-compose.yml`: Postgres 16 + backend + nginx-served frontend with `/api` proxy.
- Single Alembic migration `4bfc767ebcea_platform_schema_v2` (full schema incl. role data migration).
- `smoke_test.py` (38–42 checks), Playwright e2e spec covering the full multi-role workflow.

## 3. What works (verified end-to-end)

1. Auth: registration (first user → super_admin bootstrap), login, JWT, rate limiting, role changes
   (admin-only), account deactivation (admin-only), inactive users locked out.
2. Projects: CRUD, per-project membership with three member roles (admin/tester/reviewer),
   **project-level isolation enforced server-side** (9 dedicated isolation tests pass).
3. Data collection: CSV/JSON/JSONL upload with preview → column mapping → duplicate/invalid report →
   commit as immutable version; manual entry; bulk JSON paste; custom per-dataset fields; records
   with categories/difficulty/language; dataset archive/restore; export.
4. Rubrics: versioned rubric builder (weighted criteria + deterministic checks + dynamic evaluation
   forms), server-side validation.
5. Automated evaluation engine: run execution, findings with `rule_id`/evidence/`evaluator_version`/
   `rubric_version`, borderline routing, gold-label metrics (accuracy/precision/recall/F1/Cohen's κ),
   honest `insufficient_reason` when metrics can't be computed.
6. Task lifecycle: generation from records, manual/bulk creation, **atomic claiming**, assignment
   expiry, pause/resume/cancel, reassignment with immutable TaskAssignment history, attempt limits.
7. Submissions: rubric-form-validated, autosave drafts, attempt tracking, immutable once submitted.
8. Reviews: blind review queue, atomic claim-review, append-only decisions, revision requests,
   flags/escalations, notifications.
9. Adjudication: senior-reviewer queue, append-only adjudication referencing exact review ids.
10. Quality analytics: reviewer consistency, tester quality, Fleiss' κ with honest degenerate-case
    handling (returns `None`, not fake 1.0).
11. Notifications: per-user, unread count, read/read-all.
12. Audit log: 14+ action types observed live; admin-only access enforced.
13. Demo pipeline: `[DEMO]`-labeled, clearly separated from production data.

## 4. What is missing for V3 (gap analysis vs. V3 spec)

| V3 requirement | V2 status |
|---|---|
| Multi-tenant organizations | `organizations` table exists but is a bare name/description; **no org membership, no org-scoped authorization anywhere**; README itself lists "single-workspace tenancy" as a limitation |
| Client roles (Owner/PM/Viewer) | Do not exist; roles are internal-only (6) |
| Client portal (dashboard/requests/uploads/messaging/deliverables) | Does not exist |
| Project requests + approval queue | Does not exist |
| Client messaging | Does not exist |
| Deliverable publishing + audited client downloads | Export endpoints exist for staff, but no client-facing, permission-checked, audited deliverable flow |
| Golden tasks | Do not exist (gold labels exist on records for engine metrics, but no worker-queue golden task system, scoring, alerts, reports) |
| Worker qualifications (assessments, attempts, scoring, skills, eligibility) | Do not exist; project membership is the only access gate |
| Worker performance dashboards / progression | Partial (tester quality stats exist internally; no worker-facing dashboard, no tiers) |
| Multimodal annotation (image/video/audio workspaces, media storage) | Do not exist; `project_type` includes image/video/audio values but no media assets, no annotation models, no UI |
| API credentials / external API / scopes / rate limits | Do not exist (all auth is interactive JWT) |
| Webhooks | Do not exist |
| Idempotency keys | Do not exist |
| Unified analytics (platform/client/worker views) | Partial: strong project-level analytics; no org/client/worker-facing views |
| Email delivery | Not implemented (in-app notifications only) — must be configured-and-verified or honestly labeled |
| Media/file storage service | Does not exist (only CSV/JSON uploads parsed in-memory) |

## 5. Issues found during audit (to fix in V3)

1. **`backend/requirements.txt` is missing `psycopg`** while `docker-compose.yml` and
   `DATABASE_URL` docs use `postgresql+psycopg://`. The Docker production path cannot connect to
   Postgres as shipped. → Add `psycopg[binary]` (Phase 1).
2. **Dirty-DB smoke failures:** `smoke_test.py` assumes a fresh DB; on the existing dev DB two checks
   fail (`review queue populated`, `audit tracks evaluation + review`) because a previous demo load
   consumed pending assignments and page-1 audit logs scrolled. Verified 42/42 on a fresh DB.
   → Make smoke test tolerate re-runs (Phase 10, low priority).
3. **Dead debug files** `backend/_dbg6.py`, `backend/_dbg11.py` at repo root. → Remove.
4. **Frontend bundle 964 KB** single chunk (warning only). → Consider code splitting in Phase 10.
5. **Org model is decorative** — `projects.organization_id` exists but nothing authorizes by it.
   → Phase 1 makes organizations real tenants; existing rows keep `organization_id = NULL` behavior
   via backward-compatible checks.
6. **`frontend/dist` is committed** in the working tree (build artifact). Harmless locally; note for
   git hygiene.
7. **Unscoped reads (deep audit finding):** `datasets.py` list/get/versions, `rubrics.py` list/get/
   versions, `evaluations.py` (+results/findings) and `analytics.py` are role-gated but **not
   project-membership scoped** — any authenticated user can enumerate other projects' datasets,
   rubrics, runs and global analytics. Contradicts the README's isolation claims; becomes a
   cross-tenant leak once client roles exist. → Phase 1 scopes these reads.
8. **`POST /api/demo/load` open to any authenticated user** (creates demo accounts with documented
   passwords). → restrict to staff.
9. **Stale legacy role strings** in `routes/reviews.py` supervisor checks
   (`"administrator"`, `"project_manager"`) mean super_admin is not treated as supervisor there.
   → replace with `UserRole.STAFF`.
10. **`POST /api/datasets/{id}/restore` skips the project-membership check** (any staff can restore
    any project's archived dataset). → add check.
11. **`quality/agreement` and `quality/sample` lack the project scoping** used by other quality
    endpoints. → add scoping.
12. **`exports.py` audit rows lose client IP** (`request: Request = None` default). → fix signature.
13. **`GET /api/auth/users` exposes all user emails/roles to every authenticated user.**
    → keep (needed for reviewer assignment) but document; strip emails for non-staff in Phase 2.

## 6. Migration risks for V3

- SQLite (dev) + PostgreSQL (compose) dual support → all new migrations must use
  `op.batch_alter_table` for SQLite compatibility (existing migration already does).
- `users.role` is a free string (no DB constraint) → V3 adds client roles; safe because all checks
  are application-level. Keep it that way (no CHECK constraint change needed) but add index-friendly
  values.
- Existing data must survive: every new column nullable/defaulted; new tables only; no renames of
  v2 columns. `organizations` gets new columns via batch-alter (nullable).
- The app calls `Base.metadata.create_all` on startup — new tables appear automatically in dev even
  without migration, masking missed migrations. → V3 discipline: always write the Alembic migration;
  treat `create_all` as dev convenience only.

## 7. Reuse map (do not duplicate)

| Existing asset | Reused by V3 |
|---|---|
| `Project`, `ProjectMember`, membership checks in routes | Task distribution, eligibility gating (add qualification checks, don't replace) |
| `Dataset`/`DatasetVersion`/`DatasetRecord` import pipeline | Client uploads (same services, new client-portal entry points) |
| `Submission`/`SubmissionReview`/`SubmissionAdjudication` (append-only) | Multimodal annotation review reuses these directly; annotations attach to submission payload |
| `Task` + `TaskAssignment` + atomic claim | Golden task insertion rides on normal task queues; multimodal tasks are Tasks |
| Notification service | All new notification types |
| Audit service | All new audited events (org, client, API key, webhook, deliverable) |
| Analytics service (sklearn metrics) | Extended for golden-task & agreement reporting; never bypassed with invented numbers |
| Reviewer/adjudication models | Used unchanged for multimodal review |
| Auth/RoleChecker | Extended with client-role checkers + API-key auth dependency (separate path) |

## 8. Recommended implementation order

Adopted from the V3 master spec phases (Phase 0 = this audit):

1. **Phase 1** Multi-tenant foundations — org membership, client roles, org-scoped access control,
   isolation tests, `psycopg` fix, migration `xxx_v3_phase1`.
2. **Phase 2** Client Portal — project requests, client dashboard/monitoring, client uploads,
   messaging, deliverables, approval queue.
3. **Phase 3** Golden Tasks — management, distribution, scoring, alerts, reporting.
4. **Phase 4** Qualifications — assessments, attempts, scoring, skill profiles, eligibility, tiers.
5. **Phase 5–7** Image / Video / Audio annotation — media assets, annotation models, workspaces,
   review integration, exports.
6. **Phase 8** API credentials + external endpoints + webhooks + idempotency + docs.
7. **Phase 9** Unified analytics.
8. **Phase 10** Security hardening, performance, regression, docs, deployment.

Each phase: migration → backend models/services/routes → tests → frontend pages wired to real APIs →
full regression (pytest, vitest, build) → phase report appended to `docs/V3_PROGRESS.md`.

## 9. Environment notes for this workspace

- Node.js is not installed system-wide; Node 24.21 / npm 12.2 run through the ZCode Electron runtime
  fallback (`ZCODE_NODE_FALLBACK_EXEC_PATH` + bundled npm). All frontend commands in this project use
  that path. Documented in `docs/V3_PROGRESS.md`.
- Playwright chromium 1254 installed and working.
- Docker is **not** running in this environment; docker-compose is documented but not executed here.
  Local verification uses SQLite + uvicorn + Vite.
- Python 3.12.10 venv at `backend/.venv` with all pinned requirements installed.
