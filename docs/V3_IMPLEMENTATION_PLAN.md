# EvalForge AI V3 — Technical Implementation Plan

**Status:** Active plan (Phase 0 approved by audit)
**Baseline:** see `docs/V3_INITIAL_AUDIT.md` — V2 verified working (131/131 backend, 9/9 frontend,
42/42 smoke, 3/3 e2e, build ✓).

---

## 1. Guiding principles

1. **Extend, never rebuild.** Every new feature reuses the v2 models/services listed in the audit
   reuse map. No duplicate tables for existing concepts.
2. **Isolation at the query layer.** Multi-tenancy is enforced where data is fetched, never in the
   UI. Every client-scoped query filters by organization explicitly; every test suite includes
   cross-tenant probes.
3. **Append-only history** for anything that must stay reproducible: reference answers, review
   decisions, adjudications, qualification results, webhook deliveries, audit events.
4. **Honest metrics.** Metrics computed only from stored evidence; unavailable metrics render as
   unavailable with a reason; demo data is always labeled.
5. **SQLite-dev / PostgreSQL-prod compatible migrations** (batch_alter_table for every SQLite
   branch), additive-only, data-preserving.
6. **No feature is "done" until its backend tests + frontend wiring + a real browser check exist.**

---

## 2. Architecture changes (overview)

```
backend/app/
  models/            + org.py (extension), client.py, golden.py, qualification.py,
                       media.py, annotation.py, api_integration.py
  api/routes/        + organizations.py, client_portal.py, golden_tasks.py,
                       qualifications.py, media.py, annotations.py, api_keys.py,
                       external.py, webhooks.py
  services/          + org_access.py (org scoping helpers), client_portal.py,
                       golden.py (scoring engine), qualifications.py (grading),
                       eligibility.py, media_storage.py (local/S3 abstraction),
                       webhooks.py (dispatcher + signer + SSRF guard),
                       idempotency.py, metrics.py (golden/quality calculators)
  core/              + api_auth.py (API-key authentication & scopes)
frontend/src/
  pages/client/      dashboard, requests, projects, datasets, messages, deliverables
  pages/admin/       clientOrgs, projectRequests, goldenTasks, qualifications,
                     apiKeys, webhooks
  pages/tester/      qualifications, skills, performance
  pages/quality/     goldenMonitoring, qualificationResults
  pages/annotate/    ImageAnnotation, VideoAnnotation, AudioAnnotation workspaces
  components/annotation/  shared canvas/player/waveform primitives
```

## 3. Database changes (by phase)

All via Alembic; every migration additive (new tables or nullable/defaulted columns).

### Phase 1 — Multi-tenant foundations
- `organizations`: + `slug` (unique), `status` (active/suspended), `contact_email`, `settings` (JSON).
- **New** `organization_members`: org_id FK, user_id FK, role (`client_owner|client_project_manager|
  client_viewer`), unique(org,user). Internal users may also be listed for liaison purposes.
- **New** `organization_invitations`: org, email, role, token, status, invited_by, expires_at.
- `users`: no new columns (roles stay in `role`); client role constants added to `UserRole`.
- **New** `project_access` policy: `projects.organization_id` becomes the tenant boundary for
  client users (nullable = internal-only project, invisible to clients).
- Indexes: org_id on projects/datasets; (user_id) on organization_members.
- Fix: `requirements.txt` += `psycopg[binary]`.

### Phase 2 — Client Portal
- **New** `project_requests`: org_id, submitted_by, title, description, category, evaluation types,
  expected volume, languages, skills, dataset_availability, expected_delivery, quality_requirements,
  special_instructions, attachments (JSON), status (`draft|submitted|under_review|more_info_required|
  approved|rejected|converted`), admin response, converted_project_id, timestamps.
- **New** `client_messages`: project_id, org_id, sender_id, sender_side (`client|staff`), body,
  attachment, is_internal (staff-only note), read_at, created_at.
- **New** `deliverables`: project_id, created_by, label, dataset_version_id (nullable),
  export_format, file_path, record_count, checksum, published_at; downloads logged to audit.
- Client dataset uploads reuse Dataset services with `uploaded_by_role='client'` provenance field
  on Dataset (nullable addition).

### Phase 3 — Golden Tasks
- **New** `golden_tasks`: project_id, source_record_id (nullable FK dataset_records), title, payload
  (JSON question content), reference_answer (JSON), accepted_variations (JSON), scoring_method
  (`exact|variations|numeric_tolerance|single_label|multi_label|rubric|custom`), scoring_config
  (JSON: tolerance, labels, weights), explanation, difficulty, version, is_active, created_by.
