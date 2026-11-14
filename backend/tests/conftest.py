"""Pytest fixtures: isolated in-memory database per test + API helpers."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — registers all models
from app.core.security import hash_password
from app.db.base import Base, get_db
from app.main import app
from app.models.user import User


def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine, TestingSessionLocal


_engine, _SessionLocal = _make_engine()


def override_get_db():
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

# Bind the external-API request-log factory to the test engine (production
# binds SessionLocal inside main.lifespan).
from app.core import api_auth as _api_auth  # noqa: E402
_api_auth.bind_session_factory(_SessionLocal)


@pytest.fixture()
def db():
    """Fresh, empty database per test (and clear rate-limit buckets)."""
    from app.core import ratelimit
    ratelimit.reset_rate_limits()
    Base.metadata.drop_all(_engine)
    Base.metadata.create_all(_engine)
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client():
    return TestClient(app)


def _register(client: TestClient, email: str, name: str, password: str):
    r = client.post("/api/auth/register", json={"email": email, "name": name, "password": password})
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.fixture()
def auth_headers(client, db):
    """First user => administrator. Returns (headers, user_id)."""
    data = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]["id"]


@pytest.fixture()
def evaluator_headers(client, db):
    """Second user => evaluator."""
    _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    data = _register(client, "eval@test.dev", "Evaluator", "EvalPass!23")
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]["id"]


@pytest.fixture()
def reviewer_headers(client, db):
    """Second user with reviewer role (created directly in DB)."""
    _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    reviewer = User(email="rev@test.dev", name="Reviewer", hashed_password=hash_password("RevPass!23"), role="reviewer")
    db.add(reviewer)
    db.commit()
    db.refresh(reviewer)
    r = client.post("/api/auth/login", json={"email": "rev@test.dev", "password": "RevPass!23"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, reviewer.id


def make_dataset(client, headers, name="Test Dataset", records=None):
    """Create a dataset and import records via the JSON upload path."""
    r = client.post("/api/datasets", headers=headers, json={"name": name})
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]

    if records is None:
        records = [
            {"record_id": "r1", "prompt": "What is 2+2?", "response": "2+2 equals 4.",
             "reference_answer": "2+2 equals 4.", "expected_label": "pass"},
            {"record_id": "r2", "prompt": "Capital of France?", "response": "The capital of France is Paris.",
             "reference_answer": "Paris is the capital of France.", "expected_label": "pass"},
        ]
    files = {"file": ("records.json", _json_bytes(records), "application/json")}
    r = client.post(f"/api/datasets/{dataset_id}/upload/commit", headers=headers, files=files)
    assert r.status_code == 201, r.text
    return dataset_id, r.json()


def _json_bytes(rows):
    import json
    return json.dumps(rows).encode("utf-8")


DEMO_RUBRIC = {
    "name": "Test Rubric",
    "description": "Rubric used in tests",
    "criteria": [
        {
            "id": "format", "name": "Format", "description": "d", "weight": 0.5,
            "scoring_scale": {"type": "binary", "min": 0, "max": 1}, "pass_threshold": 1,
            "checks": [
                {"type": "completeness", "rule_id": "t.complete", "params": {}},
                {"type": "min_words", "rule_id": "t.min_words", "params": {"min": 3}},
            ],
        },
        {
            "id": "facts", "name": "Facts", "description": "d", "weight": 0.5,
            "scoring_scale": {"type": "likert", "min": 0, "max": 2}, "pass_threshold": 1,
            "checks": [
                {"type": "reference_overlap", "rule_id": "t.overlap", "params": {"support_threshold": 0.4}},
                {"type": "numeric_match", "rule_id": "t.numeric", "params": {"tolerance": 0.01}},
            ],
        },
    ],
    "passing_threshold": 0.6,
    "borderline_rules": {"confidence_below": 0.6, "score_margin": 0.05},
    "human_review_policy": {"when_borderline": True, "when_failed": False, "sample_failed_pct": 0},
}


def make_rubric(client, headers, definition=None):
    r = client.post("/api/rubrics", headers=headers, json={
        "name": (definition or DEMO_RUBRIC).get("name", "Test Rubric"),
        "definition": definition or DEMO_RUBRIC,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_run(client, headers, dataset_id, rubric_id, name="Test Run"):
    r = client.post("/api/evaluations", headers=headers, json={
        "name": name, "dataset_id": dataset_id, "rubric_id": rubric_id})
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    r = client.post(f"/api/evaluations/{run_id}/run", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def get_results(client, headers, run_id):
    r = client.get(f"/api/evaluations/{run_id}/results?page=1&page_size=100", headers=headers)
    assert r.status_code == 200
    return r.json()["items"]
