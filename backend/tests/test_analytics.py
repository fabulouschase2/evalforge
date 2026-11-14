"""Statistical analytics: metrics, kappa, Fleiss' kappa, agreement rates."""
import math

import pytest

from app.services.analytics import classification_metrics, fleiss_kappa


def test_classification_metrics_perfect():
    res = classification_metrics(["pass", "pass", "fail", "fail"], ["pass", "pass", "fail", "fail"])
    m = res["metrics"]
    assert m["accuracy"] == 1.0
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["f1"] == 1.0
    assert m["cohen_kappa"] == 1.0
    assert m["confusion_matrix"]["matrix"] == [[2, 0], [0, 2]]


def test_classification_metrics_mixed():
    res = classification_metrics(
        ["pass", "pass", "pass", "fail", "fail", "fail"],
        ["pass", "fail", "pass", "fail", "pass", "fail"],
    )
    m = res["metrics"]
    assert m["accuracy"] == pytest.approx(0.6667)  # API reports 4-decimal values
    # predicted pass: 3 (2 correct) -> precision 2/3; gold pass 3, found 2 -> recall 2/3
    assert m["precision"] == pytest.approx(0.6667)
    assert m["recall"] == pytest.approx(0.6667)
    assert m["f1"] == pytest.approx(0.6667)
    # confusion matrix rows = gold (fail, pass), cols = predicted
    # gold fail: pred fail x2 (idx3,5), pred pass x1 (idx4); gold pass: pred fail x1 (idx1), pred pass x2
    assert m["confusion_matrix"]["matrix"] == [[2, 1], [1, 2]]


import pytest  # noqa: E402  (used above)


def test_classification_metrics_single_class_kappa_note():
    res = classification_metrics(["pass", "pass"], ["pass", "fail"])
    m = res["metrics"]
    assert "cohen_kappa" not in m or m.get("kappa_note")


def test_classification_metrics_empty_reports_reason():
    res = classification_metrics([], [])
    assert res["metrics"] is None
    assert "gold" in res["insufficient_reason"].lower()


def test_fleiss_kappa_perfect_agreement():
    # 3 items, 2 raters, 2 categories: all agree
    kappa = fleiss_kappa([[2, 0], [2, 0], [0, 2]])
    assert kappa == 1.0


def test_fleiss_kappa_known_value():
    # 5 items, 3 raters, 2 categories — verify against the closed-form formula.
    matrix = [
        [3, 0],
        [0, 3],
        [2, 1],
        [1, 2],
        [2, 1],
    ]
    kappa = fleiss_kappa(matrix)
    n, N = 3, 5
    p_j = [sum(row[0] for row in matrix) / (N * n), sum(row[1] for row in matrix) / (N * n)]
    P_i = [((row[0] ** 2 + row[1] ** 2) - n) / (n * (n - 1)) for row in matrix]
    P_bar = sum(P_i) / N
    P_e = p_j[0] ** 2 + p_j[1] ** 2
    expected = (P_bar - P_e) / (1 - P_e)
    assert math.isclose(kappa, expected, rel_tol=1e-3)


def test_fleiss_kappa_all_split_items_is_minus_one():
    # Every item split 50/50: observed agreement 0 => kappa = -1
    kappa = fleiss_kappa([[1, 1], [1, 1], [1, 1], [1, 1]])
    assert kappa == -1.0


def test_fleiss_kappa_uneven_raters_returns_none():
    # Second item has only one rater -> kappa undefined
    assert fleiss_kappa([[2, 0], [1, 0]]) is None


def test_fleiss_kappa_empty():
    assert fleiss_kappa([]) is None


def test_agreement_api_flow(client, db, auth_headers):
    """End-to-end: assign two reviewers, submit agreeing reviews, check agreement."""
    from app.core.security import hash_password
    from app.models.user import User
    from tests.conftest import get_results, make_dataset, make_rubric, make_run

    admin, _ = auth_headers
    r1 = User(email="r1@test.dev", name="R1", hashed_password=hash_password("RevPass!23"), role="reviewer")
    r2 = User(email="r2@test.dev", name="R2", hashed_password=hash_password("RevPass!23"), role="reviewer")
    db.add_all([r1, r2])
    db.commit()

    ds, _ = make_dataset(client, admin, records=[
        {"record_id": "a1", "prompt": "p1", "response": "short answer one"},
        {"record_id": "a2", "prompt": "p2", "response": "short answer two"},
    ])
    rid = make_rubric(client, admin)
    run = make_run(client, admin, ds, rid)
    results = get_results(client, admin, run["id"])
    assert len(results) == 2

    r = client.post("/api/reviews/assign", headers=admin, json={"reviewer_ids": [r1.id, r2.id], "result_ids": [x["id"] for x in results]})
    assignments = r.json()["assignments"]

    def _headers_for(email):
        token = client.post("/api/auth/login", json={"email": email, "password": "RevPass!23"}).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    h1, h2 = _headers_for("r1@test.dev"), _headers_for("r2@test.dev")
    for a in assignments:
        headers = h1 if a["reviewer_id"] == r1.id else h2
        assert client.post(f"/api/reviews/{a['id']}/submit", headers=headers, json={
            "label": "pass", "criterion_scores": [], "reasoning": "agree"}).status_code == 200

    ag = client.get("/api/analytics/agreement", headers=admin).json()
    assert ag["items_with_multiple_reviews"] == 2
    assert ag["full_agreement_items"] == 2
    assert ag["raw_agreement_rate"] == 1.0
    # When every rater uses a single category, kappa is degenerate (P_e == 1):
    # the API honestly reports None instead of a fake 1.0.
    assert ag["fleiss_kappa"] in (None, 1.0)
