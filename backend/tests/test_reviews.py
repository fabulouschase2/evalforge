"""Human review workflow: independent blind reviews, immutability, adjudication."""
from tests.conftest import get_results, make_dataset, make_rubric, make_run


def _setup_flagged(client, headers):
    ds, _ = make_dataset(client, headers, records=[
        {"record_id": "b1", "prompt": "What is 2+2?", "response": "I am not sure about math questions at all.",
         "reference_answer": None, "expected_label": "pass"},  # no reference -> evidence_insufficient
    ])
    rid = make_rubric(client, headers)
    run = make_run(client, headers, ds, rid)
    results = get_results(client, headers, run["id"])
    flagged = [r for r in results if r["needs_review"]]
    assert len(flagged) == 1, "expected the no-reference record to be flagged"
    return flagged[0]["id"]


def test_blind_review_isolation(client, db, auth_headers):
    """Two reviewers: neither may see the other's assessment before submitting."""
    admin, _ = auth_headers

    # create two reviewers
    from app.core.security import hash_password
    from app.models.user import User
    r1 = User(email="r1@test.dev", name="R1", hashed_password=hash_password("RevPass!23"), role="reviewer")
    r2 = User(email="r2@test.dev", name="R2", hashed_password=hash_password("RevPass!23"), role="reviewer")
    db.add_all([r1, r2])
    db.commit()

    result_id = _setup_flagged(client, admin)
    r = client.post("/api/reviews/assign", headers=admin, json={"reviewer_ids": [r1.id, r2.id], "result_ids": [result_id]})
    assert r.status_code == 200 and r.json()["created"] == 2
    assignments = r.json()["assignments"]
    a1 = next(a for a in assignments if a["reviewer_id"] == r1.id)
    a2 = next(a for a in assignments if a["reviewer_id"] == r2.id)

    h1 = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "r1@test.dev", "password": "RevPass!23"}).json()["access_token"]}
    h2 = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "r2@test.dev", "password": "RevPass!23"}).json()["access_token"]}

    # R1 sees zero other reviews while pending
    body1 = client.get(f"/api/reviews/{a1['id']}", headers=h1).json()
    assert body1["visible_reviews"] == []

    # R1 submits pass
    r = client.post(f"/api/reviews/{a1['id']}/submit", headers=h1, json={
        "label": "pass", "criterion_scores": [], "reasoning": "Fine by me", "uncertain": False})
    assert r.status_code == 200

    # R2 (still pending) must STILL not see R1's review
    body2 = client.get(f"/api/reviews/{a2['id']}", headers=h2).json()
    assert body2["visible_reviews"] == []

    # R2 submits fail -> disagreement
    r = client.post(f"/api/reviews/{a2['id']}/submit", headers=h2, json={
        "label": "fail", "criterion_scores": [], "reasoning": "Unverifiable", "uncertain": False})
    assert r.status_code == 200

    # After own submission, R2 can now see R1's review (plus their own)
    body2 = client.get(f"/api/reviews/{a2['id']}", headers=h2).json()
    labels = {rv["label"] for rv in body2["visible_reviews"]}
    assert labels == {"pass", "fail"}

    # Both original reviews preserved in the audit-visible list for supervisors
    admin_reviews = client.get(f"/api/reviews/results/{result_id}/reviews", headers=admin).json()
    assert {rv["label"] for rv in admin_reviews} == {"pass", "fail"}


def test_review_immutability(client, db, auth_headers):
    admin, _ = auth_headers
    from app.core.security import hash_password
    from app.models.user import User
    r1 = User(email="r1@test.dev", name="R1", hashed_password=hash_password("RevPass!23"), role="reviewer")
    db.add(r1)
    db.commit()
    result_id = _setup_flagged(client, admin)
    r = client.post("/api/reviews/assign", headers=admin, json={"reviewer_ids": [r1.id], "result_ids": [result_id]})
    a1 = r.json()["assignments"][0]
    h1 = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "r1@test.dev", "password": "RevPass!23"}).json()["access_token"]}
    assert client.post(f"/api/reviews/{a1['id']}/submit", headers=h1, json={"label": "pass", "criterion_scores": []}).status_code == 200
    r = client.post(f"/api/reviews/{a1['id']}/submit", headers=h1, json={"label": "fail", "criterion_scores": []})
    assert r.status_code == 409


