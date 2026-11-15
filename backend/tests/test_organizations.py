"""V3 Phase 1: organization (tenant) management tests."""
import pytest


def _register(client, email, name, password="TestPass!23"):
    r = client.post("/api/auth/register", json={"email": email, "name": name, "password": password})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _create_org(client, headers, name, owner_email=None):
    payload = {"name": name}
    if owner_email:
        payload["owner_email"] = owner_email
    r = client.post("/api/organizations", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_admin_creates_organization(client, db, auth_headers):
    headers, _ = auth_headers
    org = _create_org(client, headers, "Acme Data Co")
    assert org["name"] == "Acme Data Co"
    assert org["slug"] == "acme-data-co"
    assert org["status"] == "active"


def test_first_registered_cannot_create_org_without_admin(client, db):
    """A plain tester (second registered user) cannot create organizations."""
    _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    user = _register(client, "someone@test.dev", "Someone")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    r = client.post("/api/organizations", headers=headers, json={"name": "Rogue Org"})
    assert r.status_code == 403


def test_organization_list_scoped_for_clients(client, db, auth_headers):
    headers, admin_id = auth_headers
    org_a = _create_org(client, headers, "Org A")
    org_b = _create_org(client, headers, "Org B")

    # client owner of org A
    owner = _register(client, "owner.a@test.dev", "Owner A")
    client.post("/api/organizations/%s/members" % org_a["id"], headers=headers,
                json={"email": "owner.a@test.dev", "role": "client_owner"})

    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    r = client.get("/api/organizations", headers=owner_headers)
    assert r.status_code == 200
    ids = {o["id"] for o in r.json()}
    assert org_a["id"] in ids
    assert org_b["id"] not in ids


def test_client_cannot_read_other_organization(client, db, auth_headers):
    headers, _ = auth_headers
    org_a = _create_org(client, headers, "Org A")
    org_b = _create_org(client, headers, "Org B")
    owner = _register(client, "owner.a@test.dev", "Owner A")
    client.post(f"/api/organizations/{org_a['id']}/members", headers=headers,
                json={"email": "owner.a@test.dev", "role": "client_owner"})
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    # changing the id in the URL must not leak org B
    r = client.get(f"/api/organizations/{org_b['id']}", headers=owner_headers)
    assert r.status_code == 403
    r = client.get(f"/api/organizations/{org_b['id']}/members", headers=owner_headers)
    assert r.status_code == 403


def test_member_role_management_and_owner_retention(client, db, auth_headers):
    headers, _ = auth_headers
    org = _create_org(client, headers, "Org X")
    owner = _register(client, "owner.x@test.dev", "Owner X")
    viewer = _register(client, "viewer.x@test.dev", "Viewer X")
    r = client.post(f"/api/organizations/{org['id']}/members", headers=headers,
                    json={"email": "owner.x@test.dev", "role": "client_owner"})
    assert r.status_code == 201
    member_owner_id = r.json()["id"]
    r = client.post(f"/api/organizations/{org['id']}/members", headers=headers,
                    json={"email": "viewer.x@test.dev", "role": "client_viewer"})
    viewer_member_id = r.json()["id"]

    # promote viewer to project manager
    r = client.put(f"/api/organizations/{org['id']}/members/{viewer_member_id}",
                   headers=headers, json={"role": "client_project_manager"})
    assert r.status_code == 200 and r.json()["role"] == "client_project_manager"

    # cannot remove the last owner
    r = client.delete(f"/api/organizations/{org['id']}/members/{member_owner_id}", headers=headers)
    assert r.status_code == 400

    # owner can manage members; viewer cannot
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    r = client.post(f"/api/organizations/{org['id']}/members", headers=owner_headers,
                    json={"email": "extra.x@test.dev", "role": "client_viewer"})
    assert r.status_code == 404  # user does not exist — but authorization passed
    viewer_headers = {"Authorization": f"Bearer {viewer['access_token']}"}
    r = client.post(f"/api/organizations/{org['id']}/members", headers=viewer_headers,
                    json={"email": "extra2.x@test.dev", "role": "client_viewer"})
    assert r.status_code == 403


def test_invitation_flow(client, db, auth_headers):
    headers, _ = auth_headers
    org = _create_org(client, headers, "Invite Org")
    r = client.post(f"/api/organizations/{org['id']}/invitations", headers=headers,
                    json={"email": "new.client@test.dev", "role": "client_project_manager"})
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    assert token

    # the invited user registers and accepts
    invited = _register(client, "new.client@test.dev", "New Client")
    invited_headers = {"Authorization": f"Bearer {invited['access_token']}"}
    r = client.post("/api/organizations/invitations/accept", headers=invited_headers,
                    json={"token": token})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "client_project_manager"

    # acceptance is single-use
    r = client.post("/api/organizations/invitations/accept", headers=invited_headers,
                    json={"token": token})
    assert r.status_code == 403

    # wrong email cannot accept someone else's invitation
    r = client.post(f"/api/organizations/{org['id']}/invitations", headers=headers,
                    json={"email": "other@test.dev", "role": "client_viewer"})
    token2 = r.json()["token"]
    r = client.post("/api/organizations/invitations/accept", headers=invited_headers,
                    json={"token": token2})
    assert r.status_code == 403


def test_client_roles_cannot_use_internal_functions(client, db, auth_headers):
    """Client roles are external: no internal platform capabilities."""
    headers, _ = auth_headers
    org = _create_org(client, headers, "Org Z")
    owner = _register(client, "owner.z@test.dev", "Owner Z")
    client.post(f"/api/organizations/{org['id']}/members", headers=headers,
                json={"email": "owner.z@test.dev", "role": "client_owner"})
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    # internal capabilities must be refused
    assert client.post("/api/projects", headers=owner_headers,
                       json={"name": "Client Project"}).status_code == 403
    assert client.post("/api/datasets", headers=owner_headers,
                       json={"name": "Client DS"}).status_code == 403
    assert client.get("/api/users-does-not-exist").status_code in (404, 405)
    # role change endpoint requires super_admin; the user directory is staff-only (V3.1)
    r = client.get("/api/auth/users", headers=owner_headers)
    assert r.status_code == 403
    r = client.put(f"/api/auth/users/{owner['user']['id']}/role", headers=owner_headers,
                   json={"role": "super_admin"})
    assert r.status_code == 403


def test_me_organizations_endpoint(client, db, auth_headers):
    headers, _ = auth_headers
    org = _create_org(client, headers, "My Org")
    owner = _register(client, "owner.my@test.dev", "Owner My")
    client.post(f"/api/organizations/{org['id']}/members", headers=headers,
                json={"email": "owner.my@test.dev", "role": "client_owner"})
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    r = client.get("/api/auth/me/organizations", headers=owner_headers)
    assert r.status_code == 200
    orgs = r.json()
    assert len(orgs) == 1 and orgs[0]["id"] == org["id"] and orgs[0]["role"] == "client_owner"
