# EvalForge AI V3 — Architecture, Database & Permissions

## Architecture overview

EvalForge V3 extends the V2 FastAPI + React platform into a multi-tenant AI data
operations platform. Nothing from V2 was rebuilt or removed; every new capability
reuses the existing project/task/submission/review/permission infrastructure.

```
Browser (React 18 + TS + Vite, role-scoped navigation)
  /client/*          client portal (org-scoped)
  /tasks/:id         dynamic form OR image/video/audio annotation workspace
  /golden-tasks, /qualifications, /multimodal, /integrations, ...
        │  /api (JWT bearer; X-API-Key only under /api/ext/v1)
FastAPI
  routes/            auth · organizations · client_portal · projects · datasets ·
                     collection · rubrics · evaluations · tasks · submissions ·
                     reviews · quality · golden_tasks · qualifications · media ·
                     api_keys · external · analytics · notifications · exports ·
                     demo · misc
  services/          access (project ACL) · org_access (tenant ACL) ·
                     client_portal · golden (scoring/distribution/alerts) ·
                     qualifications (grading/eligibility) · multimodal (validation/
                     exports) · webhooks (signing/SSRF/worker) · notifications ·
                     file_storage · datasets · rubrics · reviews · analytics · audit
  core/              security (JWT) · api_auth (X-API-Key scopes) · ratelimit · config
SQLAlchemy 2.0 → SQLite (dev) / PostgreSQL (prod, psycopg)
Background: in-process webhook delivery worker (thread, exponential backoff)
```

## Multi-tenancy model

- `users` (single table) carry either internal roles (super_admin, project_admin,
  project_manager, tester, reviewer, senior_reviewer) or client roles
  (client_owner, client_project_manager, client_viewer).
- Client capabilities derive exclusively from `organization_members` rows +
  `projects.organization_id`; enforced at the query/service layer
  (`services/org_access.py`, `services/access.py`), never in the UI.
- `projects.organization_id IS NULL` ⇒ internal-only project, invisible to clients.
- Cross-tenant probes are automated in `tests/test_tenant_isolation.py` and
  `tests/test_client_portal.py` (ID-swapping across two organizations).

## Database (48 tables after migration chain `4bfc767ebcea → f6c9d7e2f458`)

| Domain | Tables |
|---|---|
| V2 core | users, organizations, projects, project_members, datasets, dataset_versions, dataset_records, rubrics, rubric_versions, rubric_templates, evaluation_runs/results/findings, tasks, task_assignments, submissions, submission_reviews, submission_adjudications, review_assignments, human_reviews, adjudications, notifications, audit_logs, settings |
| V3 tenancy | organization_members, organization_invitations |
| V3 client portal | project_requests, client_messages, deliverables |
| V3 golden tasks | golden_tasks, golden_task_versions, golden_task_results, quality_alerts; tasks.is_golden/golden_task_id; projects.golden_task_config/eligibility_requirements |
| V3 qualifications | qualification_assessments, qualification_questions, qualification_attempts, worker_skills, project_eligibility_overrides |
| V3 multimodal | media_assets, image_annotations, video_annotations, audio_annotations; tasks.media_asset_id |
| V3 integrations | api_credentials, api_request_logs, webhook_endpoints, webhook_deliveries, idempotency_keys |

Migrations are additive and idempotent (exist-checks) so they are safe on both
fresh databases and dev databases where `create_all` ran first. V2 rows keep
working: every new column is nullable/defaulted.

## Provenance & immutability

- Append-only: `submission_reviews`, `submission_adjudications`,
  `golden_task_versions`, `golden_task_results`, `client_messages`,
  `webhook_deliveries`, `audit_logs`.
- Every final result traces to: organization → project → dataset version → record
  → task → assignment → submission (attempt) → reviews → adjudication → export
  (deliverable stores `dataset_version_id`, sha256, download audit).
- Annotations are versioned rows pinned to submission ids; coordinates normalized
  so exports stay exact.

## Permission matrix (summary)

| Capability | super_admin | project_admin | project_manager | tester | reviewer | senior_reviewer | client_owner | client_pm | client_viewer |
|---|---|---|---|---|---|---|---|---|---|
| Manage users/roles | ✓ | — | — | — | — | — | — | — | — |
| Organizations | manage | manage | view | — | — | — | own org | own org | own org (read) |
| Projects | all | administered | administered | member only | member only | all | org read | org read | org read |
| Datasets/records | all | administered | administered | member read | member read | all | own org read/write* | own org write* | own org read |
| Tasks (claim/submit) | — | — | — | member + eligible | — | — | — | — | — |
| Reviews / adjudication | ✓ | review | — | — | review | adjudicate | — | — | — |
| Golden tasks (config/CRUD) | ✓ | administered | administered | hidden | hidden | hidden | hidden | hidden | hidden |
| Qualifications (build/grade) | ✓ | administered | administered | take own | — | grade | — | — | — |
| Media/annotations | all | administered | administered | member annotate | review | all | own org read | — | own org read |
| API keys / webhooks | ✓ | — | — | — | — | — | — | — | — |
| Client requests (queue) | ✓ | ✓ | view | — | — | — | create | create | read |

\* client dataset uploads create datasets attached to their organization's projects.

Enforcement is server-side on every route (`RoleChecker`, `acl.*`, `org_access.*`,
`ApiContext.require_scope`); frontend route guards are UX only.

## Data-flow guarantees for clients

Client-facing responses are built by dedicated serializers
(`services/client_portal.py`) that exclude: worker/reviewer identities, private
performance data, internal notes (`ClientMessage.is_internal`), internal-only
projects, and golden-task identities/answers.
