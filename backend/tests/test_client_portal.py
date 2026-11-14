"""V3 Phase 2: Client Portal — requests, uploads, messaging, deliverables + isolation.

Extends the cross-tenant matrix with portal resources: a client of org A must
never read org B's requests, messages, deliverables or datasets by changing IDs.
"""
import io
import json

import pytest


def _register(client, email, name, password="TestPass!23"):
    r = client.post("/api/auth/register", json={"email": email, "name": name, "password": password})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _make_org_with_client(client, admin_headers, name, letter):
    org = client.post("/api/organizations", headers=admin_headers, json={"name": name}).json()
    owner = _register(client, f"owner.{letter}@test.dev", f"Owner {letter}")
    r = client.post(f"/api/organizations/{org['id']}/members", headers=admin_headers,
                    json={"email": f"owner.{letter}@test.dev", "role": "client_owner"})
    assert r.status_code == 201, r.text
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    return org, owner_headers


@pytest.fixture()
def portal(client, db):
    """Admin + two orgs with clients + one project each + demo content."""
    admin = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}
    org_a, owner_a = _make_org_with_client(client, admin_headers, "Portal Org A", "a")
    org_b, owner_b = _make_org_with_client(client, admin_headers, "Portal Org B", "b")

    # projects per org (created by admin, linked to the org)
    proj_a = client.post("/api/projects", headers=admin_headers,
                         json={"name": "Proj A", "organization_id": org_a["id"]}).json()
    proj_b = client.post("/api/projects", headers=admin_headers,
                         json={"name": "Proj B", "organization_id": org_b["id"]}).json()

    return {
        "client": client,
        "admin_headers": admin_headers,
        "org_a": org_a, "org_b": org_b,
        "owner_a": owner_a, "owner_b": owner_b,
        "proj_a": proj_a, "proj_b": proj_b,
    }


def _json_upload(client, headers, url, rows, name="records.json"):
    files = {"file": (name, json.dumps(rows).encode(), "application/json")}
    return client.post(url, headers=headers, files=files)


def test_client_dashboard_counts_are_real(portal):
    c, ah = portal["client"], portal["admin_headers"]
    oa = portal["owner_a"]
    # initially zero
    r = c.get("/api/client/dashboard", headers=oa)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["projects"]["total"] == 1  # proj_a exists
    assert data["tasks"]["total"] == 0
    assert data["tasks"]["completion_rate"] is None  # never invented
    assert data["requests"]["total"] == 0
    assert data["organization"]["name"] == "Portal Org A"


def test_project_request_lifecycle(portal):
    c, ah = portal["client"], portal["admin_headers"]
    oa = portal["owner_a"]

    # client submits a request
    r = c.post("/api/client/requests", headers=oa, json={
        "title": "Sentiment dataset evaluation",
        "description": "Evaluate 5k classified support tickets",
        "category": "text_classification",
        "expected_task_volume": 5000,
        "required_languages": ["en", "de"],
        "required_skills": ["data annotation"],
        "dataset_availability": "csv_upload",
        "quality_requirements": "95% minimum accuracy on golden tasks",
        "special_instructions": "Use our taxonomy v2",
    })
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "submitted"

    # staff queue sees it with org name
    r = c.get("/api/admin/project-requests", headers=ah)
    assert r.status_code == 200
    queued = [x for x in r.json() if x["id"] == req["id"]]
    assert queued and queued[0]["organization_name"] == "Portal Org A"

    # more info -> client sees it; then approve -> convert
    r = c.post(f"/api/admin/project-requests/{req['id']}/review", headers=ah,
               json={"action": "more_info", "note": "Please specify the label set."})
    assert r.status_code == 200 and r.json()["status"] == "more_info_required"

    r = c.post(f"/api/admin/project-requests/{req['id']}/review", headers=ah,
               json={"action": "approve"})
    assert r.status_code == 200 and r.json()["status"] == "approved"

    r = c.post(f"/api/admin/project-requests/{req['id']}/convert", headers=ah)
    assert r.status_code == 200, r.text
    project_id = r.json()["project_id"]

    # converted request carries all submitted info into the project
    proj = c.get(f"/api/projects/{project_id}", headers=ah).json()
    assert proj["organization_id"] == portal["org_a"]["id"]
    assert proj["target_task_volume"] == 5000

    # client sees converted project
    r = c.get("/api/client/projects", headers=oa)
    assert any(p["id"] == project_id for p in r.json())
    # and the request shows converted
    r = c.get("/api/client/requests", headers=oa)
    mine = [x for x in r.json() if x["id"] == req["id"]][0]
    assert mine["status"] == "converted" and mine["converted_project_id"] == project_id


def test_reject_requires_explanation(portal):
    c, ah = portal["client"], portal["admin_headers"]
    oa = portal["owner_a"]
    req = c.post("/api/client/requests", headers=oa, json={
        "title": "Req", "category": "custom_evaluation"}).json()
    r = c.post(f"/api/admin/project-requests/{req['id']}/review", headers=ah,
               json={"action": "reject"})
    assert r.status_code == 422
    r = c.post(f"/api/admin/project-requests/{req['id']}/review", headers=ah,
               json={"action": "reject", "note": "Out of scope this quarter."})
    assert r.status_code == 200 and r.json()["status"] == "rejected"


