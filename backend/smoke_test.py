"""End-to-end API smoke test against a running server (no pytest).

Run: .venv/Scripts/python.exe smoke_test.py [base_url]
"""
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
client = httpx.Client(base_url=BASE, timeout=120)

checks = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    checks.append((name, status))
    print(f"[{status}] {name}" + (f" — {extra}" if extra else ""))


def main() -> None:
    # Health
    r = client.get("/api/health")
    check("health", r.status_code == 200, str(r.json()))

    # Auth — admin registers FIRST so it receives the administrator bootstrap role
    r = client.post("/api/auth/register", json={"email": "admin@evalforge.dev", "name": "Admin", "password": "AdminPass!23"})
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={"email": "admin@evalforge.dev", "password": "AdminPass!23"})
    check("admin register/login", r.status_code in (200, 201), f"{r.status_code}")
    ah = {"Authorization": f"Bearer {r.json()['access_token']}"}
    check("first user is super_admin", r.json()["user"]["role"] == "super_admin", r.json()["user"]["role"])

    email = "smoke@evalforge.dev"
    r = client.post("/api/auth/register", json={"email": email, "name": "Smoke User", "password": "SmokePass!23"})
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={"email": email, "password": "SmokePass!23"})
    check("auth register/login", r.status_code in (200, 201), f"{r.status_code}")
    token = r.json()["access_token"]
    user = r.json()["user"]
    h = {"Authorization": f"Bearer {token}"}
    check("second user is tester", user["role"] == "tester", user["role"])
    check("auth me", client.get("/api/auth/me", headers=h).status_code == 200)

    # Wrong password must fail
    r = client.post("/api/auth/login", json={"email": email, "password": "wrongpass"})
    check("auth rejects bad password", r.status_code == 401)

    # Unauthenticated access must fail
    check("datasets require auth", client.get("/api/datasets").status_code == 401)

    # Demo pipeline (dataset + rubric + engine + reviews)
    r = client.post("/api/demo/load", headers=h)
    check("demo load", r.status_code == 200, f"{r.status_code} {r.text[:200]}" if r.status_code != 200 else "")
    demo = r.json()
    print("   demo:", {k: demo[k] for k in ("records", "flagged_for_review", "disagreement_items")})

    # Dataset records
    ds_id = demo["dataset_id"]
    r = client.get(f"/api/datasets/{ds_id}/records?page=1&page_size=5", headers=h)
    check("dataset records", r.status_code == 200 and len(r.json()["items"]) == 5)
    check("dataset pagination total", r.json()["total"] == demo["records"], str(r.json()["total"]))

    # Rubric versions
    r = client.get(f"/api/rubrics/{demo['rubric_id']}/versions", headers=h)
    check("rubric versions", r.status_code == 200 and len(r.json()) == 1)

    # Rubric validation errors
    r = client.post("/api/rubrics/validate", headers=h, json={"definition": {"name": "x", "criteria": [{"id": "a", "weight": 0.5}]}})
    body = r.json()
    check("rubric validation catches errors", r.status_code == 200 and body["valid"] is False and len(body["errors"]) >= 3)

    # Duplicate criterion ids rejected
    bad = {"name": "Bad", "criteria": [
        {"id": "a", "name": "A", "weight": 0.5, "scoring_scale": {"type": "binary"}, "pass_threshold": 1,
         "checks": [{"type": "completeness"}]},
        {"id": "a", "name": "A2", "weight": 0.5, "scoring_scale": {"type": "binary"}, "pass_threshold": 1,
         "checks": [{"type": "completeness"}]},
    ], "passing_threshold": 0.7}
    r = client.post("/api/rubrics", headers=ah, json={"name": "Bad Rubric", "definition": bad})
    check("duplicate criterion id rejected", r.status_code == 422)
    # staff-only authoring: testers get 403 (role model v2)
    r = client.post("/api/rubrics", headers=h, json={"name": "Bad Rubric", "definition": bad})
    check("role enforcement (tester cannot author rubric)", r.status_code == 403, str(r.status_code))

    # Run results
    run_id = demo["evaluation_run_id"]
    r = client.get(f"/api/evaluations/{run_id}", headers=h)
    run = r.json()
    check("run completed", run["status"] == "completed", run["status"])
    total = run["passed_count"] + run["failed_count"] + run["borderline_count"]
    check("run totals consistent", total == run["total_records"] == demo["records"], f"pass={run['passed_count']} fail={run['failed_count']} bl={run['borderline_count']}")

    r = client.get(f"/api/evaluations/{run_id}/results?page=1&page_size=100", headers=h)
    results = r.json()["items"]
    check("results listed", r.status_code == 200 and len(results) == demo["records"])

    # Borderline routing present (partially_correct / evidence_insufficient etc.)
    cats = {r_.get("borderline_category") for r_ in results if r_.get("borderline_category")}
    print("   borderline categories:", cats)
    check("borderline categories assigned", len(cats) >= 2, ", ".join(sorted(cats)))

    # Findings traceability
    result_id = results[0]["id"]
    r = client.get(f"/api/evaluations/{run_id}/results/{result_id}", headers=h)
    det = r.json()
    check("findings recorded", len(det["findings"]) > 0)
    f0 = det["findings"][0]
    check("finding traceability fields", all(k in f0 for k in ("rule_id", "evidence", "evaluator_version", "rubric_version", "executed_at")))

    # Gold-label metrics: accuracy/precision/recall/F1 + kappa
    r = client.get("/api/analytics/metrics", headers=h)
    m = r.json()
    print("   metrics:", {k: m.get(k) for k in ("accuracy", "precision", "recall", "f1", "cohen_kappa", "gold_labeled_count")})
    check("gold metrics computed", m.get("accuracy") is not None and m.get("f1") is not None)
    check("confusion matrix", m.get("confusion_matrix") is not None and len(m["confusion_matrix"]["matrix"]) == 2)

    r = client.get("/api/analytics/agreement", headers=h)
    ag = r.json()
    print("   agreement:", {k: ag.get(k) for k in ("raw_agreement_rate", "fleiss_kappa", "disagreement_items")})
    check("agreement computed", ag.get("raw_agreement_rate") is not None and ag.get("fleiss_kappa") is not None)
    check("disagreement detected", ag.get("disagreement_items", 0) >= 1, str(ag.get("disagreement_items")))

    # Blind review enforcement: demo reviewer 1 must NOT see reviewer 2's reviews pre-submission.
    r = client.post("/api/auth/login", json={"email": "reviewer.one@evalforge.demo", "password": "DemoReview!23"})
    check("demo reviewer login", r.status_code == 200)
    rtok = r.json()["access_token"]
    rh = {"Authorization": f"Bearer {rtok}"}
    r = client.get("/api/reviews/queue", headers=rh)
    pending = r.json()["items"]
    check("review queue populated", len(pending) > 0, f"pending={len(pending)}")
    if pending:
        aid = pending[0]["assignment"]["id"]
        r = client.get(f"/api/reviews/{aid}", headers=rh)
        body = r.json()
        visible = body["visible_reviews"]
        check("blind review: no other reviews visible while pending", len(visible) == 0, f"visible={len(visible)}")
        # Submit own review
        r = client.post(f"/api/reviews/{aid}/submit", headers=rh, json={
            "label": "pass", "criterion_scores": [], "reasoning": "Smoke review", "uncertain": False})
        check("review submit", r.status_code == 200)
        # Now other reviews become visible
        r = client.get(f"/api/reviews/{aid}", headers=rh)
        check("reviews visible after own submission", len(r.json()["visible_reviews"]) >= 1)
        # Re-submission must be blocked (immutability)
        r = client.post(f"/api/reviews/{aid}/submit", headers=rh, json={"label": "fail", "criterion_scores": []})
        check("review immutable", r.status_code == 409)

    # Adjudication on a disagreeing result (requires admin/project_manager role)
    r = client.get(f"/api/evaluations/{run_id}/results?page=1&page_size=100", headers=h)
    dis_ids = [x["id"] for x in r.json()["items"] if x.get("borderline_category")]
    adj_done = False
    for rid in dis_ids:
        r = client.get(f"/api/reviews/results/{rid}/reviews", headers=ah)
        labels = {rv["label"] for rv in r.json()}
        if len(labels) > 1:
            r = client.post(f"/api/reviews/results/{rid}/adjudicate", headers=ah, json={
                "final_label": "partially_correct", "rationale": "Smoke adjudication: structural checks pass but evidence is thin."})
            check("adjudication created", r.status_code == 200, r.text[:120] if r.status_code != 200 else "")
            # Evaluator role must NOT be able to adjudicate
            r = client.post(f"/api/reviews/results/{rid}/adjudicate", headers=h, json={
                "final_label": "pass", "rationale": "should fail"})
            check("role enforcement (evaluator cannot adjudicate)", r.status_code == 403, str(r.status_code))
            adj_done = True
            break
    if not adj_done:
        check("adjudication created", False, "no disagreeing result found")

    # Analytics overview
    r = client.get("/api/analytics/overview", headers=h)
    ov = r.json()
    check("overview populated", ov["total_records"] == demo["records"] and ov["completed_runs"] >= 1)
    check("review queue metric", ov["review_queue_size"] >= 0)

    # Audit logs (admin only)
    r = client.get("/api/audit-logs?page=1&page_size=50", headers=h)
    check("audit logs restricted from evaluator", r.status_code == 403, str(r.status_code))
    r = client.get("/api/audit-logs?page=1&page_size=50", headers=ah)
    check("audit logs", r.status_code == 200 and r.json()["total"] > 5, f"total={r.json()['total']}")
    actions = {i["action"] for i in r.json()["items"]}
    print("   audit actions:", sorted(actions))
    check("audit tracks evaluation + review", ("evaluation.execute" in actions or "demo.load" in actions) and "review.submit" in actions)

    # Settings
    r = client.get("/api/settings", headers=h)
    check("settings get", r.status_code == 200)
    r = client.put("/api/settings", headers=h, json={"borderline_confidence_below": 0.65})
    check("settings update restricted from evaluator", r.status_code == 403, str(r.status_code))
    r = client.put("/api/settings", headers=ah, json={"borderline_confidence_below": 0.65})
    check("settings update", r.status_code == 200 and r.json()["borderline_confidence_below"] == 0.65)

    # Role enforcement: reviewer cannot create datasets
    r = client.post("/api/datasets", headers=rh, json={"name": "Should Fail"})
    check("role enforcement (tester cannot create dataset)", r.status_code == 403, str(r.status_code))

    failed = [n for n, s in checks if s == "FAIL"]
    print(f"\n===== {len(checks) - len(failed)}/{len(checks)} checks passed =====")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
