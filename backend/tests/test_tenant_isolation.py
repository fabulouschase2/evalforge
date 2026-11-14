"""V3 cross-tenant authorization tests — the multi-tenancy mandate.

Builds two organizations (A and B), each with a project + dataset, and asserts
that swapping any resource ID between tenants fails closed for every surface
that exists after Phase 1. Phase 2+ suites extend this matrix with portal
resources (requests, messages, deliverables, media).
"""
import json

import pytest


def _register(client, email, name, password="TestPass!23"):
    r = client.post("/api/auth/register", json={"email": email, "name": name, "password": password})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _make_world(client, db):
    """Admin, two orgs (A, B) with one client_owner each, one project per org."""
    admin = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}

    world = {"admin_headers": admin_headers}
    for letter in ("A", "B"):
        org = client.post("/api/organizations", headers=admin_headers,
                          json={"name": f"Org {letter}"}).json()
        owner = _register(client, f"owner.{letter.lower()}@test.dev", f"Owner {letter}")
        r = client.post(f"/api/organizations/{org['id']}/members", headers=admin_headers,
                        json={"email": f"owner.{letter.lower()}@test.dev", "role": "client_owner"})
        assert r.status_code == 201, r.text
        owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
        world[letter] = {
            "org": org,
            "owner_headers": owner_headers,
            "owner_user_id": owner["user"]["id"],
        }
    return world


def _project_with_dataset(client, admin_headers, org_id, name):
    project = client.post("/api/projects", headers=admin_headers,
                          json={"name": name, "organization_id": org_id}).json()
    dataset = client.post("/api/datasets", headers=admin_headers,
                          json={"name": f"{name} DS", "project_id": project["id"]}).json()
    records = [{"record_id": "r1", "prompt": f"prompt {name}", "response": "resp",
                "reference_answer": "ref"}]
    files = {"file": ("records.json", json.dumps(records).encode(), "application/json")}
    r = client.post(f"/api/datasets/{dataset['id']}/upload/commit", headers=admin_headers, files=files)
    assert r.status_code == 201, r.text
    return project, dataset


@pytest.fixture()
def world(client, db):
    w = _make_world(client, db)
    project_a, dataset_a = _project_with_dataset(client, w["admin_headers"], w["A"]["org"]["id"], "Project A")
    project_b, dataset_b = _project_with_dataset(client, w["admin_headers"], w["B"]["org"]["id"], "Project B")
    w["A"]["project"], w["A"]["dataset"] = project_a, dataset_a
    w["B"]["project"], w["B"]["dataset"] = project_b, dataset_b
    w["_client"] = client
    return w


def test_client_cannot_read_other_orgs_project(world):
    a, b = world["A"], world["B"]
    r = client_get(world, a["owner_headers"], f"/api/projects/{b['project']['id']}")
    assert r.status_code == 403


def test_client_cannot_read_other_orgs_dataset(world):
    a, b = world["A"], world["B"]
    r = client_get(world, a["owner_headers"], f"/api/datasets/{b['dataset']['id']}")
    assert r.status_code == 403
    r = client_get(world, a["owner_headers"], f"/api/datasets/{b['dataset']['id']}/versions")
    assert r.status_code == 403
    r = client_get(world, a["owner_headers"], f"/api/datasets/{b['dataset']['id']}/records")
    assert r.status_code == 403


def test_client_project_list_contains_only_own_org(world):
    a = world["A"]
    r = client_get(world, a["owner_headers"], "/api/projects")
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    assert a["project"]["id"] in ids
    assert world["B"]["project"]["id"] not in ids


def test_client_dataset_list_contains_only_own_org(world):
    a = world["A"]
    r = client_get(world, a["owner_headers"], "/api/datasets")
    assert r.status_code == 200
    ids = {d["id"] for d in r.json()}
    assert a["dataset"]["id"] in ids
    assert world["B"]["dataset"]["id"] not in ids


def test_client_cannot_modify_other_orgs_project(world):
    a, b = world["A"], world["B"]
    r = client_request(world, "PUT", a["owner_headers"], f"/api/projects/{b['project']['id']}",
                       json={"name": "Hijacked"})
    assert r.status_code == 403
    r = client_request(world, "POST", a["owner_headers"], f"/api/projects/{b['project']['id']}/archive")
    assert r.status_code == 403


def test_client_cannot_download_other_orgs_dataset_export(world):
    a, b = world["A"], world["B"]
    r = client_get(world, a["owner_headers"], f"/api/datasets/{b['dataset']['id']}/export")
    assert r.status_code == 403


def test_client_cannot_access_other_orgs_notifications_or_admin_surfaces(world):
    """Client roles get 403 on staff-only surfaces even with valid tokens."""
    a = world["A"]
    for method, path, payload in (
        ("POST", "/api/organizations", {"name": "Nope"}),
        ("POST", "/api/demo/load", {}),
    ):
        r = client_request(world, method, a["owner_headers"], path, json=payload)
        assert r.status_code == 403, f"{method} {path} -> {r.status_code}"


def test_worker_cannot_access_unassigned_project(world):
    """A tester who is not a member of either org project sees neither."""
    client = world["_client"]
    tester = _register(client, "worker.x@test.dev", "Worker X")
    tester_headers = {"Authorization": f"Bearer {tester['access_token']}"}
    r = client_get(world, tester_headers, "/api/projects")
    assert r.status_code == 200 and r.json() == []
    for pid in (world["A"]["project"]["id"], world["B"]["project"]["id"]):
        assert client_get(world, tester_headers, f"/api/projects/{pid}").status_code == 403
    for did in (world["A"]["dataset"]["id"], world["B"]["dataset"]["id"]):
        assert client_get(world, tester_headers, f"/api/datasets/{did}").status_code == 403


def test_client_cannot_enumerate_other_orgs_via_filters(world):
    """project_id filter on list endpoints must not leak other tenants."""
    a = world["A"]
    r = client_get(world, a["owner_headers"], f"/api/datasets?project_id={world['B']['project']['id']}")
    assert r.status_code == 200
    assert all(d["project_id"] != world["B"]["project"]["id"] for d in r.json())


# -- helpers wired through the pytest `client` fixture of conftest ------------

def client_get(world, headers, path):
    return client_request(world, "GET", headers, path)


def client_request(world, method, headers, path, json=None):
    return world["_client"].request(method, path, headers=headers, json=json)