def test_client_dataset_upload_with_report(portal):
    c, oa = portal["client"], portal["owner_a"]
    rows = [
        {"record_id": "c1", "prompt": "Is this positive?", "response": "I love it",
         "expected_label": "positive"},
        {"record_id": "c2", "prompt": "Is this negative?", "response": "I hate it",
         "expected_label": "negative"},
    ]
    r = _json_upload(c, oa, f"/api/client/projects/{portal['proj_a']['id']}/datasets", rows)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["report"]["valid_count"] == 2
    ds_id = body["dataset"]["id"]

    # client can preview the records
    r = c.get(f"/api/client/projects/{portal['proj_a']['id']}/datasets/{ds_id}/records", headers=oa)
    assert r.status_code == 200 and r.json()["total"] == 2

    # staff sees the dataset under the project
    r = c.get("/api/datasets", headers=portal["admin_headers"])
    assert any(d["id"] == ds_id for d in r.json())


def test_client_upload_isolated_across_orgs(portal):
    """Org B's client cannot touch org A's project or dataset by ID swap."""
    c = portal["client"]
    oa, ob = portal["owner_a"], portal["owner_b"]
    rows = [{"record_id": "a1", "prompt": "p", "response": "r"}]
    r = _json_upload(c, oa, f"/api/client/projects/{portal['proj_a']['id']}/datasets", rows)
    assert r.status_code == 201
    ds_id = r.json()["dataset"]["id"]

    # org B cannot upload into org A's project
    r = _json_upload(c, ob, f"/api/client/projects/{portal['proj_a']['id']}/datasets", rows)
    assert r.status_code == 404
    # org B cannot read org A's dataset records
    r = c.get(f"/api/client/projects/{portal['proj_a']['id']}/datasets/{ds_id}/records", headers=ob)
    assert r.status_code == 404
    # org B cannot see org A's project details
    assert c.get(f"/api/client/projects/{portal['proj_a']['id']}", headers=ob).status_code == 404


def test_messaging_flow_and_internal_notes_hidden(portal):
    c, ah, oa = portal["client"], portal["admin_headers"], portal["owner_a"]
    project_id = portal["proj_a"]["id"]

    # client -> staff
    r = c.post(f"/api/client/projects/{project_id}/messages", headers=oa,
               json={"body": "When do you expect the first batch?"})
    assert r.status_code == 201, r.text

    # staff tokens cannot use the client route
    assert c.post(f"/api/client/projects/{project_id}/messages", headers=ah,
                  json={"body": "hi"}).status_code == 403

    # staff replies via the admin thread endpoint
    r = c.post(f"/api/admin/projects/{project_id}/messages", headers=ah,
               json={"body": "Next Tuesday."})
    assert r.status_code == 201, r.text

    # staff leaves an internal note
    r = c.post(f"/api/admin/projects/{project_id}/messages", headers=ah,
               json={"body": "Client is impatient — prioritize.", "is_internal": True})
    assert r.status_code == 201

    # staff sees both
    r = c.get(f"/api/admin/projects/{project_id}/messages", headers=ah)
    assert r.status_code == 200
    bodies = [m["body"] for m in r.json()]
    assert "Next Tuesday." in bodies and any("prioritize" in b for b in bodies)

    # client sees the reply but NEVER the internal note
    r = c.get(f"/api/client/projects/{project_id}/messages", headers=oa)
    bodies = [m["body"] for m in r.json()]
    assert "Next Tuesday." in bodies
    assert not any("prioritize" in b for b in bodies)
    assert all(m["sender_side"] in ("client", "staff") for m in r.json())


def test_deliverable_publish_and_download(portal):
    c, ah, oa = portal["client"], portal["admin_headers"], portal["owner_a"]
    project_id = portal["proj_a"]["id"]

    # no approved results yet -> deliverable with 0 records still publishes
    r = c.post(f"/api/admin/projects/{project_id}/deliverables", headers=ah,
               json={"label": "Batch 1", "format": "json"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["record_count"] == 0

    # client lists + downloads it
    r = c.get("/api/client/deliverables", headers=oa)
    assert r.status_code == 200 and len(r.json()) == 1
    dl = c.get(f"/api/client/deliverables/{d['id']}/download", headers=oa)
    assert dl.status_code == 200
    payload = json.loads(dl.content)
    assert payload["project"]["id"] == project_id

    # org B cannot list or download org A's deliverable
    assert c.get("/api/client/deliverables", headers=portal["owner_b"]).json() == []
    assert c.get(f"/api/client/deliverables/{d['id']}/download",
                 headers=portal["owner_b"]).status_code == 404


def test_readonly_client_role_cannot_submit(portal):
    c, ah = portal["client"], portal["admin_headers"]
    org_a = portal["org_a"]
    viewer = _register(c, "viewer.a@test.dev", "Viewer A")
    c.post(f"/api/organizations/{org_a['id']}/members", headers=ah,
           json={"email": "viewer.a@test.dev", "role": "client_viewer"})
    vh = {"Authorization": f"Bearer {viewer['access_token']}"}
    # read works
    assert c.get("/api/client/dashboard", headers=vh).status_code == 200
    # writes are blocked
    assert c.post("/api/client/requests", headers=vh,
                  json={"title": "Nope", "category": "custom_evaluation"}).status_code == 403
    r = _json_upload(c, vh, f"/api/client/projects/{portal['proj_a']['id']}/datasets", [])
    assert r.status_code == 403


def test_staff_tokens_rejected_on_client_endpoints(portal):
    c, ah = portal["client"], portal["admin_headers"]
    assert c.get("/api/client/dashboard", headers=ah).status_code == 403
    assert c.get("/api/client/projects", headers=ah).status_code == 403