- **New** `golden_task_versions`: append-only reference answer history.
- **New** `golden_task_results`: golden_task_id, task_id, submission_id, worker_id, project_id,
  scored_answer, score (0..1), passed, failure_reasons (JSON), scoring_method, scored_at.
  Inserted automatically when the submission's task is a golden task.
- `projects` + golden config JSON column (`golden_task_config`: percentage / fixed count / spacing /
  difficulty mix), nullable.
- `users`/stats: no columns — golden stats computed by query from `golden_task_results`.

### Phase 4 — Worker Qualifications
- **New** `qualification_assessments`: title, description, assessment_type (mcq/text_grading/
  annotation_exercise/custom_rubric...), skill_tags (JSON), time_limit_minutes, max_attempts,
  passing_score, randomize_questions, questions (JSON, versioned via separate table), status,
  project_id (nullable = platform-wide), created_by, version.
- **New** `qualification_questions`: assessment_id, order, type (`mcq|multi_select|numeric|text|
  code|annotation_ref`), prompt, options (JSON), correct_answer (JSON), points, explanation.
- **New** `qualification_attempts`: assessment_id, worker_id, status (`not_started|in_progress|
  submitted|passed|failed|under_review|expired`), score, answers (JSON), auto_graded, graded_by,
  started_at, submitted_at, expires_at.
- **New** `worker_skills`: user_id, skill, source (`self_reported|verified`), evidence
  (assessment_id / admin grant), level, verified_by, verified_at.
- **New** `worker_tiers`: user_id, tier (`beginner|qualified|advanced|specialist`), computed_from
  (JSON evidence summary), updated_at — or computed on read; stored table chosen for eligibility
  queries and history.
- `projects` + `eligibility_requirements` JSON column (required assessments min scores, verified
  skills); **new** `project_eligibility_overrides`: project_id, user_id, granted_by, reason.

### Phase 5–7 — Multimodal annotation
- **New** `media_assets`: project_id, uploader_id, media_type (`image|video|audio`), filename,
  storage_key, mime_type, size_bytes, width/height/duration_seconds (nullable, filled on inspect),
  checksum (dedupe), status, created_at.
- **New** `image_annotations`: media_asset_id, task_id, submission_id, worker_id, shapes (JSON:
  [{type: bbox|polygon|point, label, points normalized 0..1, …}]), labels (JSON), image_width/
  height captured at annotation time, version, created_at.
- **New** `video_annotations`: media_asset_id, task_id, submission_id, worker_id, events (JSON:
  [{label, start_ms, end_ms, frames: [{time_ms, shapes}]}]), frame_sampling config, version.
- **New** `audio_annotations`: media_asset_id, task_id, submission_id, worker_id, segments (JSON:
  [{start_ms, end_ms, transcript, speaker, language, emotion, labels}]), version.
- Media storage: `services/media_storage.py` with local-disk driver (dev) + S3-compatible driver
  interface (prod, env-configured); uploads validated (mime sniff, size limits, extension
  allowlist); served through an authenticated streaming endpoint — never static public files.

### Phase 8 — API & Webhooks
- **New** `api_credentials`: name, key_prefix, key_hash (sha256), scopes (JSON list), org_id
  (nullable), project_ids (JSON), expires_at, last_used_at, created_by, revoked_at, status.
- **New** `api_request_log`: credential_id, method, path, status_code, ip, created_at (activity view).
- **New** `webhook_endpoints`: org_id/project scope, url, secret_hash, events (JSON), is_active,
  created_by; **new** `webhook_deliveries`: endpoint_id, event_type, payload JSON, signature,
  attempts, status (`pending|delivered|failed|disabled`), next_retry_at, response_code, error,
  delivered_at. Retry with exponential backoff via background thread worker.
- **New** `idempotency_keys`: key (unique per credential), endpoint, request_hash, response_status,
  response_body, created_at.
- SSRF guard: URL validation (scheme http/https, IP-literal/private/loopback/link-local/metadata
  ranges blocked, DNS resolve + re-check).

### Phase 9 — Unified analytics
- No new tables; analytics services extended (golden-task accuracy, qualification pass rates,
  org-level rollups, worker-facing own-stats). CSV/JSON export endpoints.

## 4. Backend service & API design (new endpoints by phase)

Permissions: existing `RoleChecker` extended with client roles; all client routes additionally
scoped by `org_access.py` helpers (`require_org_member(user, org_id, roles)`,
`org_scoped_query(...)`). Every external API route authenticates via `core/api_auth.py`
(`X-API-Key` header → `api_credentials` hash lookup → scope check → project restriction check →
rate-limit check), never via JWT.