def test_cannot_submit_someone_elses_review(client, db, auth_headers):
    admin, _ = auth_headers
    from app.core.security import hash_password
    from app.models.user import User
    r1 = User(email="r1@test.dev", name="R1", hashed_password=hash_password("RevPass!23"), role="reviewer")
    db.add(r1)
    db.commit()
    result_id = _setup_flagged(client, admin)
    r = client.post("/api/reviews/assign", headers=admin, json={"reviewer_ids": [r1.id], "result_ids": [result_id]})
    a1 = r.json()["assignments"][0]
    r = client.post(f"/api/reviews/{a1['id']}/submit", headers=admin, json={"label": "pass", "criterion_scores": []})
    assert r.status_code == 403


def test_adjudication_preserves_reviews(client, db, auth_headers):
    admin, _ = auth_headers
    from app.core.security import hash_password
    from app.models.user import User
    r1 = User(email="r1@test.dev", name="R1", hashed_password=hash_password("RevPass!23"), role="reviewer")
    r2 = User(email="r2@test.dev", name="R2", hashed_password=hash_password("RevPass!23"), role="reviewer")
    db.add_all([r1, r2])
    db.commit()
    result_id = _setup_flagged(client, admin)
    r = client.post("/api/reviews/assign", headers=admin, json={"reviewer_ids": [r1.id, r2.id], "result_ids": [result_id]})
    a1, a2 = r.json()["assignments"]
    h1 = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "r1@test.dev", "password": "RevPass!23"}).json()["access_token"]}
    h2 = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "r2@test.dev", "password": "RevPass!23"}).json()["access_token"]}
    client.post(f"/api/reviews/{a1['id']}/submit", headers=h1, json={"label": "pass", "criterion_scores": [], "reasoning": "ok"})
    client.post(f"/api/reviews/{a2['id']}/submit", headers=h2, json={"label": "fail", "criterion_scores": [], "reasoning": "not ok"})

    r = client.post(f"/api/reviews/results/{result_id}/adjudicate", headers=admin, json={
        "final_label": "partially_correct", "rationale": "Split decision; treating as partial."})
    assert r.status_code == 200 and r.json()["final_label"] == "partially_correct"

    # Original reviews preserved
    reviews = client.get(f"/api/reviews/results/{result_id}/reviews", headers=admin).json()
    assert len(reviews) == 2
    # Adjudication visible in review detail
    body = client.get(f"/api/reviews/{a1['id']}", headers=h1).json()
    assert body["adjudication"]["final_label"] == "partially_correct"


def test_adjudication_requires_two_reviews(client, db, auth_headers):
    admin, _ = auth_headers
    from app.core.security import hash_password
    from app.models.user import User
    r1 = User(email="r1@test.dev", name="R1", hashed_password=hash_password("RevPass!23"), role="reviewer")
    db.add(r1)
    db.commit()
    result_id = _setup_flagged(client, admin)
    r = client.post("/api/reviews/assign", headers=admin, json={"reviewer_ids": [r1.id], "result_ids": [result_id]})
    a1 = r.json()["assignments"][0]
    h1 = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "r1@test.dev", "password": "RevPass!23"}).json()["access_token"]}
    client.post(f"/api/reviews/{a1['id']}/submit", headers=h1, json={"label": "pass", "criterion_scores": []})
    r = client.post(f"/api/reviews/results/{result_id}/adjudicate", headers=admin, json={
        "final_label": "pass", "rationale": "single review"})
    assert r.status_code == 400
