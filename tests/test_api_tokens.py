"""Tests for the API token + bearer auth + agent role feature."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def write_headers(client, **extra):
    """Return XHR + CSRF headers for the current session, plus any extras.

    httpx rejects `None` as a header value, so we omit the CSRF header
    entirely if no session is active.
    """
    csrf = client.cookies.get("questline_csrf")
    headers = dict(XHR_HEADERS)
    if csrf:
        headers["X-CSRF-Token"] = csrf
    headers.update({k: v for k, v in extra.items() if v is not None})
    return headers


def audit_events(caplog):
    return [json.loads(record.getMessage()) for record in caplog.records if record.name == "questline.audit"]


def register(client, email, display_name, password="supersecret"):
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": display_name},
        headers=XHR_HEADERS,
    )
    assert res.status_code == 200, res.text
    return res


def register_admin(client):
    return register(client, "admin-tokens@example.com", "Token Admin")


def login(client, email, password="supersecret"):
    """Clear current cookies and log in as the given user."""
    client.cookies.clear()
    res = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers=XHR_HEADERS,
    )
    assert res.status_code == 200, res.text
    return res


def activate_user(client, user_id):
    """Have the currently-logged-in admin activate a freshly-registered user."""
    res = client.put(
        f"/api/admin/users/{user_id}",
        json={"is_active": True},
        headers=write_headers(client),
    )
    assert res.status_code == 200, res.text
    return res


# ---------------------------------------------------------------------------
# Self-service
# ---------------------------------------------------------------------------


def test_user_can_mint_list_and_revoke_own_token(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    register_admin(client)

    created = client.post(
        "/api/tokens",
        json={"name": "alice-cli"},
        headers=write_headers(client),
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["name"] == "alice-cli"
    assert body["last_four"]
    assert body["raw_token"].startswith("qgl_")
    assert body["raw_token"].endswith(body["last_four"])

    listed = client.get("/api/tokens", headers=XHR_HEADERS)
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["name"] == "alice-cli"
    assert items[0]["last_four"] == body["last_four"]
    assert "raw_token" not in items[0]

    delete_res = client.delete(
        f"/api/tokens/{body['id']}",
        headers=write_headers(client),
    )
    assert delete_res.status_code == 200

    listed_after = client.get("/api/tokens", headers=XHR_HEADERS)
    assert listed_after.json() == []


def test_token_creation_requires_auth(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    res = client.post(
        "/api/tokens",
        json={"name": "anon"},
        headers=XHR_HEADERS,
    )
    # No session cookie → CSRF middleware rejects before the auth check runs.
    assert res.status_code == 403
    assert res.json()["detail"] == "CSRF validation failed"


def test_empty_token_name_is_rejected(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    register_admin(client)
    res = client.post(
        "/api/tokens",
        json={"name": "   "},
        headers=write_headers(client),
    )
    assert res.status_code == 400


def test_revoke_unknown_token_returns_404(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    register_admin(client)
    res = client.delete(
        "/api/tokens/9999",
        headers=write_headers(client),
    )
    assert res.status_code == 404


def test_cannot_revoke_another_users_token(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    register_admin(client)
    alice = register(client, "alice-tokens@example.com", "Alice")
    activate_user(client, alice.json()["id"])
    login(client, "alice-tokens@example.com")
    created = client.post(
        "/api/tokens",
        json={"name": "alice-token"},
        headers=write_headers(client),
    )
    alice_token_id = created.json()["id"]

    login(client, "admin-tokens@example.com")
    res = client.delete(
        f"/api/tokens/{alice_token_id}",
        headers=write_headers(client),
    )
    # Admin (or any other user) cannot revoke Alice's token via the
    # self-service endpoint — it filters by user_id and returns 404.
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Bearer auth + CSRF bypass
# ---------------------------------------------------------------------------


def test_bearer_token_authenticates_and_bypasses_csrf(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    register_admin(client)
    created = client.post(
        "/api/tokens",
        json={"name": "alice-bearer"},
        headers=write_headers(client),
    )
    raw_token = created.json()["raw_token"]

    client.cookies.clear()
    bearer_headers = {"Authorization": f"Bearer {raw_token}"}

    me = client.get("/api/auth/me", headers=bearer_headers)
    assert me.status_code == 200
    assert me.json()["email"] == "admin-tokens@example.com"

    board = client.post(
        "/api/boards",
        json={"name": "Bearer Board"},
        headers=bearer_headers,
    )
    assert board.status_code == 200, board.text
    assert board.json()["name"] == "Bearer Board"

    update = client.put(
        "/api/auth/profile",
        json={"display_name": "Renamed", "password": ""},
        headers=bearer_headers,
    )
    assert update.status_code == 200
    assert update.json()["display_name"] == "Renamed"


def test_revoked_bearer_token_is_rejected(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    register_admin(client)
    created = client.post(
        "/api/tokens",
        json={"name": "soon-revoked"},
        headers=write_headers(client),
    )
    raw_token = created.json()["raw_token"]
    token_id = created.json()["id"]

    client.cookies.clear()
    bearer = {"Authorization": f"Bearer {raw_token}"}
    assert client.get("/api/auth/me", headers=bearer).status_code == 200

    login(client, "admin-tokens@example.com")
    assert (
        client.delete(
            f"/api/tokens/{token_id}",
            headers=write_headers(client),
        ).status_code
        == 200
    )

    client.cookies.clear()
    assert client.get("/api/auth/me", headers=bearer).status_code == 401


def test_garbage_bearer_token_is_rejected(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    register_admin(client)
    client.cookies.clear()
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert res.status_code == 401


def test_bearer_token_marks_last_used_at(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    register_admin(client)
    created = client.post(
        "/api/tokens",
        json={"name": "track-last-used"},
        headers=write_headers(client),
    )
    raw = created.json()["raw_token"]

    client.cookies.clear()
    bearer = {"Authorization": f"Bearer {raw}"}
    assert client.get("/api/auth/me", headers=bearer).status_code == 200

    login(client, "admin-tokens@example.com")
    listed = client.get("/api/tokens", headers=XHR_HEADERS).json()
    assert listed, "expected the token to still be listed"
    assert listed[0]["last_used_at"] is not None


# ---------------------------------------------------------------------------
# Agent creation + admin token minting
# ---------------------------------------------------------------------------


def test_admin_can_create_agent_and_mint_token(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    register_admin(client)

    created = client.post(
        "/api/admin/agents",
        json={"display_name": "AcmeBot", "email": "acmebot@example.com"},
        headers=write_headers(client),
    )
    assert created.status_code == 200, created.text
    agent = created.json()
    assert agent["role"] == "agent"
    assert agent["is_active"] is True

    minted = client.post(
        f"/api/admin/agents/{agent['id']}/tokens",
        json={"name": "acmebot-primary"},
        headers=write_headers(client),
    )
    assert minted.status_code == 200, minted.text
    assert minted.json()["raw_token"].startswith("qgl_")

    listed = client.get(
        f"/api/admin/agents/{agent['id']}/tokens",
        headers=XHR_HEADERS,
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_non_admin_cannot_create_agent(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    register_admin(client)
    alice = register(client, "alice-tokens@example.com", "Alice")
    activate_user(client, alice.json()["id"])
    login(client, "alice-tokens@example.com")

    res = client.post(
        "/api/admin/agents",
        json={"display_name": "Should Fail", "email": "nope@example.com"},
        headers=write_headers(client),
    )
    assert res.status_code == 403


def test_admin_cannot_mint_token_for_non_agent_user(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    register_admin(client)
    res = client.post(
        "/api/admin/agents/999999/tokens",
        json={"name": "x"},
        headers=write_headers(client),
    )
    assert res.status_code == 404


def test_admin_agent_create_validates_email(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    register_admin(client)
    res = client.post(
        "/api/admin/agents",
        json={"display_name": "No Email", "email": "no-at-sign"},
        headers=write_headers(client),
    )
    assert res.status_code == 400

    res = client.post(
        "/api/admin/agents",
        json={"display_name": "Dup", "email": "admin-tokens@example.com"},
        headers=write_headers(client),
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Agent can use the API
# ---------------------------------------------------------------------------


def test_agent_can_be_added_to_board_and_create_task_via_bearer(app_env):
    main = app_env["main"]
    client = TestClient(main.app)

    register_admin(client)
    board = client.post(
        "/api/boards",
        json={"name": "Agent Board"},
        headers=write_headers(client),
    ).json()
    stage = client.post(
        "/api/stages",
        json={"name": "To Do", "board_id": board["id"]},
        headers=write_headers(client),
    ).json()

    agent = client.post(
        "/api/admin/agents",
        json={"display_name": "AcmeBot", "email": "acmebot@example.com"},
        headers=write_headers(client),
    ).json()
    raw_token = client.post(
        f"/api/admin/agents/{agent['id']}/tokens",
        json={"name": "acmebot"},
        headers=write_headers(client),
    ).json()["raw_token"]

    add_member = client.post(
        f"/api/boards/{board['id']}/members",
        json={"email": "acmebot@example.com", "role": "editor"},
        headers=write_headers(client),
    )
    assert add_member.status_code == 200, add_member.text

    bearer = {"Authorization": f"Bearer {raw_token}"}
    task = client.post(
        "/api/tasks",
        json={"title": "Hello from agent", "stage_id": stage["id"]},
        headers=bearer,
    )
    assert task.status_code == 200, task.text
    assert task.json()["title"] == "Hello from agent"


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------


def test_deactivating_user_revokes_their_tokens(app_env):
    main = app_env["main"]
    client = TestClient(main.app)

    register_admin(client)
    alice = register(client, "alice-tokens@example.com", "Alice")
    activate_user(client, alice.json()["id"])
    login(client, "alice-tokens@example.com")
    res = client.post(
        "/api/tokens",
        json={"name": "alice-token"},
        headers=write_headers(client),
    )
    raw = res.json()["raw_token"]

    login(client, "admin-tokens@example.com")
    deact = client.put(
        f"/api/admin/users/{alice.json()['id']}",
        json={"is_active": False},
        headers=write_headers(client),
    )
    assert deact.status_code == 200

    client.cookies.clear()
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {raw}"}).status_code == 401


def test_password_reset_revokes_tokens(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    register_admin(client)
    alice = register(client, "alice-tokens@example.com", "Alice")
    activate_user(client, alice.json()["id"])
    login(client, "alice-tokens@example.com")
    res = client.post(
        "/api/tokens",
        json={"name": "alice"},
        headers=write_headers(client),
    )
    raw = res.json()["raw_token"]

    login(client, "admin-tokens@example.com")
    res = client.put(
        f"/api/admin/users/{alice.json()['id']}",
        json={"password": "newsecret1"},
        headers=write_headers(client),
    )
    assert res.status_code == 200

    client.cookies.clear()
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {raw}"}).status_code == 401


def test_admin_can_revoke_specific_agent_token(app_env):
    main = app_env["main"]
    client = TestClient(main.app)
    register_admin(client)
    agent = client.post(
        "/api/admin/agents",
        json={"display_name": "AcmeBot", "email": "acmebot@example.com"},
        headers=write_headers(client),
    ).json()
    minted = client.post(
        f"/api/admin/agents/{agent['id']}/tokens",
        json={"name": "first"},
        headers=write_headers(client),
    ).json()

    res = client.delete(
        f"/api/admin/agents/{agent['id']}/tokens/{minted['id']}",
        headers=write_headers(client),
    )
    assert res.status_code == 200

    listed = client.get(
        f"/api/admin/agents/{agent['id']}/tokens",
        headers=XHR_HEADERS,
    )
    assert listed.json() == []


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def test_token_authenticated_request_is_audited_with_token_id_and_kind(app_env, caplog):
    main = app_env["main"]
    client = TestClient(main.app)
    caplog.set_level("INFO", logger="questline.audit")

    register_admin(client)
    res = client.post(
        "/api/tokens",
        json={"name": "audit-token"},
        headers=write_headers(client),
    )
    raw = res.json()["raw_token"]
    token_id = res.json()["id"]

    client.cookies.clear()
    bearer = {"Authorization": f"Bearer {raw}"}
    # Update the admin's display name via bearer — `auth_update_profile`
    # does not audit by itself, but we'll trigger a known audited path
    # by having admin change its own password (which revokes tokens
    # and emits `api_tokens_revoked_for_user` with the new actor).
    profile = client.put(
        "/api/auth/profile",
        json={"display_name": "Renamed", "password": "newsecret1"},
        headers=bearer,
    )
    assert profile.status_code == 200

    events = audit_events(caplog)
    create_event = next(e for e in events if e["event"] == "api_token_created")
    assert create_event["actor_user_id"] is not None
    assert create_event["actor_token_id"] is None
    assert create_event["actor_kind"] == "session"

    # The password change should have emitted an audit event tagged
    # with the token id (since the request came via bearer).
    password_event = next(
        (e for e in events if e["event"] == "password_changed"), None
    )
    assert password_event is not None, "expected a password_changed audit event"
    assert password_event["actor_token_id"] == token_id
    assert password_event["actor_kind"] == "token"


# ---------------------------------------------------------------------------
# End-to-end: the original goal
# ---------------------------------------------------------------------------


def test_create_task_in_stage_via_bearer_token(app_env):
    main = app_env["main"]
    client = TestClient(main.app)

    register_admin(client)
    board = client.post(
        "/api/boards",
        json={"name": "My Hub"},
        headers=write_headers(client),
    ).json()
    backlog = client.post(
        "/api/stages",
        json={"name": "Backlog", "board_id": board["id"]},
        headers=write_headers(client),
    ).json()
    in_progress = client.post(
        "/api/stages",
        json={"name": "In Progress", "board_id": board["id"]},
        headers=write_headers(client),
    ).json()

    res = client.post(
        "/api/tokens",
        json={"name": "agent"},
        headers=write_headers(client),
    )
    raw = res.json()["raw_token"]

    client.cookies.clear()
    bearer = {"Authorization": f"Bearer {raw}"}

    stages = client.get(f"/api/stages?board_id={board['id']}", headers=bearer).json()
    backlog_stage = next(s for s in stages if s["name"] == "Backlog")
    assert backlog_stage["id"] == backlog["id"]

    task = client.post(
        "/api/tasks",
        json={"title": "Buy milk", "stage_id": backlog_stage["id"]},
        headers=bearer,
    )
    assert task.status_code == 200
    assert task.json()["title"] == "Buy milk"
    assert task.json()["stage_id"] == backlog["id"]

    move = client.put(
        f"/api/tasks/{task.json()['id']}/move",
        json={"stage_id": in_progress["id"], "position": 0},
        headers=bearer,
    )
    assert move.status_code == 200
    assert move.json()["stage_id"] == in_progress["id"]