- **Phase 1:** `GET/POST /api/organizations`, `GET/PUT /api/organizations/{id}`,
  `GET/POST/DELETE /api/organizations/{id}/members`, `POST .../invitations`, `POST .../invitations/accept`,
  `GET /api/auth/me` extended with `organizations` list.
- **Phase 2:** `/api/client/*` — dashboard stats, requests CRUD + admin queue + convert,
  project monitoring (sanitized), dataset upload (preview/commit reuse), messages thread,
  deliverables list/download (audited), staff-side publish-deliverable.
- **Phase 3:** `/api/golden-tasks` CRUD + import + versions; `/api/projects/{id}/golden-config`;
  scoring inside submission path (service hook); `/api/quality/golden-report`,
  `/api/quality/golden-alerts`; worker results appear in submission responses without revealing
  golden identity at claim time.
- **Phase 4:** `/api/qualifications` CRUD(+questions), `/api/qualifications/{id}/attempts` start/
  save/submit, grading service, `/api/quality/qualifications` review queue (manual grading),
  `/api/workers/me/skills`, `/api/workers/me/performance`, project eligibility config + check in
  task claim path, overrides endpoint.
- **Phase 5–7:** `/api/projects/{id}/media` upload/list; `/api/media/{id}` streaming (auth,
  range requests for video/audio); `/api/tasks/{id}/annotation` get/put per modality (normalized
  coords); exports `/api/exports/annotations/{media|task}?format=coco|yolo|csv|json`.
- **Phase 8:** `/api/admin/api-keys` CRUD/rotate/revoke + activity; external `/api/ext/v1/*`
  (projects/datasets/records/tasks/submissions/results) with scopes+idempotency;
  `/api/admin/webhooks` CRUD + `/api/admin/webhooks/{id}/deliveries` + replay;
  `/api/ext/v1/webhooks/test`.
- **Phase 9:** `/api/analytics/platform`, `/api/analytics/client`, `/api/analytics/worker/me`,
  `/api/analytics/quality-report` (+exports).

## 5. Frontend pages (by phase)

Role-scoped navigation arrays extended per spec (ADMIN/CLIENT/TESTER/REVIEWER/QUALITY LEAD).
Every page: loading/empty/error states, toasts, confirm dialogs, pagination where relevant.

- Phase 1: Organization management (admin), organization members UI.
- Phase 2: Client shell (separate layout for client roles), client dashboard, project request form
  + list, client projects + monitoring, client datasets (upload wizard reuse), messages,
  deliverables; admin: requests queue + approve/reject/convert, client orgs.
- Phase 3: Admin/quality golden task management, golden config in project settings, quality
  monitoring screens (golden report, alerts), CSV/JSON import UI.
- Phase 4: Assessment builder (admin), worker assessment-taking UI, results review (quality lead),
  worker skills/profile/performance pages, eligibility editor in project settings.
- Phase 5–7: Media library (admin), image annotation workspace (canvas, zoom/pan, bbox/polygon/
  point, undo/redo, label palette), video workspace (player, timeline, frame stepping, event spans),
  audio workspace (waveform canvas, segments, transcript editor), reviewer annotation inspection,
  annotation exports.
- Phase 8: API key management UI (secret shown once), webhook management + delivery history/replay.
- Phase 9: Unified analytics screens per role.

## 6. Role & permission changes

New roles in `UserRole`: `client_owner`, `client_project_manager`, `client_viewer`.
- Client roles are **not** members of internal project roles; their access derives from
  organization membership + `project.organization_id` and is read-mostly (except uploads/messages).
- Access matrix (summary; full matrix in `docs/V3_PERMISSIONS.md` at Phase 2):
  - client_owner: org management, requests, uploads, projects read, deliverables, messages.
  - client_project_manager: requests, uploads, projects read, messages, deliverables read.
  - client_viewer: read-only projects/deliverables/notifications.
- Internal staff: unchanged capabilities + new admin queues (requests, golden, qualifications, API,
  webhooks). Testers gain qualification/self-skill routes (self-scoped only).
- API credentials: explicit scope list; can never bypass org scoping (credentials are org-bound).

## 7. Multi-tenant isolation enforcement points

1. All client-route queries filtered by `organization_members` of current user.
2. All project fetches for client users verify `project.organization_id ∈ user orgs`.
3. Worker/reviewer access continues to require `project_members` rows (unchanged).
4. Media endpoints authorize via project membership (workers) or org ownership (clients).
5. External API: credential → org scope → project allowlist, then same rules as (4).
6. Deliverable download: org check + audit event.
7. Dedicated pytest module `test_tenant_isolation.py` runs an A-vs-B matrix (IDs swapped) and fails
   on any leak. Webhook SSRF unit tests included.

