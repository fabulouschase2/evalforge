# EvalForge AI V3 — Progress Log

Updated after every phase. Newest entries at top.

---

## 2026-11-14 — V3 COMPLETE (Phases 0–10 + final verification)

### Final verification results
- Backend pytest: **188/188** (131 V2 + 57 V3)
- Frontend Vitest: **9/9** · production build: **success**
- Playwright: V2 workflow **3/3** + V3 client portal **4/4**
- Alembic chain on fresh DB: 7 migrations → 46 tables, clean; live dev DB migrated
  in-place with data preserved

### Completed in Phase 10
- `.env.example` extended (storage root, SMTP, scaling notes).
- Full migration chain re-verified on a fresh DB.
- Playwright V3 spec `v3-client-portal.spec.ts` (4 tests: org creation UI →
  request UI → approve/convert UI → monitoring + real deliverable download).
- Documentation suite: V3_ARCHITECTURE, V3_FEATURES, V3_SECURITY_TESTING_DEPLOYMENT,
  V3_FINAL_REPORT, V3_CHANGELOG + pointer docs (V3_CLIENT_PORTAL, V3_GOLDEN_TASKS,
  V3_QUALIFICATIONS, V3_MULTIMODAL, V3_API_REFERENCE, V3_PERMISSIONS, V3_DATABASE).
- Screenshots 01–09 in `docs/screenshots/` covering admin overview (live platform
  panel), client dashboard/deliverables, admin requests queue, golden tasks,
  multimodal library, image annotation workspace, API management, tester
  qualifications.

### Honest status summary
- Fully implemented & verified: multi-tenancy + isolation matrix, client portal,
  golden tasks, qualifications + eligibility, image/video/audio annotation with
  exports, scoped external API + idempotency + signed webhooks + SSRF guard,
  unified analytics + audited exports.
- Partially implemented: YOLO export (normalized rows, not per-image files); S3
  media driver (documented extension point, not stubbed as working).
- Requires external configuration: SMTP email, production SECRET_KEY, PostgreSQL,
  persistent storage volume.
- Not implemented: OAuth2 for external API (scoped keys chosen), Krippendorff's α.

---

## 2026-11-14 — Phase 8+9 (API integrations, unified analytics)

- API credentials (hashed secrets, scopes, org/project binding, rotate/revoke,
  activity log, 120 req/min bucket → 429); `/api/ext/v1` surface (projects,
  datasets + record ingestion, tasks, approved results) with Idempotency-Key
  replay (24h; different-body reuse → 422); webhook endpoints with event
  subscriptions, HMAC signatures (`X-EvalForge-Signature: t,v1`), SSRF guard
  enforced at creation AND delivery, background retry worker with backoff,
  delivery history + replay + test dispatch; review decisions dispatch webhooks.
- Tests (8): key lifecycle + scope enforcement, rotation, external ingestion,
  idempotency replay, rate limiting 429, live webhook delivery with signature
  verification against a local receiver, SSRF matrix, endpoint CRUD blocks →
  **185/185**. Frontend: IntegrationsPage.
- Phase 9: `/api/analytics/platform` (honest rates: None when denominator 0),
  `/api/analytics/export` (quality CSV/JSON + platform, audited), platform panel
  on the admin overview. Tests (3) → **188/188**.

---

## 2026-11-14 — Phases 5–7 complete (multimodal annotation)

### Completed
- Models: `MediaAsset` (magic-byte sniffed, probed dims/duration), `ImageAnnotation`
  (bbox/polygon/point, normalized 0..1 coords), `VideoAnnotation` (events with start/end ms +
  per-frame shapes), `AudioAnnotation` (timestamped segments with transcript/speaker/language/
  emotion); `Task.media_asset_id`.
- `services/multimodal.py`: content sniffing (never trusts extensions), header probes
  (PNG/JPEG/GIF dims, WAV duration), annotation validation (coordinate ranges, polygon closure
  rules, monotone timestamps, transcripts required), COCO + CSV + native JSON converters.
