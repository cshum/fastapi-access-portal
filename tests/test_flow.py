"""The end-to-end onboarding flow, exercised through the HTTP surface.

Run with:  pytest -q
"""

from tests.conftest import auth_header

APPROVER = {"email": "approver@example.com", "full_name": "Ada Approver", "password": "supersecret1"}
MEMBER = {"email": "member@example.com", "full_name": "Mo Member", "password": "supersecret2"}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_first_user_becomes_approver(client):
    resp = client.post("/auth/register", json=APPROVER)
    assert resp.status_code == 201
    assert resp.json()["role"] == "approver"

    resp = client.post("/auth/register", json=MEMBER)
    assert resp.json()["role"] == "member"


def test_duplicate_email_rejected(client):
    client.post("/auth/register", json=APPROVER)
    resp = client.post("/auth/register", json=APPROVER)
    assert resp.status_code == 409


def test_short_password_rejected(client):
    resp = client.post(
        "/auth/register",
        json={"email": "x@example.com", "full_name": "X", "password": "short"},
    )
    assert resp.status_code == 422  # Pydantic validation, before any handler runs


def test_unauthenticated_request_is_401(client):
    assert client.get("/requests").status_code == 401


def test_full_onboarding_flow(client):
    # 1. bootstrap an approver, then a member
    client.post("/auth/register", json=APPROVER)
    client.post("/auth/register", json=MEMBER)
    approver_h = auth_header(client, APPROVER["email"], APPROVER["password"])
    member_h = auth_header(client, MEMBER["email"], MEMBER["password"])

    # 2. an approver creates a group (stands in for an AD group)
    resp = client.post(
        "/admin/groups",
        json={"name": "finance-readers", "description": "Read access to finance reporting"},
        headers=approver_h,
    )
    assert resp.status_code == 201
    group_id = resp.json()["id"]

    # 3. a member may NOT create groups
    assert (
        client.post("/admin/groups", json={"name": "sneaky"}, headers=member_h).status_code
        == 403
    )

    # 4. the member requests access
    resp = client.post(
        "/requests",
        json={"group_id": group_id, "justification": "I need the monthly revenue report."},
        headers=member_h,
    )
    assert resp.status_code == 201
    request_id = resp.json()["id"]
    assert resp.json()["status"] == "pending"

    # 5. a second identical request is refused while one is pending
    resp = client.post(
        "/requests",
        json={"group_id": group_id, "justification": "Please, again."},
        headers=member_h,
    )
    assert resp.status_code == 409

    # 6. the approver sees it in the pending queue
    resp = client.get("/admin/requests?status_filter=pending", headers=approver_h)
    assert [r["id"] for r in resp.json()] == [request_id]

    # 7. approve it
    resp = client.post(f"/admin/requests/{request_id}/approve", headers=approver_h)
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert resp.json()["decided_at"] is not None

    # 8. the member now holds the group
    member_id = client.get("/auth/me", headers=member_h).json()["id"]
    resp = client.get(f"/admin/users/{member_id}/memberships", headers=approver_h)
    assert [m["group_id"] for m in resp.json()] == [group_id]

    # 9. re-deciding the same request is refused
    assert (
        client.post(f"/admin/requests/{request_id}/approve", headers=approver_h).status_code
        == 409
    )

    # 10. with the first request closed, the member may request again
    resp = client.post(
        "/requests",
        json={"group_id": group_id, "justification": "Requesting again after the first grant."},
        headers=member_h,
    )
    assert resp.status_code == 201


def test_rejection_does_not_grant_membership(client):
    client.post("/auth/register", json=APPROVER)
    client.post("/auth/register", json=MEMBER)
    approver_h = auth_header(client, APPROVER["email"], APPROVER["password"])
    member_h = auth_header(client, MEMBER["email"], MEMBER["password"])

    group_id = client.post(
        "/admin/groups", json={"name": "g"}, headers=approver_h
    ).json()["id"]
    request_id = client.post(
        "/requests",
        json={"group_id": group_id, "justification": "A justification long enough."},
        headers=member_h,
    ).json()["id"]

    resp = client.post(f"/admin/requests/{request_id}/reject", headers=approver_h)
    assert resp.json()["status"] == "rejected"

    member_id = client.get("/auth/me", headers=member_h).json()["id"]
    assert client.get(f"/admin/users/{member_id}/memberships", headers=approver_h).json() == []