## 8. Background processing

Lightweight in-process background worker (`threading` + queue, started in FastAPI lifespan,
dormant when empty) for: webhook deliveries + retries, golden-task batch scoring, media
post-inspect (dimensions/duration via header parse), and large import finalization where needed.
Rationale: no external broker dependency locally; interface kept swappable for Celery in prod.
Documented honestly as single-process (scales behind more uvicorn workers).

## 9. Testing strategy

- Backend pytest (target: keep 131 green + add per-phase suites, cross-tenant matrix, API auth,
  webhook signer/SSRF, scoring engines, eligibility gating, annotation coordinate math).
- Frontend Vitest for new shared components (scoring, validation, coordinate utils) + page smoke.
- Playwright e2e: extend `full-workflow.spec.ts` with golden-task + qualification + client portal +
  annotation happy paths (separate specs; keep v2 spec untouched and green).
- `smoke_test.py`: extend with V3 endpoint checks (idempotent on re-run).
- Manual browser verification per phase via dev servers + screenshots to `docs/screenshots/`.

## 10. Implementation phases (execution order & gates)

| Phase | Scope | Gate to proceed |
|---|---|---|
| 0 | Audit + this plan (done) | Audit written; baseline green |
| 1 | Orgs/members/client roles/tenancy + psycopg fix | Isolation suite green; v2 suite green |
| 2 | Client portal end-to-end | Client journey passes in browser; isolation suite extended |
| 3 | Golden tasks | Scoring unit tests + hidden-identity test + queue insertion test |
| 4 | Qualifications & eligibility | Assessment lifecycle tests + claim-gate test |
| 5 | Image annotation | Save/review/export tests + browser annotation check |
| 6 | Video annotation | Timestamp accuracy test + streaming endpoint test |
| 7 | Audio annotation | Segmentation/timestamp test + waveform UI check |
| 8 | API keys, external API, webhooks | Scope/rate/idempotency/SSRF/signature tests |
| 9 | Unified analytics | Metric-honesty tests (unavailable ≠ invented) |
| 10 | Hardening, regression, docs, deployment | Full suite + build + e2e + screenshots |

After every phase: append `docs/V3_PROGRESS.md` entry (completed / in-progress / outstanding /
test results / known issues / next actions) and run the full regression trio
(pytest, vitest, production build).

## 11. Key engineering decisions (documented now)

1. **Client identities live in `users`** (role = client_*) + `organization_members` — avoids a
   parallel auth system; JWT/`get_current_user` unchanged. Client users never appear in worker
   lists because every worker surface filters by internal roles.
2. **Golden tasks are real Tasks** inserted into queues (not a shadow queue) so claiming, timing,
   and review flow stay uniform; their scoring happens at submission time via service hook; identity
   hidden from worker payloads (`is_golden` never serialized to testers).
3. **Annotations stored normalized (0..1)** with image dims captured per annotation → resize-safe;
   export converters materialize absolute pixel/COCO/YOLO values on demand.
4. **API keys: random 32-byte secret, shown once, stored as sha256 hash** with a `ef_` prefix +
   key_prefix for lookup; constant-time comparison; per-credential rate limiting (in-memory token
   bucket, documented limitation for multi-instance prod → Redis recommended).
5. **Webhook payloads signed** `sha256=HMAC(secret, timestamp.body)` header style
   (Stripe-like: `X-EvalForge-Signature: t=…,v1=…`); 5 attempts exponential backoff; SSRF guard on
   endpoint creation AND delivery.
6. **Idempotency:** `Idempotency-Key` header honored on external POSTs; response replayed for
   24h-window duplicates (stored response body + status).
7. **Email:** notification service gains an email channel guarded by env config
   (`SMTP_HOST` etc.); without config, emails are skipped and logged as "email disabled" — never
   simulated.
8. **Media storage abstraction:** `local://` driver default (dev), `s3://` driver via env
   (`MEDIA_STORAGE_URL`, `S3_*`); signature-style protected URLs implemented for local driver via
   short-lived HMAC tokens; documented that S3 driver requires real bucket config before use.

## 12. Backward compatibility guarantees

- All v2 routes, payloads and statuses unchanged; new capabilities are additive endpoints/columns.
- v2 tests untouched and must stay green at every gate.
- `organizations` with NULL member rows behave exactly as v2 (internal-only visibility rules).
- Existing demo data remains labeled and separated.