- Routes: media upload/list/detail/**Range-aware streaming** (auth + membership, chunked);
  annotation get/save (versioned)/submit (creates a real Submission → standard review flow);
  annotation task generation (deduped); permission-checked audited exports (COCO/CSV/JSON for
  image, JSON for video, JSON/CSV for audio).
- Migration `e5b8c6d1e347` (idempotent) applied to dev DB.
- Tests: `test_multimodal.py` (6) — metadata probing, 415 on junk, idempotent generation,
  Range streaming + outsider 403, image validation (range/polygon rules) → submit → reviewer
  approval, video timestamp validation, audio segment validation, COCO pixel-space math
  ([40,40,160,80] asserted), tester export 403. **Backend 177/177.**
- Frontend: `AnnotationTaskWorkspace` with three modality components — image (bbox/polygon/point
  tools, zoom, undo/redo, label palette, shape list), video (player + timeline + event spans +
  frame stepping + frame capture), audio (waveform canvas via decodeAudioData, seek, playback
  speed, transcript segments); authenticated blob URLs for media (`<img>` cannot send JWT);
  admin `MultimodalPage` (library/upload/labels/generate/exports); TaskWorkspacePage branches to
  the annotation workspace by task_type. Typecheck + vitest + build ✓.
- **Browser verified end-to-end**: seeded images → admin media library (screenshot 06) → claimed
  annotation task → drew 2 bboxes via real clicks → save (version 1) → submit (toasts + submitted
  badge) — screenshot 07. Fixed a stale-closure crash in the bbox drawing path found by this pass.

### Known issues / notes
- Video/audio duration: parsed from WAV headers server-side; MP4/WebM/MP3/OGG metadata accepted
  from the client as reported (probe libs documented as an extension point).
- Media streaming uses short-lived object URLs client-side; direct signed-URL mode is available
  on the backend for future CDN use.

---

## 2026-11-14 — Phase 4 complete (worker qualifications)

### Completed
- Models: assessments (+versioned questions), attempts, WorkerSkill (self vs verified),
  ProjectEligibilityOverride. Services: attempt lifecycle, auto/manual grading, verified-skill
  grants, evidence-based tiers, `eligibility_status` enforced in the task claim path (403 + unmet
  reasons; overrides honored). Routes: staff CRUD, worker attempts (answers never leak), grading
  queue, skills/performance, eligibility config. Migration `d4a7f5b0c236`. Tests: 6 → **171/171**.
- Frontend: admin builder + eligibility editor, quality grading queue, tester take/skills/
  performance pages. **Journey B verified live** (create → attempt → pass → verified skill → tier).

---

## 2026-11-14 — Phase 3 complete (golden tasks)

### Completed
- GoldenTask (+append-only versions), GoldenTaskResult, QualityAlert; Task.is_golden;
  6 scoring methods; distribution (percentage/fixed/spacing/difficulty); submission-time scoring
  hook; alert engine (indicators only). Routes: CRUD + import + config + quality report/alerts.
  **Worker-facing surfaces never expose golden identity or reference answers.**
- Migration `c3f6e4a9b125`. Tests: 8 → **165/165**. Frontend: admin management + quality
  monitoring, browser-verified (screenshot 05).

---

## 2026-11-13/14 — Phase 2 complete (client portal)

### Completed
- ProjectRequest / ClientMessage (internal notes) / Deliverable; org-scoped dashboard + sanitized
  monitoring + uploads with import reports + messaging + audited deliverable downloads; staff
  approval queue + convert-to-project + publishing + thread. Migration `b2e5d3f8a014`. Tests: 9 →
  **157/157**. Full client portal frontend; **browser verified** (screenshots 02–04).

---

## 2026-11-13 — Phase 1 complete (multi-tenant foundations)

### Completed
- Organization + members + invitations (hashed tokens); client roles; org-scoped access;
  organizations API; tenant-isolation fixes (dataset scoping, demo/load, stale role strings,
  restore gap, quality scoping). Migration `a1f4c2d7e903`; psycopg fix. Tests: 17 → **148/148**.

---

## 2026-11-13 — Phase 0 complete (audit + plan)

### Baseline verified independently
- Backend pytest **131/131** · Vitest **9/9** · smoke (fresh DB) **42/42** · Playwright **3/3**
  · build ✓ · Alembic ✓. `docs/V3_INITIAL_AUDIT.md` + `docs/V3_IMPLEMENTATION_PLAN.md`.

### Environment notes
- Node via ZCode Electron fallback; Docker unavailable — SQLite + uvicorn + Vite verification;
  screenshots in `docs/screenshots/`.
