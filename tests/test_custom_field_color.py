"""Tests for custom field dropdown color rendering."""
import json

from fastapi.testclient import TestClient


def test_stages_api_returns_custom_field_options_with_label_key(app_env):
    """Stages.py must serialize custom field options using 'label' key
    (not 'value'), matching what task_types.py stores in the DB."""
    db = app_env["db"]
    models = app_env["models"]

    from authz import hash_password

    # Create user, board, membership
    user = models.User(
        email="test@test.com",
        display_name="Test",
        password_hash=hash_password("pass"),
        role="admin",
        is_active=True,
    )
    db.add(user)
    db.flush()

    board = models.Board(name="Test Board", owner_user_id=user.id, position=0)
    db.add(board)
    db.flush()

    db.add(
        models.BoardMembership(board_id=board.id, user_id=user.id, role="owner")
    )

    # Create task type
    tt = models.TaskType(name="Bug", board_id=board.id, color=None)
    db.add(tt)
    db.flush()

    # Create custom field with options stored in DB using 'label' key
    # (same format as task_types.py produces)
    field = models.CustomFieldDef(
        task_type_id=tt.id,
        name="Priority",
        field_type="dropdown",
        show_on_card=True,
        options=json.dumps(
            [
                {"label": "High", "color": "#ef4444"},
                {"label": "Low", "color": "#22c55e"},
            ]
        ),
    )
    db.add(field)
    db.flush()

    # Create stage
    stage = models.Stage(name="To Do", board_id=board.id, position=0, row=0)
    db.add(stage)
    db.flush()

    # Create task with custom field value
    task = models.Task(title="Test", stage_id=stage.id, task_type_id=tt.id, position=0)
    db.add(task)
    db.flush()

    db.add(
        models.CustomFieldValue(task_id=task.id, field_def_id=field.id, value="High")
    )
    db.commit()

    # Now test _task_to_dict from stages
    from routes.stages import _task_to_dict

    result = _task_to_dict(task)

    # Verify options are present and use 'label' key
    options = result["task_type"]["custom_fields"][0]["options"]
    assert len(options) == 2, f"Expected 2 options, got {len(options)}"
    assert options[0]["label"] == "High", f"Expected label 'High', got {options[0]}"
    assert options[0]["color"] == "#ef4444", f"Expected color '#ef4444', got {options[0]}"
    assert options[1]["label"] == "Low", f"Expected label 'Low', got {options[1]}"
    assert options[1]["color"] == "#22c55e", f"Expected color '#22c55e', got {options[1]}"


def test_stages_api_keeps_null_option_color_as_null_for_field_color_fallback(app_env):
    db = app_env["db"]
    models = app_env["models"]

    user = models.User(
        email="null-color@test.com",
        display_name="Null Color",
        password_hash="x",
        role="admin",
        is_active=True,
    )
    db.add(user)
    db.flush()
    board = models.Board(name="Test Board", owner_user_id=user.id, position=0)
    db.add(board)
    db.flush()
    tt = models.TaskType(name="Paper", board_id=board.id, color=None)
    db.add(tt)
    db.flush()
    field = models.CustomFieldDef(
        task_type_id=tt.id,
        name="Assi",
        field_type="dropdown",
        color="#3b82f6",
        show_on_card=True,
        options=json.dumps([{"label": "David", "color": None}]),
    )
    db.add(field)
    db.flush()
    stage = models.Stage(name="Papers", board_id=board.id, position=0, row=0)
    db.add(stage)
    db.flush()
    task = models.Task(title="Architecture Simulation", stage_id=stage.id, task_type_id=tt.id, position=0)
    db.add(task)
    db.flush()
    db.add(models.CustomFieldValue(task_id=task.id, field_def_id=field.id, value="David"))
    db.commit()

    from routes.stages import _task_to_dict

    result = _task_to_dict(task)
    serialized_field = result["task_type"]["custom_fields"][0]
    assert serialized_field["color"] == "#3b82f6"
    assert serialized_field["options"] == [{"label": "David", "color": None}]


def test_board_custom_field_color_css_includes_arbitrary_option_colors(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]
    client = TestClient(main.app)

    register = client.post(
        "/api/auth/register",
        json={
            "email": "colors@example.com",
            "password": "supersecret",
            "display_name": "Colors",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert register.status_code == 200
    user_id = register.json()["id"]

    board = models.Board(name="Color Hub", owner_user_id=user_id, position=0)
    db.add(board)
    db.flush()
    db.add(models.BoardMembership(board_id=board.id, user_id=user_id, role="owner"))
    tt = models.TaskType(name="Bug", board_id=board.id, color=None)
    db.add(tt)
    db.flush()
    db.add(
        models.CustomFieldDef(
            task_type_id=tt.id,
            name="Impact",
            field_type="dropdown",
            show_on_card=True,
            options=json.dumps(
                [
                    {"label": "Major", "color": "#123456"},
                    {"label": "Risk", "color": "#ABC"},
                    {"label": "Bad", "color": "not-a-color"},
                ]
            ),
        )
    )
    db.commit()

    response = client.get(f"/board/{board.id}/custom-field-colors.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert ".swatch-123456 { background: #123456; }" in response.text
    assert ".swatch-aabbcc { background: #aabbcc; }" in response.text
    assert "not-a-color" not in response.text

    board_page = client.get(f"/board/{board.id}")
    assert board_page.status_code == 200
    assert f'/board/{board.id}/custom-field-colors.css' in board_page.text
