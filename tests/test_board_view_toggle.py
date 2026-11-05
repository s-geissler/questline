import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture()
def view_toggle_env(app_env):
    client = TestClient(app_env["main"].app)
    client.headers["X-Requested-With"] = "XMLHttpRequest"
    client.post(
        "/api/auth/register",
        json={"email": "toggle-owner@example.com", "password": "test-password-only"},
    ).raise_for_status()
    client.headers["X-CSRF-Token"] = client.cookies["questline_csrf"]
    board = client.post("/api/boards", json={"name": "Positioned toggle"}).json()
    other = client.post("/api/boards", json={"name": "Other hub"}).json()
    yield {**app_env, "client": client, "board": board, "other": other}
    client.close()


def test_view_toggle_position_defaults_updates_and_is_scoped_to_board(view_toggle_env):
    ctx = view_toggle_env
    client = ctx["client"]
    board_id = ctx["board"]["id"]
    assert ctx["board"]["view_toggle_position"] == "north-east"
    for position in ("south-east", "hidden", "north-east"):
        response = client.put(f"/api/boards/{board_id}", json={"view_toggle_position": position})
        assert response.status_code == 200, response.text
        assert response.json()["view_toggle_position"] == position
        renamed = client.put(f"/api/boards/{board_id}", json={"name": "Renamed hub"})
        assert renamed.json()["view_toggle_position"] == position
        boards = {board["id"]: board for board in client.get("/api/boards").json()}
        assert boards[board_id]["view_toggle_position"] == position
        assert boards[ctx["other"]["id"]]["view_toggle_position"] == "north-east"
        page = client.get(f"/board/{board_id}")
        assert page.status_code == 200
        assert f'data-view-toggle-position="{position}"' in page.text
        assert f'data-position="{position}"' in page.text
    created = client.post("/api/boards", json={"name": "Hidden toggle", "view_toggle_position": "hidden"})
    assert created.status_code == 200, created.text
    assert created.json()["view_toggle_position"] == "hidden"


def test_invalid_view_toggle_positions_are_rejected_before_changes(view_toggle_env):
    ctx = view_toggle_env
    client = ctx["client"]
    board_id = ctx["board"]["id"]
    for invalid in (None, "north-west", "", True, {}):
        update = client.put(
            f"/api/boards/{board_id}", json={"name": "Invalid update", "view_toggle_position": invalid}
        )
        assert update.status_code == 422, update.text
        create = client.post("/api/boards", json={"name": "Invalid create", "view_toggle_position": invalid})
        assert create.status_code == 422, create.text
    boards = {board["id"]: board for board in client.get("/api/boards").json()}
    assert len(boards) == 2
    assert boards[board_id]["name"] == "Positioned toggle"
    assert boards[board_id]["view_toggle_position"] == "north-east"


@pytest.mark.parametrize("role", ["viewer", "editor"])
def test_only_board_managers_can_change_view_toggle_position(view_toggle_env, role):
    from authz import hash_password

    ctx = view_toggle_env
    db = ctx["db"]
    email = f"toggle-{role}@example.com"
    user = ctx["models"].User(
        email=email, display_name="Member", role="user", is_active=True,
        password_hash=hash_password("test-password-only"),
    )
    db.add(user)
    db.flush()
    db.add(ctx["models"].BoardMembership(board_id=ctx["board"]["id"], user_id=user.id, role=role))
    db.commit()
    ctx["client"].put(
        f"/api/boards/{ctx['board']['id']}", json={"view_toggle_position": "south-east"}
    ).raise_for_status()
    with TestClient(ctx["main"].app) as member:
        member.headers["X-Requested-With"] = "XMLHttpRequest"
        member.post("/api/auth/login", json={"email": email, "password": "test-password-only"}).raise_for_status()
        member.headers["X-CSRF-Token"] = member.cookies["questline_csrf"]
        denied = member.put(f"/api/boards/{ctx['board']['id']}", json={"view_toggle_position": "hidden"})
        assert denied.status_code == 403
        boards = member.get("/api/boards").json()
        assert boards[0]["view_toggle_position"] == "south-east"
        assert 'data-view-toggle-position="south-east"' in member.get(f"/board/{ctx['board']['id']}").text


def test_view_toggle_migration_preserves_existing_boards_and_is_idempotent(view_toggle_env):
    ctx = view_toggle_env
    engine = ctx["database"].engine
    with engine.begin() as conn:
        before = conn.execute(text("SELECT id, name, color, position, owner_user_id FROM boards ORDER BY id")).fetchall()
        conn.execute(text("ALTER TABLE boards DROP COLUMN view_toggle_position"))
    for _ in range(2):
        ctx["main"]._run_column_migrations()
        with engine.connect() as conn:
            assert conn.execute(text("SELECT id, name, color, position, owner_user_id FROM boards ORDER BY id")).fetchall() == before
        assert all(board["view_toggle_position"] == "north-east" for board in ctx["client"].get("/api/boards").json())
    ctx["client"].put(
        f"/api/boards/{ctx['board']['id']}", json={"view_toggle_position": "south-east"}
    ).raise_for_status()
    ctx["main"]._run_column_migrations()
    boards = {board["id"]: board for board in ctx["client"].get("/api/boards").json()}
    assert boards[ctx["board"]["id"]]["view_toggle_position"] == "south-east"
