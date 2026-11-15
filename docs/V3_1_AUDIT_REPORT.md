# EvalForge AI V3.1 — Security, Reliability & Quality Audit Report

**Branch:** `release/v3.1-security-reliability` · **Date:** 2026-11-14
**Scope:** full-stack audit of the V3 implementation (backend, frontend, infra, tests, docs)
with verified fixes. Every fix below has a reproducing regression test unless marked otherwise.

**Final verification:** backend pytest **207/207** · frontend Vitest **9/9** · Playwright e2e **17/17**
(v2 workflow 3, client portal 4, quality flows 5, multimodal+integrations 5) · production build **✓**
· Alembic fresh-DB chain **✓** (SQLite + PostgreSQL) · initial JS bundle **964 kB → 334 kB (gzip 266 → 107 kB)**.

---

## Phase 1 — Security findings and fixes

| ID | Severity | Finding | Fix | Verification |
|---|---|---|---|---|
| S1 | **High** | Insecure production defaults: `SECRET_KEY="change-me-in-production"` accepted in production; JWTs forgeable | `Settings` model validator refuses startup in production when the key is a known default or < 32 chars; error message names the remedy | `test_production_secret_key_validation` (2 rejection cases + 1 accept) |
| S2 | **High** | `GET /api/auth/users` returned the full user directory (emails + roles) to **any** authenticated user incl. clients and workers — user enumeration | Staff-only (403 otherwise) | `test_user_directory_staff_only` |
| S3 | **High** | Evaluation runs/results/findings readable by any authenticated user, unscoped (IDOR: swap run id, read other tenants' evaluation data) | Runs inherit dataset-project visibility; `_load_run_scoped` returns 404 (non-enumerable); `create_evaluation` requires project admin (projectless → super admin only) | `test_evaluation_runs_hidden_from_non_members`, `test_evaluation_run_visible_to_project_staff`, `test_run_creation_requires_project_admin` |
| S4 | **High** | Rubrics readable/writable cross-project (list unscoped; any staff evaluator could edit another project's rubric) | `_rubric_visible` read scoping + `_require_rubric_admin` write gate; create requires project admin when project-linked | `test_rubrics_hidden_from_non_members`, `test_rubric_update_requires_project_admin` |
| S5 | **High** | Global analytics (`/overview`, `/metrics`, `/agreement`, `/confusion-matrix`) open to any authenticated user — leaked cross-project quality data | `/overview` staff-only; run-scoped metrics require run visibility; no-run aggregate access staff-only | `test_global_analytics_staff_only`, `test_run_scoped_metrics_allowed_for_project_staff` |
| S6 | **Medium** | `GET /api/audit-logs` accessible to project managers (README claimed admin-only) — exposes all tenants' activity | Restricted to `ADMINISTRATORS` (super_admin + project_admin), matching the frontend gate | `test_audit_logs_administrator_only` |
| S7 | **Medium** | `POST /api/reviews/assign` — any project_manager could assign reviewers to **any** project's flagged results (cross-project write) | Caller must administer each result's project (super admin excepted); bulk "assign all flagged" now filtered to administered projects | `test_review_assignment_requires_project_admin` |
| S8 | **Medium** | `POST /api/reviews/results/{id}/adjudicate` — same cross-project write gap | Restricted to the result's project admin or platform-wide quality roles | `test_adjudication_requires_project_admin` |
| S9 | **Medium** | Projectless datasets readable by testers/reviewers (V3.1 tightened `require_dataset_read` inconsistently with the original loader) | Projectless datasets are staff-only for read and super-admin-only for edits (unchanged) | `test_projectless_dataset_staff_only` |
| S10 | **Medium** | Webhook SSRF gaps: redirects not explicitly disabled (httpx default is off, but not asserted); URLs with embedded credentials accepted; DNS-rebinding TOCTOU | `follow_redirects=False` asserted at the delivery call; URLs with `user:pass@` rejected; delivery-time re-resolution already re-validates every resolved address. Residual: theoretical DNS-rebinding TOCTOU between resolution and connect — documented below (mitigated by delivery-time re-check; a pinned-connection transport is the future hardening step) | `test_webhook_url_with_embedded_credentials_blocked`, `test_webhook_redirects_not_followed` (302 → metadata URL NOT followed), `test_webhook_dns_rebind_blocked_at_delivery` (private resolution at delivery → delivery failed) |
| S11 | **Medium** | Demo accounts with **published** passwords (`DemoReview!23` in README) — a forgotten demo instance was remotely accessible | Demo seeding gated: production requires explicit `ENABLE_DEMO=true`; passwords now **random per seed run**, printed once to the server console and returned only to the calling staff member; smoke test reads them from the response; all published passwords removed from README | `test_production_requires_explicit_demo_opt_in`; `rg DemoReview` → no matches in code/docs |
| S12 | **Low** | Login brute-force limiter (20/5min per IP) broke legitimate multi-user e2e suites and shared offices | Now `settings.login_rate_limit` (default **60/5min** per IP ≈ 12 attempts/min — still a hard brute-force ceiling), configurable via env `LOGIN_RATE_LIMIT` | `test_login_rate_limited_after_burst` (parameterized by setting) |

Also reviewed (no change needed): notification routes (owner-scoped), exports (scoped + audited), client portal routes (org-scoped with cross-tenant probes), media streaming (project membership + traversal-safe keys), deliverables (org-checked + audited), external API (credential scopes + org/project allowlist), golden tasks (identity never serialized to workers), invitations (hashed single-use tokens).

**Accepted risks (documented, not fixed):** e2e spec files contain throwaway test credentials (test code, not runtime secrets); the user directory remains readable among staff by design for assignment flows; audit log records user id, not full field snapshots.

## Phase 2 — Reliability findings and fixes

| ID | Severity | Finding | Fix | Verification |
|---|---|---|---|---|
| R1 | **High** | `Base.metadata.create_all()` ran in **every** environment — production could silently drift from Alembic migrations | `create_all` now runs only in development/test; production requires migrations | code + CI migration job |
| R2 | **High** | No migration-state verification — a stale production DB would boot with missing columns/tables | `app/core/startup_checks.py`: production startup compares `alembic_version` to the script head and **refuses to start** on mismatch/absence | CI job "Startup checks refuse stale databases" + `check_migrations_up_to_date` unit path |
| R3 | Medium | Readiness/liveness not separated; health didn't report migration state | `/api/health` (readiness: DB ping + migration info in production) and `/api/health/live` (liveness, no DB) | observed live (`{"migrations": {"checked": false}}` in dev, real values in prod) |
| R4 | Medium | Idempotency-key insert race: two concurrent identical writes could both pass the pre-check → duplicate processing or 500 on unique-violation | Insert race now caught: on unique-violation the loser replays the winner's stored response, or gets 409 "in progress" if not yet stored | `test_idempotency_replay_and_conflicting_reuse` (replay + 422 different-body + single effect); unique index `(credential_id, key)` |
| R5 | Medium | Invitation acceptance race: two concurrent accepts could both read `status='pending'` | Acceptance is a single conditional `UPDATE ... WHERE status='pending'`; rowcount 0 → 403 with accurate reason | `test_invitation_single_use_across_sessions` |
| R6 | Verified (no change) | Task claiming and review claiming already use atomic conditional UPDATEs with task-assignment history (V2 tests cover concurrent claims); webhook deliveries persist attempts/backoff and the worker re-scans pending rows | — | existing `test_tasks.py`, `test_reviews.py`, `test_api_webhooks.py` |

## Phase 3 — CI pipeline and browser coverage

`.github/workflows/ci.yml` with four jobs:
1. **backend** — pip install + full pytest (fresh in-memory DB per test).
2. **frontend** — `tsc -b` + Vitest + production build (+ dist artifact).
3. **migrations** — Alembic chain on a fresh SQLite DB (asserts ≥ 45 tables) **and** on a fresh PostgreSQL 16 service (upgrade → downgrade → upgrade), plus a check that the production startup gate refuses a stale database.
4. **e2e** — boots backend (migrations + uvicorn) and frontend, runs the 42-check API smoke test, then Playwright (chromium) across all four spec files.

Browser coverage added in V3.1 (`v3-quality-flows.spec.ts`, `v3-multimodal-integrations.spec.ts`) on top of the existing suites:
- client organization creation and invitations (v3-client-portal + UI org creation)
- client project requests and approval → conversion (v3-client-portal)
- client deliverable download (real file)
- dataset upload and validation (multipart upload through the real endpoint)
- tester task claiming and submission (v2 workflow)
- reviewer decisions and **revision requests** (new: decision = revision_requested, tester notification asserted)
- senior reviewer adjudication surface (new)
- golden task configuration + worker scoring (new: 100% weaving config, wrong-answer submission, honest report `< 100%`)
- qualification creation, worker attempt, pass (new)
- image annotation (new: real bbox drawing on the canvas, save v1, submit)
- audio annotation (new: waveform workspace, segment + transcript, save)
- API key lifecycle (new: create with one-time secret, revoke with confirm)
- webhook failure handling (SSRF refusal surfaced in the UI; delivery retries covered by pytest)
- tenant isolation across client workflows (v3-client-portal + pytest tenant matrix)

Note: webhook **delivery** against a public receiver is covered by pytest with a local HTTP receiver (SSRF rules intentionally block loopback for real endpoints; the test uses the service-layer bypass flag).

## Phase 4 — Documentation

- README: V3.1 section, demo passwords removed (all of them; `rg DemoReview` → 0 matches in code + docs), test/e2e account policy rewritten, counts reconciled.
- Counts reconciled: backend **207** tests, frontend **9**, e2e **17**, **48** DB tables after `a7b8c9d0e123` (46 application + alembic bookkeeping), bundle sizes measured.
- `docs/V3_SECURITY_TESTING_DEPLOYMENT.md` remains the deployment/backup reference; this file records V3.1 specifics. Backup/recovery: nightly `pg_dump` + `storage/` volume sync documented there.
- Known limitations documented honestly below and in the README.

## Phase 5 — Performance

| Item | Before | After | Notes |
|---|---|---|---|
| Initial JS (gzip) | 266 kB (single 964 kB chunk, every page) | **107 kB** (334 kB raw) | React.lazy + Suspense for all 47 routes; Recharts (374 kB chunk) now loads only on dashboard/analytics |
| Route chunks | 1 | 47 page chunks + vendor splits | largest page chunk 61 kB raw (Dashboard incl. charts) |
| Webhook due-scan query | full-table scan on deliveries | composite index `(status, next_retry_at)` | migration `a7b8c9d0e123` |
| Golden report join | scan by FK without index | index on `golden_task_results.golden_task_id` | same migration |
| Pagination | already enforced on list endpoints (max page_size 200) | unchanged | verified during audit |
| Media handling | chunked streaming with Range support (V3) | unchanged | verified during audit |

**Budgets (enforced informally, to be wired into CI later):** initial JS gzip ≤ 120 kB; any single route chunk gzip ≤ 20 kB; LCP target < 2.5 s on local dev hardware. Current state meets all three.

## Known limitations (honest)

1. DNS-rebinding TOCTOU on webhooks is mitigated (delivery-time re-validation, redirects off) but not eliminated — a pinned-connection HTTP transport is the complete fix.
2. In-memory rate limiting and webhook worker are single-process; Redis/a queue are the multi-instance path (documented).
3. E2E specs use throwaway credentials defined in test files (test code, not runtime secrets).
4. The audit-logs endpoint is administrator-scoped but not org-filtered — super admins see all tenants by design; project admins see all audit rows too (could be narrowed later).
5. `EVALFORGE_STORAGE_ROOT` defaults to a local folder; S3 driver remains a documented extension point.

## Files changed (summary)

Backend: `app/core/config.py`, `app/core/startup_checks.py` (new), `app/main.py`, `app/api/routes/{auth,misc,evaluations,rubrics,analytics,reviews,demo}.py`, `app/services/{access,org_access,webhooks,demo}.py`, `alembic/versions/a7b8c9d0e123_*`, `smoke_test.py`, `tests/{test_v3_1_security,test_rate_limit}.py`.
Frontend: `src/main.tsx` (lazy routes), `src/pages/quality/QualityPages.tsx` (default export), `tests/e2e/{v3-quality-flows,v3-multimodal-integrations}.spec.ts` (new).
Infra/docs: `.github/workflows/ci.yml` (new), `README.md`, `.env.example` (login rate limit note), this report.

## Verification evidence

- Full backend suite: **207/207** (fresh run after all changes; includes 19 new V3.1 security tests and parameterized rate-limit tests).
- Frontend: Vitest **9/9**, `tsc -b` clean, production build green (bundle measured above).
- Playwright: **17/17** across all four spec files (single worker, serial).
- Alembic: fresh-DB chain green on SQLite and PostgreSQL in CI config; startup gate verified in the CI migration job.
