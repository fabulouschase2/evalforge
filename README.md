# EvalForge AI

A professional **multi-tenant AI data collection, annotation, evaluation, quality-assurance and human-review platform**.

- **Administrators** collect data (CSV/JSON/JSONL uploads, manual entry, bulk paste), create fully configured projects, build versioned rubrics with dynamic evaluation forms, generate tasks and distribute them to testers.
- **Testers / annotators** work a task marketplace with exclusive claiming, complete dynamic rubric-driven forms with autosave, and receive structured reviewer feedback.
- **Reviewers** inspect submissions under configurable blind review, approve / reject / request revisions — decisions are append-only.
- **Senior reviewers (quality leads)** adjudicate disagreements, monitor reviewer consistency and tester quality, and measure inter-annotator agreement (raw + Fleiss' κ).
- **Automated evaluation engine** runs deterministic checks, exposes uncertainty with borderline detection, routes uncertain results to blind human review, and compares decisions against gold-standard labels (accuracy / precision / recall / F1 / Cohen's κ).
- Every action lands in an **audit trail**; every result is traceable to dataset version, rubric version and evaluator version.

## V3 — multi-tenant platform capabilities

V3 extends the platform into a complete AI data operations lifecycle:

- **Client organizations & portal** — independent client tenants with owner / project-manager / viewer roles; project requests with an admin approval queue and one-click conversion to projects; client dataset uploads with validation reports; per-project messaging (internal staff notes never reach clients); published deliverables with audited, checksummed downloads.
- **Golden tasks** — known-answer probes woven into task queues (configurable percentage / fixed count / spacing / difficulty mix) with six scoring methods, immutable versioned reference answers, quality alerts (indicators only), and accuracy reports. Workers can never identify golden tasks.
- **Worker qualifications** — assessment builder (MCQ auto-grading, free-text/code manual grading), attempt limits and time limits, verified-vs-self-reported skills, evidence-based tiers, and per-project eligibility gates enforced at task-claim time with recorded admin overrides.
- **Multimodal annotation** — image (bbox/polygon/point, undo/redo, zoom), video (timeline, event spans, frame capture) and audio (waveform, timestamped segments, transcripts) workspaces sharing the standard task/review/permission infrastructure; COCO/CSV/JSON exports.
- **External API & webhooks** — scoped API keys (hashed secrets, rotation, activity logs, rate limits), `/api/ext/v1` endpoints with idempotency keys, and HMAC-signed webhook deliveries with SSRF protection, retries and replay.
- **Unified analytics** — platform rollups and downloadable quality reports computed only from stored evidence (unavailable metrics are reported as unavailable, never fabricated).

See [`docs/V3_FINAL_REPORT.md`](docs/V3_FINAL_REPORT.md), [`docs/V3_ARCHITECTURE.md`](docs/V3_ARCHITECTURE.md) and [`docs/V3_PROGRESS.md`](docs/V3_PROGRESS.md) for the full V3 documentation and test results (backend 188/188, frontend 9/9, e2e 7/7, production build green).

**Philosophy:** automate objective checks, expose uncertainty, preserve human judgment, and make evaluation decisions reproducible.

---

## Table of contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Technology stack](#technology-stack)
4. [Feature walkthrough](#feature-walkthrough)
5. [Quick start](#quick-start)
6. [Environment configuration](#environment-configuration)
7. [Database setup](#database-setup)
8. [API documentation](#api-documentation)
9. [Testing](#testing)
10. [Example evaluation workflow](#example-evaluation-workflow)
11. [Demonstration data](#demonstration-data)
12. [Evaluation methodology](#evaluation-methodology)
13. [Known limitations](#known-limitations)
14. [Future improvements](#future-improvements)

---

## Overview

| Capability | What it does |
|---|---|
| Dataset management | CSV / JSON / JSONL import with column mapping, duplicate detection, missing-value reporting, invalid-row quarantine, immutable versioning |
| Rubric builder | Visual + JSON editor for weighted criteria, scoring scales, deterministic checks, thresholds and review policies — every save creates an immutable version |
| Evaluation engine | 14 deterministic check types, reference-based factuality heuristics, weighted scoring, decision confidence, borderline classification across 7 categories |
| Human review | Blind independent reviews, immutable submissions, adjudication when reviewers disagree |
| Analytics | Accuracy, precision, recall, F1, confusion matrix, Cohen's kappa (scikit-learn), Fleiss' kappa, raw-vs-chance-adjusted agreement |
| Audit trail | Every dataset import, rubric change, run execution, review submission and adjudication is recorded and traceable to dataset version + rubric version + evaluator version |

Every dashboard value comes from backend API responses. When the database is empty the UI shows an empty state and an explicit **"Load demonstration dataset"** action; demonstration values are always labeled `[DEMO]` and never presented as production measurements.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Browser                                                                 │
│  React 18 + TypeScript + Vite + Tailwind (dark enterprise UI)            │
│  TanStack Query · React Router · Recharts · Radix primitives             │
└───────────────▲──────────────────────────────────────────────────────────┘
                │  /api (dev: Vite proxy → :8000; prod: nginx proxy_pass)
┌───────────────┴──────────────────────────────────────────────────────────┐
│  FastAPI backend (Python 3.12)                                           │
│                                                                          │
│  api/routes/        auth · datasets · rubrics · evaluations · reviews    │
│                     analytics · audit/settings · projects · demo         │
│  core/              config (env) · security (JWT + bcrypt) · logging     │
│  services/          datasets (parse/validate/version) · rubrics          │
│                     (validate/version) · reviews (blind/adjudication)    │
│                     analytics (sklearn/scipy) · audit · demo seed        │
│  engine/            checks.py (14 deterministic rules)                   │
│                     factuality.py (reference-based claim analysis)       │
│                     scoring.py (weighted aggregate + confidence)         │
│                     borderline.py (uncertainty classification)           │
│                     runner.py (orchestration + immutable findings)       │
└───────────────▲──────────────────────────────────────────────────────────┘
                │  SQLAlchemy 2.0 (parameterized ORM)
┌───────────────┴──────────────────────────────────────────────────────────┐
│  PostgreSQL (docker-compose) / SQLite (local dev)  +  Alembic migrations │
└──────────────────────────────────────────────────────────────────────────┘
```

**Data model:** Users · Projects · Datasets → DatasetVersions → DatasetRecords · Rubrics → RubricVersions · EvaluationRuns → EvaluationResults → EvaluationFindings · ReviewAssignments → HumanReviews → Adjudications · AuditLogs · Settings. Foreign keys, uniqueness constraints and indexes throughout; rubric versions and dataset versions are append-only so historical runs stay reproducible.

## Technology stack

- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, Radix UI primitives, TanStack Query, React Router, React Hook Form, Zod, Recharts, Lucide icons
- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, pandas
- **Analytics:** scikit-learn, SciPy, NumPy
- **Testing:** Pytest (77 tests), Vitest + React Testing Library (9 tests), Playwright E2E
- **Infrastructure:** Docker, Docker Compose, environment-based configuration, structured logging

## Quick start

### Option A — Docker Compose (PostgreSQL + production-style build)

```bash
docker compose up --build
# frontend:  http://localhost:8080
# API docs:  http://localhost:8000/docs
```

### Option B — Local development (SQLite, lightweight)

```bash
# 1. Backend
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt     # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux
copy .env.example .env
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# 2. Frontend (second terminal)
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**, register an account (the first account becomes the **administrator**), then use **"Load demonstration dataset"** on the empty dashboard to see the full pipeline with clearly labeled demo data.

### Seeding demo data from the CLI

```bash
cd backend
.venv\Scripts\python -m app.seed_demo
```

## Environment configuration

Copy `backend/.env.example` to `backend/.env`. Never commit real secrets.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./evalforge.db` | Use `postgresql+psycopg://user:pass@host:5432/evalforge` in production |
| `SECRET_KEY` | dev value | JWT signing — **must** be changed in production |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` | JWT lifetime |
| `CORS_ORIGINS` | localhost:5173 | Comma-separated allowed origins |
| `MAX_UPLOAD_MB` | `25` | Upload size limit |
| `ENVIRONMENT` | `development` | `production` switches logs to JSON lines |

## Database setup

- **Local dev:** `alembic upgrade head` creates the SQLite schema. The app also auto-creates missing tables on startup as a dev convenience.
- **Docker/production:** the backend container runs `alembic upgrade head` against PostgreSQL before serving. Migrations live in `backend/alembic/versions/`.

## API documentation

Interactive OpenAPI docs are served at **`/docs`** (Swagger) and **`/redoc`** when the backend is running.

| Area | Endpoints |
|---|---|
| Auth & users | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `GET /api/auth/users`, `POST /api/auth/users`, `PUT /api/auth/users/{id}/role`, `PUT /api/auth/users/{id}/status` |
| Projects | `POST/GET /api/projects`, `GET/PUT /api/projects/{id}`, `POST /api/projects/{id}/archive`, `GET/POST /api/projects/{id}/members`, `DELETE /api/projects/{id}/members/{member_id}`, `POST/GET /api/projects/organizations` |
| Datasets & records | `POST /api/datasets`, `GET /api/datasets`, `GET /api/datasets/{id}`, `GET /api/datasets/{id}/records` (+status/category/language/search filters), `POST /api/datasets/{id}/records`, `POST /api/datasets/{id}/records/bulk`, `PATCH/DELETE /api/datasets/{id}/records/{rid}`, `POST /api/datasets/{id}/archive` / `restore`, `GET /api/datasets/{id}/export?format=json|csv`, `GET/PUT /api/datasets/{id}/custom-fields`, upload preview/commit, versions |
| Rubrics | `POST /api/rubrics`, `GET /api/rubrics`, `GET /api/rubrics/{id}`, `PUT /api/rubrics/{id}`, `GET /api/rubrics/{id}/versions`, `POST /api/rubrics/validate` (incl. evaluation-form validation), `DELETE /api/rubrics/{id}` |
| Evaluations | `POST /api/evaluations`, `GET /api/evaluations`, `GET /api/evaluations/{id}`, `GET /api/evaluations/{id}/results`, `GET /api/evaluations/{id}/results/{result_id}`, `POST /api/evaluations/{id}/run` |
| Tasks | `POST /api/tasks/generate`, `POST /api/tasks/manual`, `POST /api/tasks/bulk-manual`, `GET /api/tasks` (+filters), `GET /api/tasks/available`, `GET /api/tasks/mine`, `GET /api/tasks/{id}`, `POST /api/tasks/{id}/claim` (atomic) / `start` / `assign` / `reassign` / `release` / `pause` / `unpause` / `cancel`, `POST /api/tasks/maintenance/expire-assignments` |
| Submissions | `POST /api/submissions/tasks/{id}/draft` (autosave), `POST /api/submissions/tasks/{id}/submit`, `GET /api/submissions/tasks/{id}/workspace`, `GET /api/submissions/mine`, `GET /api/submissions`, `GET /api/submissions/{id}` |
| Reviews | `GET /api/submissions/review-queue`, `POST /api/submissions/{id}/claim-review` (atomic), `POST /api/submissions/{id}/review` (append-only) |
| Quality | `GET /api/quality/overview`, `GET /api/quality/adjudication-queue`, `POST /api/quality/submissions/{id}/adjudicate`, `GET /api/quality/reviewer-consistency`, `GET /api/quality/tester-quality`, `GET /api/quality/agreement`, `GET /api/quality/sample` |
| Notifications | `GET /api/notifications`, `GET /api/notifications/unread-count`, `POST /api/notifications/{id}/read`, `POST /api/notifications/read-all` |
| Exports | `GET /api/exports/tasks?format=csv|json`, `GET /api/exports/submissions?format=csv|json` |
| Automated-result flow | `GET /api/reviews/queue`, `POST /api/reviews/assign`, `GET /api/reviews/{id}`, `POST /api/reviews/{id}/submit`, `GET /api/reviews/results/{id}/reviews`, `POST /api/reviews/results/{id}/adjudicate` |
| Analytics | `GET /api/analytics/overview`, `GET /api/analytics/admin-overview`, `GET /api/analytics/metrics`, `GET /api/analytics/agreement`, `GET /api/analytics/confusion-matrix` |
| Audit / settings | `GET /api/audit-logs` (+action/entity filters), `GET/PUT /api/settings` |
| Demo | `POST /api/demo/load` |

**Role-based access:** six platform roles — `super_admin` (everything), `project_admin` / `project_manager` (manage their projects: data, tasks, membership), `tester` (task marketplace + submissions in their projects), `reviewer` (submission reviews), `senior_reviewer` (quality monitoring + adjudication). Capabilities are enforced **server-side** in every route, and **project membership** is checked for every task, submission and dataset access — a tester of project A gets `403` on project B regardless of what the client sends. Login and registration are rate-limited.

## Testing

```bash
# Backend — 129 tests (auth/roles, project isolation, dataset collection, task
# lifecycle incl. concurrent claiming, submission validation, blind reviews,
# immutability, adjudication, agreement/kappa, notifications, exports, audit, RBAC)
cd backend
.venv\Scripts\python -m pytest

# API smoke test against a running server (42 checks, full acceptance pipeline)
.venv\Scripts\python smoke_test.py

# Frontend — Vitest + React Testing Library
cd frontend
npm test

# E2E — full multi-role workflow through the real UI (requires dev servers running)
npx playwright install chromium
npx playwright test
```

## Example evaluation workflow

1. **Register / sign in** — the first account becomes the super admin.
2. **Create a project** — type, client/organization, instructions, deadline, quality requirements, blind-review policy. Add testers and reviewers as members.
3. **Collect data** — import CSV/JSON/JSONL (preview → column mapping → duplicate/invalid report → commit as an immutable version), add records manually or by pasting JSON batches, define custom per-dataset fields.
4. **Build a rubric** — weighted criteria with deterministic checks **plus an evaluation form** (yes/no, single/multi-select, numeric, likert, free text, evidence lists, conditional questions). Validate, save as version 1.
5. **Generate tasks** from dataset records (or create manually/in bulk) — published to the project's task marketplace.
6. **Testers claim tasks** (atomic exclusive claim — two workers can never share one), work the dynamic form in the task workspace with autosave, and submit (validated against the rubric form, attempt-limited).
7. **Reviewers** work the blind review queue: approve / reject / request revisions with comments, flags and escalations. Revision requests return the task to the tester for a new attempt.
8. **Disagreements** (conflicting reviewer decisions) go to the **senior reviewer's adjudication queue** — the final decision is recorded separately; original decisions are never modified.
9. **Analytics** — admin overview (task pipeline, daily submissions, tester/reviewer performance), quality monitoring (disagreement rate, reviewer consistency vs adjudications, Fleiss' κ), gold-label accuracy/precision/recall/F1/Cohen's κ for the automated engine. CSV/JSON exports with permission checks.
10. **Notifications & audit** — every assignment, submission, decision and adjudication notifies the right people and lands in the audit trail.

The original **automated evaluation pipeline** (dataset + rubric + deterministic engine → borderline routing → blind human review of automated results) remains fully available alongside this workflow — see the [Evaluation methodology](#evaluation-methodology) section.

## Demonstration data

`POST /api/demo/load` (or the dashboard button, or `python -m app.seed_demo`) seeds a complete, **clearly labeled** pipeline:

- 18 support-domain records covering: clearly correct, clearly incorrect, partially correct, evidence-thin, context-misleading, ambiguous instructions, truncated responses, JSON format cases, hedged claims, and two records **without reference material** (one actually wrong — the system must refuse to auto-fail it).
- Gold labels + explanations on every record.
- One evaluation run executed with the demo rubric (≈4 pass / 6 fail / 8 borderline spanning 6 borderline categories).
- Two demo reviewers (`reviewer.one@evalforge.demo`, `reviewer.two@evalforge.demo`, password `DemoReview!23`) with planted agreement, **two disagreement items awaiting adjudication**, and pending assignments left in the queue so the review workflow can be exercised by hand.

Everything demo is named `[DEMO]`, flagged `is_demo`, and badged in the UI.

### Seeded accounts used in tests / E2E

| Account | Password | Role |
|---|---|---|
| `admin@evalforge.dev` | `AdminPass!23` | super_admin (first registered user) |
| `reviewer.one@evalforge.demo` | `DemoReview!23` | reviewer |
| `reviewer.two@evalforge.demo` | `DemoReview!23` | reviewer |

## Evaluation methodology

EvalForge deliberately separates three kinds of judgment:

| Layer | Nature | Examples |
|---|---|---|
| **Deterministic checks** | Objective, reproducible rules over the response text | `format_regex`, `json_valid`, `sentence_count`, `required_keywords`, `forbidden_patterns`, length limits, `required_fields`, truncation detection |
| **Reference-based factuality heuristics** | Lexical/numeric similarity signals against reference material | claim support (supported / contradicted / unsupported / needs verification), numeric conflict detection, citation presence. These are **heuristics, not semantic verification** — keyword matching cannot prove factual accuracy |
| **Human assessments** | Ground truth | Blind criterion scores, labels, reasoning, uncertainty flags, adjudication |

**Borderline detection** routes uncertainty to humans instead of guessing. Categories: `partially_correct`, `evidence_insufficient`, `context_misleading`, `ambiguous_instruction`, `conflicting_evidence`, `reviewer_disagreement`, `uncertain_automated_decision`. Triggers include confidence below threshold, aggregate score within the passing-threshold margin, mixed numeric evidence, missing reference data, and ambiguity markers in the prompt. A borderline result **keeps its automated label** but is flagged `needs_review` — the system never silently converts low confidence into "incorrect".

**Metrics honesty:** accuracy/precision/recall/F1/confusion matrix are computed **only** when records carry gold pass/fail labels; otherwise the API returns an explicit `insufficient_reason`. Cohen's κ is omitted when either axis has one class. Fleiss' κ returns `None` for degenerate distributions (e.g. all raters use one label) rather than a fake 1.0. Raw percentage agreement and chance-adjusted kappa are always reported side by side.

**Traceability:** every finding stores `rule_id`, input excerpt, output, pass/fail/inconclusive, evidence, explanation, severity, `evaluator_version` and `rubric_version`. Completed runs cannot be re-run in place (create a new run instead), and datasets/rubrics referenced by runs cannot be deleted.

## Known limitations

- The evaluation engine is fully deterministic. Model-assisted (LLM judge) evaluation is intentionally **not** wired to any external API; a provider interface is the natural extension point (`app/engine/`), so the core system never requires external API keys.
- Factuality analysis is lexical/numeric (token overlap, number conflicts, negation contrast, hedging). It cannot verify semantics and will miss paraphrase-level contradictions; such cases route to human review by design.
- Evaluation runs execute synchronously — very large datasets (tens of thousands of records) would benefit from a task queue.
- Fleiss' kappa requires the same number of raters on every item; uneven reviewer coverage reports `None`.
- The audit log records user id, not a full historical snapshot of every entity field.
- Single-workspace tenancy: projects group work, but there is no per-workspace isolation of users.

## Future improvements

- Pluggable model-assisted evaluators behind the same finding schema (with explicit "model-assisted" labeling and separate confidence treatment).
- Async evaluation execution (worker queue) with live progress in the UI.
- Agreement-weighted reviewer reliability (Krippendorff's α), per-reviewer calibration.
- Dataset diffing between versions; sampling strategies for review assignment.
- Exportable evaluation reports (PDF/HTML) directly from run results.
- OIDC/SSO integration and per-project role scoping.

---

**Demo reviewers** (created by the demo seed): `reviewer.one@evalforge.demo` / `reviewer.two@evalforge.demo`, password `DemoReview!23`.
