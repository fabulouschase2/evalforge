# EvalForge AI V3 — Feature Reference (Client Portal, Golden Tasks, Qualifications, Multimodal)

## Client Portal (`docs/V3_CLIENT_PORTAL.md` summary)

- **Roles**: client_owner (manage org/members/invitations), client_project_manager
  (requests, uploads, messages), client_viewer (read-only). Separate from internal roles.
- **Requests**: full request form (title, description, category, evaluation types,
  volume, languages, skills, dataset availability, delivery date, quality requirements,
  special instructions, attachments). Status flow: submitted → under_review →
  approved / rejected / more_info_required → converted. Admin actions require an
  explanation for reject/more_info; conversion creates a real project preserving all
  submitted fields and the full append-only admin history.
- **Uploads**: CSV/JSON/JSONL through the org-scoped endpoint with the standard
  validation/import report (valid/invalid/duplicate rows, per-row errors).
- **Monitoring**: sanitized dashboards — task pipeline counts, completion rate
  (`null` when no tasks, never fabricated), dataset versions, activity feed. No
  worker identities, no internal notes.
- **Messaging**: per-project thread; staff can post client-visible replies and
  internal notes (`is_internal` never leaves the server for client users).
- **Deliverables**: staff package approved results (JSON/CSV/JSONL) with per-row
  provenance (task id, record id, attempt, approved_at); downloads are org-checked
  and audited; sha256 checksums exposed.

## Golden Tasks (`docs/V3_GOLDEN_TASKS.md` summary)

- Known-answer probes stored with versioned immutable reference answers
  (`golden_task_versions`), scoring method + config, difficulty, explanation.
- Scoring methods: exact, variations, numeric_tolerance, single_label,
  multi_label (optional partial credit), contains_keywords. Preview endpoint for builders.
- Distribution: real Tasks woven into generated queues honoring percentage /
  fixed count / min spacing / difficulty mix. **Workers can never identify golden
  tasks**: `is_golden` is never serialized; reference answers are stripped from
  tester-facing task/workspace payloads.
- Scoring runs at submission time; results append to `golden_task_results` with
  the reference version, method, score, failure reasons.
- Alerts (indicators only, never auto-suspension, 24h dedupe): repeated failures,
  low accuracy, sudden decline, excessive speed. Reports: overall + per-difficulty
  + per-worker accuracy computed only from stored results (`None` + reason when empty).

## Qualifications (`docs/V3_QUALIFICATIONS.md` summary)

- Assessments: mcq / text_grading / coding / annotation_exercise / factuality /
  instruction_following / custom_rubric; time limits, attempt limits, passing
  scores, randomization flag, versioning (question edits bump the version).
- Attempts: start → save → submit; auto-grading for mcq/multi_select/numeric;
  text/code route to a manual grading queue (quality/staff) with notifications.
  Passing an assessment grants **verified** skills (vs self-reported, always
  distinguished).
- Eligibility: projects define requirements (assessment min-score, verified
  skills). Enforced in the task claim path (403 with unmet reasons). Admin
  overrides require a recorded reason.
- Worker surfaces: My Qualifications (take flow), skills page, performance page
  (submissions, golden accuracy, tier, recent feedback). Tiers: beginner →
  qualified (1 pass) → advanced (3) → specialist (5 + verified skill), evidence-based.

## Multimodal (`docs/V3_MULTIMODAL.md` summary)

- Media: magic-byte sniffed uploads (PNG/JPEG/GIF/WebP, MP4/WebM, WAV/MP3/OGG;
  200 MB), server-side probes (dimensions; WAV duration), per-project library,
  Range-aware authenticated streaming (chunked; never fully buffered).
- Image annotations: bbox/polygon/point + classification labels, normalized
  coordinates, versioned saves, undo/redo, zoom/pan, project label palettes.
- Video: player with frame stepping, event spans (start/end ms), per-frame shape
  capture, timeline. Audio: waveform (decodeAudioData), playback speeds,
  timestamped segments with transcript/speaker/language/emotion.
- Annotation submission creates a standard `Submission` → existing reviewer flow
  (blind review, revisions, adjudication) applies unchanged; annotations are
  versioned and pinned to the submission.
- Exports (permission-checked, audited): COCO JSON, CSV, native JSON for images;
  JSON (and CSV) for audio; JSON for video events.

## API & Webhooks (`docs/V3_API_REFERENCE.md` summary)

- Keys: `ef_`-prefixed secrets shown once, stored hashed (sha256) with prefix
  lookup; scopes list, optional org binding + project allowlist, expiry, rotate,
  revoke, last-used, per-request activity log, 120 req/min in-memory limiter (429).
- External surface `/api/ext/v1`: projects list, dataset create, bulk record
  ingestion (validation report), tasks list/create, approved results only.
  Auth = `X-API-Key` header. Idempotency via `Idempotency-Key` header
  (24h replay; same-key-different-body → 422). Writes dispatch webhooks.
- Webhooks: event subscription (11 event types), HMAC signature header
  `X-EvalForge-Signature: t=<unix>,v1=HMAC_SHA256(secret, "<t>.<body>")`,
  SSRF guard (scheme + IP-literal/DNS checks blocking private/loopback/link-local/
  metadata ranges at creation AND delivery), in-process delivery worker with
  exponential backoff (5 attempts), delivery history + replay + test send.
