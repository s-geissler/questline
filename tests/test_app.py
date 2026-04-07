from datetime import timedelta

import pytest
from fastapi import HTTPException


def request_with_cookie(path="/", cookie=None):
    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode("utf-8")))
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
    }


def create_board(main, db, name="Test Board", color="#3b82f6"):
    return main.create_board(main.BoardCreate(name=name, color=color), db)


def create_stage(main, db, board_id, name, row=0):
    return main.create_stage(main.StageCreate(name=name, board_id=board_id, row=row), db)


def create_task_type(main, db, board_id, name="Bug", color="#ef4444", is_epic=False):
    return main.create_task_type(
        main.TaskTypeCreate(name=name, board_id=board_id, color=color, is_epic=is_epic),
        db,
    )


def create_saved_filter(main, db, board_id, name="Saved Filter", definition=None):
    return main.create_saved_filter(
        main.SavedFilterCreate(
            name=name,
            board_id=board_id,
            definition=definition or main.default_filter_definition(),
        ),
        db,
    )


def create_task(main, db, stage_id, title, task_type_id=None, due_date=None):
    return main.create_task(
        main.TaskCreate(
            title=title,
            stage_id=stage_id,
            task_type_id=task_type_id,
            due_date=due_date,
        ),
        db,
    )


def add_custom_field(main, db, task_type_id, name, field_type="text", options=None):
    return main.add_custom_field(
        task_type_id,
        main.CustomFieldCreate(
            name=name,
            field_type=field_type,
            options=options,
        ),
        db,
    )


def test_dropdown_custom_field_options_can_store_per_option_colors(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    task_type = create_task_type(main, db, board["id"], name="Bug")

    field = add_custom_field(
        main,
        db,
        task_type["id"],
        "Status",
        field_type="dropdown",
        options=[
            {"label": "Open", "color": "#ef4444"},
            {"label": "Ready", "color": "#22c55e"},
        ],
    )
    assert field["options"] == [
        {"label": "Open", "color": "#ef4444"},
        {"label": "Ready", "color": "#22c55e"},
    ]

    updated = main.update_custom_field(
        task_type["id"],
        field["id"],
        main.CustomFieldCreate(
            name="Status",
            field_type="dropdown",
            show_on_card=True,
            options=["Open", {"label": "Done", "color": "#3b82f6"}],
        ),
        db,
    )
    assert updated["options"] == [
        {"label": "Open", "color": None},
        {"label": "Done", "color": "#3b82f6"},
    ]


def test_task_type_is_preserved_and_can_be_cleared(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    stage = create_stage(main, db, board["id"], "Backlog")
    bug_type = create_task_type(main, db, board["id"], name="Bug")
    task = create_task(main, db, stage["id"], "Fix login", task_type_id=bug_type["id"])

    fetched = main.get_task(task["id"], db)
    assert fetched["task_type_id"] == bug_type["id"]
    assert fetched["task_type"]["name"] == "Bug"

    cleared = main.update_task(task["id"], main.TaskUpdate(task_type_id=None), db)
    assert cleared["task_type_id"] is None
    assert cleared["task_type"] is None


def test_due_date_round_trip_on_task(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    stage = create_stage(main, db, board["id"], "Backlog")
    task = create_task(main, db, stage["id"], "Ship release", due_date="2026-04-10")

    assert task["due_date"] == "2026-04-10"

    updated = main.update_task(task["id"], main.TaskUpdate(due_date="2026-04-17"), db)
    assert updated["due_date"] == "2026-04-17"


def test_task_assignee_can_be_set_and_cleared(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]
    board = create_board(main, db)
    stage = create_stage(main, db, board["id"], "Backlog")
    task = create_task(main, db, stage["id"], "Assigned task")

    assignee = models.User(
        email="assignee@example.com",
        password_hash="x",
        display_name="Assigned User",
        is_active=True,
    )
    db.add(assignee)
    db.commit()
    board_row = db.query(models.Board).filter(models.Board.id == board["id"]).first()
    main.ensure_board_membership(board_row, assignee, "viewer", db)
    db.commit()

    updated = main.update_task(task["id"], main.TaskUpdate(assignee_user_id=assignee.id), db)
    assert updated["assignee_user_id"] == assignee.id
    assert updated["assignee"]["display_name"] == "Assigned User"

    cleared = main.update_task(task["id"], main.TaskUpdate(assignee_user_id=None), db)
    assert cleared["assignee_user_id"] is None
    assert cleared["assignee"] is None


def test_task_assignee_must_be_active_board_member(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]
    board = create_board(main, db)
    stage = create_stage(main, db, board["id"], "Backlog")
    task = create_task(main, db, stage["id"], "Assigned task")

    outsider = models.User(
        email="outsider-assignee@example.com",
        password_hash="x",
        display_name="Outsider",
        is_active=True,
    )
    db.add(outsider)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        main.update_task(task["id"], main.TaskUpdate(assignee_user_id=outsider.id), db)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Assignee must be a board member"


def test_task_reorder_updates_positions_and_stage(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    done = create_stage(main, db, board["id"], "Done")
    task_a = create_task(main, db, backlog["id"], "A")
    task_b = create_task(main, db, backlog["id"], "B")

    response = main.reorder_tasks(
        main.ReorderTasks(stage_id=done["id"], ids=[task_b["id"], task_a["id"]]),
        db,
    )
    assert response == {"ok": True}

    stages_json = main.get_stages(board["id"], db)
    done_stage = next(stage for stage in stages_json if stage["id"] == done["id"])
    assert [task["id"] for task in done_stage["tasks"]] == [task_b["id"], task_a["id"]]
    assert [task["position"] for task in done_stage["tasks"]] == [0, 1]


def test_stage_reorder_updates_positions(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    todo = create_stage(main, db, board["id"], "Todo")
    doing = create_stage(main, db, board["id"], "Doing")
    done = create_stage(main, db, board["id"], "Done")

    response = main.reorder_stages(main.ReorderStages(ids=[done["id"], todo["id"], doing["id"]]), db)
    assert response == {"ok": True}

    stages = main.get_stages(board["id"], db)
    assert [stage["id"] for stage in stages] == [done["id"], todo["id"], doing["id"]]


def test_stages_can_be_created_and_reordered_across_rows(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    top = create_stage(main, db, board["id"], "Top")
    lower_a = create_stage(main, db, board["id"], "Lower A", row=1)
    lower_b = create_stage(main, db, board["id"], "Lower B", row=1)

    stages = main.get_stages(board["id"], db)
    assert [(stage["name"], stage["row"], stage["position"]) for stage in stages] == [
        ("Top", 0, 0),
        ("Lower A", 1, 0),
        ("Lower B", 1, 1),
    ]

    response = main.reorder_stages(
        main.ReorderStages(
            stages=[
                {"id": lower_b["id"], "row": 0, "position": 0},
                {"id": top["id"], "row": 0, "position": 1},
                {"id": lower_a["id"], "row": 1, "position": 0},
            ]
        ),
        db,
    )
    assert response == {"ok": True}

    stages = main.get_stages(board["id"], db)
    assert [(stage["id"], stage["row"], stage["position"]) for stage in stages] == [
        (lower_b["id"], 0, 0),
        (top["id"], 0, 1),
        (lower_a["id"], 1, 0),
    ]


def test_task_created_automation_can_move_stage(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    intake = create_stage(main, db, board["id"], "Intake")
    triage = create_stage(main, db, board["id"], "Triage")

    response = main.create_automation(
        main.AutomationCreate(
            name="Route new work to triage",
            board_id=board["id"],
            trigger_type="task_created",
            trigger_stage_id=intake["id"],
            action_type="move_to_stage",
            action_stage_id=triage["id"],
        ),
        db,
    )
    assert response["action_stage_id"] == triage["id"]

    task = create_task(main, db, intake["id"], "New task")
    assert task["stage_id"] == triage["id"]


def test_task_done_automation_can_set_task_type(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    bug_type = create_task_type(main, db, board["id"], name="Bug")
    task = create_task(main, db, backlog["id"], "Investigate outage")

    response = main.create_automation(
        main.AutomationCreate(
            name="Done becomes bug",
            board_id=board["id"],
            trigger_type="task_done",
            action_type="set_task_type",
            action_task_type_id=bug_type["id"],
        ),
        db,
    )
    assert response["action_task_type_id"] == bug_type["id"]

    updated = main.update_task(task["id"], main.TaskUpdate(done=True), db)
    assert updated["task_type_id"] == bug_type["id"]
    assert updated["task_type"]["name"] == "Bug"


def test_checklist_completed_automation_can_mark_task_done(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    task = create_task(main, db, backlog["id"], "Release checklist")

    response = main.create_automation(
        main.AutomationCreate(
            name="Checklist completion closes task",
            board_id=board["id"],
            trigger_type="checklist_completed",
            action_type="set_done",
        ),
        db,
    )
    assert response["action_type"] == "set_done"

    item_one = main.add_checklist_item(task["id"], main.ChecklistItemCreate(title="Docs"), db)
    item_two = main.add_checklist_item(task["id"], main.ChecklistItemCreate(title="Deploy"), db)

    done_one = main.update_checklist_item(
        task["id"],
        item_one["id"],
        main.ChecklistItemUpdate(done=True),
        db,
    )
    assert done_one["done"] is True
    intermediate = main.get_task(task["id"], db)
    assert intermediate["done"] is False

    done_two = main.update_checklist_item(
        task["id"],
        item_two["id"],
        main.ChecklistItemUpdate(done=True),
        db,
    )
    assert done_two["done"] is True
    final_task = main.get_task(task["id"], db)
    assert final_task["done"] is True


def test_recurring_task_generates_new_task_in_configured_stage(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    done = create_stage(main, db, board["id"], "Done")
    task = create_task(main, db, backlog["id"], "Payroll review", due_date="2026-04-03")

    recurrence = main.upsert_task_recurrence(
        task["id"],
        main.TaskRecurrenceUpdate(
            enabled=True,
            mode="create_new",
            frequency="weekly",
            interval=1,
            next_run_on="2026-04-03",
            spawn_stage_id=backlog["id"],
        ),
        db,
    )
    assert recurrence["spawn_stage_id"] == backlog["id"]

    main.move_task(task["id"], main.TaskMove(stage_id=done["id"], position=0), db)
    created = main.process_due_recurrences(db, today=main.date(2026, 4, 3))
    assert created == 1

    stages = main.get_stages(board["id"], db)
    backlog_stage = next(stage for stage in stages if stage["id"] == backlog["id"])
    done_stage = next(stage for stage in stages if stage["id"] == done["id"])
    spawned = next(t for t in backlog_stage["tasks"] if t["title"] == "Payroll review" and t["id"] != task["id"])

    assert spawned["stage_id"] == backlog["id"]
    assert spawned["due_date"] == "2026-04-03"
    assert all(t["id"] != spawned["id"] for t in done_stage["tasks"])


def test_recurring_task_is_deleted_with_source_task(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    task = create_task(main, db, backlog["id"], "Delete me later")

    main.upsert_task_recurrence(
        task["id"],
        main.TaskRecurrenceUpdate(
            enabled=True,
            mode="create_new",
            frequency="weekly",
            interval=1,
            next_run_on="2026-04-03",
            spawn_stage_id=backlog["id"],
        ),
        db,
    )

    main.delete_task(task["id"], db)
    assert db.query(models.TaskRecurrence).count() == 0
    assert main.process_due_recurrences(db, today=main.date(2026, 4, 3)) == 0


def test_recurring_task_copies_custom_fields_and_checklist(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    task_type = create_task_type(main, db, board["id"], name="Routine")
    field = add_custom_field(main, db, task_type["id"], "Priority")
    task = create_task(main, db, backlog["id"], "Monthly close", task_type_id=task_type["id"])
    main.update_task(task["id"], main.TaskUpdate(custom_fields={str(field["id"]): "High"}), db)
    main.add_checklist_item(task["id"], main.ChecklistItemCreate(title="Review"), db)
    main.add_checklist_item(task["id"], main.ChecklistItemCreate(title="Approve"), db)

    main.upsert_task_recurrence(
        task["id"],
        main.TaskRecurrenceUpdate(
            enabled=True,
            mode="create_new",
            frequency="monthly",
            interval=1,
            next_run_on="2026-04-03",
            spawn_stage_id=backlog["id"],
        ),
        db,
    )

    assert main.process_due_recurrences(db, today=main.date(2026, 4, 3)) == 1
    stages = main.get_stages(board["id"], db)
    copies = [t for t in next(stage for stage in stages if stage["id"] == backlog["id"])["tasks"] if t["title"] == "Monthly close"]
    cloned = max(copies, key=lambda t: t["id"])

    assert cloned["custom_field_values"][str(field["id"])] == "High"
    assert [item["title"] for item in cloned["checklist"]] == ["Review", "Approve"]
    assert all(item["done"] is False for item in cloned["checklist"])


def test_recurring_task_next_run_advances_after_generation(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    task = create_task(main, db, backlog["id"], "Weekly sync")

    main.upsert_task_recurrence(
        task["id"],
        main.TaskRecurrenceUpdate(
            enabled=True,
            mode="create_new",
            frequency="weekly",
            interval=2,
            next_run_on="2026-04-03",
            spawn_stage_id=backlog["id"],
        ),
        db,
    )

    assert main.process_due_recurrences(db, today=main.date(2026, 4, 3)) == 1
    recurrence = db.query(models.TaskRecurrence).filter(models.TaskRecurrence.task_id == task["id"]).first()
    assert recurrence.next_run_on == "2026-04-17"


def test_recurring_task_can_reuse_existing_objective(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    done = create_stage(main, db, board["id"], "Done")
    task = create_task(main, db, backlog["id"], "Daily standup", due_date="2026-04-02")
    item = main.add_checklist_item(task["id"], main.ChecklistItemCreate(title="Prepare notes"), db)
    main.update_checklist_item(task["id"], item["id"], main.ChecklistItemUpdate(done=True), db)
    main.update_task(task["id"], main.TaskUpdate(done=True), db)
    main.move_task(task["id"], main.TaskMove(stage_id=done["id"], position=0), db)

    recurrence = main.upsert_task_recurrence(
        task["id"],
        main.TaskRecurrenceUpdate(
            enabled=True,
            mode="reuse_existing",
            frequency="daily",
            interval=1,
            next_run_on="2026-04-03",
            spawn_stage_id=backlog["id"],
        ),
        db,
    )
    assert recurrence["mode"] == "reuse_existing"

    processed = main.process_due_recurrences(db, today=main.date(2026, 4, 3))
    assert processed == 1

    refreshed = main.get_task(task["id"], db)
    assert refreshed["id"] == task["id"]
    assert refreshed["done"] is False
    assert refreshed["stage_id"] == backlog["id"]
    assert refreshed["due_date"] == "2026-04-03"
    assert refreshed["checklist"][0]["done"] is False


def test_recurring_reuse_existing_does_not_create_second_task(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    task = create_task(main, db, backlog["id"], "Monthly inventory")

    main.upsert_task_recurrence(
        task["id"],
        main.TaskRecurrenceUpdate(
            enabled=True,
            mode="reuse_existing",
            frequency="monthly",
            interval=1,
            next_run_on="2026-04-03",
            spawn_stage_id=backlog["id"],
        ),
        db,
    )

    before_count = db.query(models.Task).count()
    assert main.process_due_recurrences(db, today=main.date(2026, 4, 3)) == 1
    after_count = db.query(models.Task).count()
    assert after_count == before_count


def test_marking_quest_done_marks_checklist_items_and_spawned_children_done(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    quest_type = create_task_type(main, db, board["id"], name="Quest", is_epic=True)
    quest = create_task(main, db, backlog["id"], "Launch quest", task_type_id=quest_type["id"])

    item_one = main.add_checklist_item(quest["id"], main.ChecklistItemCreate(title="Child A"), db)
    item_two = main.add_checklist_item(quest["id"], main.ChecklistItemCreate(title="Child B"), db)

    updated = main.update_task(quest["id"], main.TaskUpdate(done=True), db)
    assert updated["done"] is True
    assert all(item["done"] is True for item in updated["checklist"])

    child_one = main.get_task(item_one["spawned_task_id"], db)
    child_two = main.get_task(item_two["spawned_task_id"], db)
    assert child_one["done"] is True
    assert child_two["done"] is True


def test_spawned_quest_children_include_parent_quest_link(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    quest_type = create_task_type(main, db, board["id"], name="Quest", is_epic=True)
    quest = create_task(main, db, backlog["id"], "Parent quest", task_type_id=quest_type["id"])

    item = main.add_checklist_item(quest["id"], main.ChecklistItemCreate(title="Spawned child"), db)
    child = main.get_task(item["spawned_task_id"], db)

    assert child["parent_task"] is not None
    assert child["parent_task"]["id"] == quest["id"]
    assert child["parent_task"]["title"] == "Parent quest"


def test_editing_quest_checklist_item_renames_spawned_objective(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    quest_type = create_task_type(main, db, board["id"], name="Quest", is_epic=True)
    quest = create_task(main, db, backlog["id"], "Parent quest", task_type_id=quest_type["id"])

    item = main.add_checklist_item(quest["id"], main.ChecklistItemCreate(title="Initial child"), db)

    updated_item = main.update_checklist_item(
        quest["id"],
        item["id"],
        main.ChecklistItemUpdate(title="Renamed child"),
        db,
    )

    assert updated_item["title"] == "Renamed child"
    child = main.get_task(item["spawned_task_id"], db)
    assert child["title"] == "Renamed child"


def test_editing_spawned_objective_renames_linked_checklist_item(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    quest_type = create_task_type(main, db, board["id"], name="Quest", is_epic=True)
    quest = create_task(main, db, backlog["id"], "Parent quest", task_type_id=quest_type["id"])

    item = main.add_checklist_item(quest["id"], main.ChecklistItemCreate(title="Initial child"), db)

    updated_child = main.update_task(
        item["spawned_task_id"],
        main.TaskUpdate(title="Renamed child"),
        db,
    )

    assert updated_child["title"] == "Renamed child"
    refreshed_quest = main.get_task(quest["id"], db)
    assert refreshed_quest["checklist"][0]["title"] == "Renamed child"


def test_deleting_quest_checklist_item_deletes_spawned_objective(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    quest_type = create_task_type(main, db, board["id"], name="Quest", is_epic=True)
    quest = create_task(main, db, backlog["id"], "Parent quest", task_type_id=quest_type["id"])

    item = main.add_checklist_item(quest["id"], main.ChecklistItemCreate(title="Spawned child"), db)

    response = main.delete_checklist_item(quest["id"], item["id"], db)

    assert response == {"ok": True}
    assert db.query(main.models.ChecklistItem).filter(main.models.ChecklistItem.id == item["id"]).first() is None
    with pytest.raises(HTTPException):
        main.get_task(item["spawned_task_id"], db)


def test_deleting_spawned_objective_deletes_linked_checklist_item(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    quest_type = create_task_type(main, db, board["id"], name="Quest", is_epic=True)
    quest = create_task(main, db, backlog["id"], "Parent quest", task_type_id=quest_type["id"])

    item = main.add_checklist_item(quest["id"], main.ChecklistItemCreate(title="Spawned child"), db)

    response = main.delete_task(item["spawned_task_id"], db)

    assert response == {"ok": True}
    with pytest.raises(HTTPException):
        main.get_task(item["spawned_task_id"], db)
    refreshed = main.get_task(quest["id"], db)
    assert refreshed["checklist"] == []


def test_description_on_card_uses_type_default_and_task_override(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    task_type = main.create_task_type(
        main.TaskTypeCreate(
            name="Feature",
            board_id=board["id"],
            show_description_on_card=True,
        ),
        db,
    )
    task = create_task(main, db, backlog["id"], "Card desc", task_type_id=task_type["id"])

    updated = main.update_task(
        task["id"],
        main.TaskUpdate(description="Visible on card by default"),
        db,
    )
    assert updated["effective_show_description_on_card"] is True
    assert updated["show_description_on_card"] is None
    assert updated["task_type"]["show_description_on_card"] is True

    overridden = main.update_task(
        task["id"],
        main.TaskUpdate(show_description_on_card=False),
        db,
    )
    assert overridden["effective_show_description_on_card"] is False
    assert overridden["show_description_on_card"] is False


def test_checklist_on_card_uses_type_default_and_task_override(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    task_type = main.create_task_type(
        main.TaskTypeCreate(
            name="Checklist Feature",
            board_id=board["id"],
            show_checklist_on_card=True,
        ),
        db,
    )
    task = create_task(main, db, backlog["id"], "Card checklist", task_type_id=task_type["id"])

    main.add_checklist_item(task["id"], main.ChecklistItemCreate(title="Visible item"), db)
    fetched = main.get_task(task["id"], db)
    assert fetched["effective_show_checklist_on_card"] is True
    assert fetched["show_checklist_on_card"] is None
    assert fetched["task_type"]["show_checklist_on_card"] is True

    overridden = main.update_task(
        task["id"],
        main.TaskUpdate(show_checklist_on_card=False),
        db,
    )
    assert overridden["effective_show_checklist_on_card"] is False
    assert overridden["show_checklist_on_card"] is False


def test_saved_filter_rejects_malformed_custom_field_rule(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)

    with pytest.raises(HTTPException) as exc:
        create_saved_filter(
            main,
            db,
            board["id"],
            definition={
                "op": "and",
                "selected_task_type_id": None,
                "source_board_ids": [],
                "rules": [
                    {"field": "custom:not-a-number", "operator": "eq", "value": "x"},
                ],
            },
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid custom field rule"


def test_clear_completed_stage_removes_completed_quests_and_spawned_children(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    quest_type = create_task_type(main, db, board["id"], name="Quest", is_epic=True)

    completed_task = create_task(main, db, backlog["id"], "Completed task")
    active_task = create_task(main, db, backlog["id"], "Active task")
    quest = create_task(main, db, backlog["id"], "Completed quest", task_type_id=quest_type["id"])
    child_item = main.add_checklist_item(quest["id"], main.ChecklistItemCreate(title="Spawned child"), db)

    main.update_task(completed_task["id"], main.TaskUpdate(done=True), db)
    main.update_task(quest["id"], main.TaskUpdate(done=True), db)

    response = main.clear_completed_stage_tasks(backlog["id"], db)
    assert response["ok"] is True
    assert response["deleted"] == 3

    remaining = main.get_stages(board["id"], db)
    backlog_stage = next(stage for stage in remaining if stage["id"] == backlog["id"])
    assert [task["title"] for task in backlog_stage["tasks"]] == ["Active task"]

    child_task = db.query(app_env["models"].Task).filter(
        app_env["models"].Task.id == child_item["spawned_task_id"]
    ).first()
    assert child_task is None


def test_log_stage_shows_filtered_tasks_without_owning_them(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    done = create_stage(main, db, board["id"], "Done")
    bug_type = create_task_type(main, db, board["id"], name="Bug")
    log_stage = create_stage(main, db, board["id"], "Bug Log")
    saved_filter = create_saved_filter(
        main,
        db,
        board["id"],
        name="Open Bugs",
        definition={
            "op": "and",
            "selected_task_type_id": bug_type["id"],
            "rules": [
                {"field": "done", "operator": "eq", "value": False},
            ],
        },
    )

    main.update_stage_config(
        log_stage["id"],
        main.StageConfigUpdate(
            is_log=True,
            filter_id=saved_filter["id"],
        ),
        db,
    )

    bug_task = create_task(main, db, backlog["id"], "Bug one", task_type_id=bug_type["id"])
    done_task = create_task(main, db, done["id"], "Done bug", task_type_id=bug_type["id"])
    main.update_task(done_task["id"], main.TaskUpdate(done=True), db)
    create_task(main, db, backlog["id"], "Feature one")

    stages = main.get_stages(board["id"], db)
    rendered_log = next(stage for stage in stages if stage["id"] == log_stage["id"])
    assert rendered_log["is_log"] is True
    assert [task["id"] for task in rendered_log["tasks"]] == [bug_task["id"]]
    assert rendered_log["tasks"][0]["stage_id"] == backlog["id"]


def test_log_stage_includes_tasks_from_legacy_non_log_stages_with_null_flag(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    log_stage = create_stage(main, db, board["id"], "All Work")
    create_task(main, db, backlog["id"], "Existing task")

    db.query(models.Stage).filter(models.Stage.id == backlog["id"]).update({"is_log": None})
    db.commit()

    main.update_stage_config(log_stage["id"], main.StageConfigUpdate(is_log=True, filter_id=None), db)

    stages = main.get_stages(board["id"], db)
    rendered_log = next(stage for stage in stages if stage["id"] == log_stage["id"])
    assert [task["title"] for task in rendered_log["tasks"]] == ["Existing task"]


def test_log_stage_rejects_creates_and_moves(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    log_stage = create_stage(main, db, board["id"], "Log")
    main.update_stage_config(log_stage["id"], main.StageConfigUpdate(is_log=True, filter_id=None), db)
    task = create_task(main, db, backlog["id"], "Regular task")

    with pytest.raises(HTTPException):
        create_task(main, db, log_stage["id"], "Should fail")

    with pytest.raises(HTTPException):
        main.move_task(task["id"], main.TaskMove(stage_id=log_stage["id"], position=0), db)


def test_non_empty_stage_cannot_be_converted_to_log(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    create_task(main, db, backlog["id"], "Existing task")

    with pytest.raises(HTTPException):
        main.update_stage_config(backlog["id"], main.StageConfigUpdate(is_log=True, filter_id=None), db)


def test_log_stage_can_filter_by_selected_type_custom_field(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    log_stage = create_stage(main, db, board["id"], "Priority Log")
    bug_type = create_task_type(main, db, board["id"], name="Bug")
    feature_type = create_task_type(main, db, board["id"], name="Feature", color="#22c55e")
    priority_field = add_custom_field(main, db, bug_type["id"], "Priority", field_type="dropdown", options=["Low", "High"])

    matching_bug = create_task(main, db, backlog["id"], "Fix prod issue", task_type_id=bug_type["id"])
    create_task(main, db, backlog["id"], "Small cleanup", task_type_id=bug_type["id"])
    create_task(main, db, backlog["id"], "New dashboard", task_type_id=feature_type["id"])

    main.update_task(
        matching_bug["id"],
        main.TaskUpdate(custom_fields={str(priority_field["id"]): "High"}),
        db,
    )

    saved_filter = create_saved_filter(
        main,
        db,
        board["id"],
        name="High Priority Bugs",
        definition={
            "op": "and",
            "selected_task_type_id": bug_type["id"],
            "rules": [
                {"field": f"custom:{priority_field['id']}", "operator": "eq", "value": "High"},
            ],
        },
    )
    main.update_stage_config(log_stage["id"], main.StageConfigUpdate(is_log=True, filter_id=saved_filter["id"]), db)

    stages = main.get_stages(board["id"], db)
    rendered_log = next(stage for stage in stages if stage["id"] == log_stage["id"])
    assert [task["title"] for task in rendered_log["tasks"]] == ["Fix prod issue"]


def test_log_stage_can_combine_rules_with_or(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    log_stage = create_stage(main, db, board["id"], "Follow Up")

    release = create_task(main, db, backlog["id"], "Ship release")
    docs = create_task(main, db, backlog["id"], "Write docs")
    create_task(main, db, backlog["id"], "Plan roadmap")
    main.update_task(docs["id"], main.TaskUpdate(description="Needs release notes"), db)

    saved_filter = create_saved_filter(
        main,
        db,
        board["id"],
        name="Release Follow Up",
        definition={
            "op": "or",
            "selected_task_type_id": None,
            "rules": [
                {"field": "title", "operator": "contains", "value": "release"},
                {"field": "description", "operator": "contains", "value": "release"},
            ],
        },
    )
    main.update_stage_config(log_stage["id"], main.StageConfigUpdate(is_log=True, filter_id=saved_filter["id"]), db)

    stages = main.get_stages(board["id"], db)
    rendered_log = next(stage for stage in stages if stage["id"] == log_stage["id"])
    assert [task["id"] for task in rendered_log["tasks"]] == [docs["id"], release["id"]]


def test_log_stage_can_filter_overdue_tasks_relative_to_today(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    log_stage = create_stage(main, db, board["id"], "Overdue")

    overdue_task = create_task(
        main,
        db,
        backlog["id"],
        "Missed target",
        due_date=(main.date.today() - timedelta(days=1)).isoformat(),
    )
    create_task(
        main,
        db,
        backlog["id"],
        "Due later",
        due_date=(main.date.today() + timedelta(days=2)).isoformat(),
    )
    create_task(main, db, backlog["id"], "No due date")

    saved_filter = create_saved_filter(
        main,
        db,
        board["id"],
        name="Overdue Tasks",
        definition={
            "op": "and",
            "selected_task_type_id": None,
            "rules": [
                {"field": "due_date", "operator": "lt", "value": "today"},
            ],
        },
    )
    main.update_stage_config(log_stage["id"], main.StageConfigUpdate(is_log=True, filter_id=saved_filter["id"]), db)

    stages = main.get_stages(board["id"], db)
    rendered_log = next(stage for stage in stages if stage["id"] == log_stage["id"])
    assert [task["id"] for task in rendered_log["tasks"]] == [overdue_task["id"]]


def test_log_stage_can_filter_by_objective_type_rule(app_env):
    main = app_env["main"]
    db = app_env["db"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    log_stage = create_stage(main, db, board["id"], "Bugs Only")
    bug_type = create_task_type(main, db, board["id"], name="Bug")
    feature_type = create_task_type(main, db, board["id"], name="Feature", color="#22c55e")

    bug_task = create_task(main, db, backlog["id"], "Fix login", task_type_id=bug_type["id"])
    create_task(main, db, backlog["id"], "Ship dashboard", task_type_id=feature_type["id"])
    create_task(main, db, backlog["id"], "Untyped task")

    saved_filter = create_saved_filter(
        main,
        db,
        board["id"],
        name="Bug Tasks",
        definition={
            "op": "and",
            "selected_task_type_id": None,
            "rules": [
                {"field": "task_type_id", "operator": "eq", "value": str(bug_type["id"])},
            ],
        },
    )
    main.update_stage_config(log_stage["id"], main.StageConfigUpdate(is_log=True, filter_id=saved_filter["id"]), db)

    stages = main.get_stages(board["id"], db)
    rendered_log = next(stage for stage in stages if stage["id"] == log_stage["id"])
    assert [task["id"] for task in rendered_log["tasks"]] == [bug_task["id"]]


def test_log_stage_can_filter_assigned_to_me(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    log_stage = create_stage(main, db, board["id"], "My Work")

    current_user = models.User(
        email="me@example.com",
        password_hash="x",
        display_name="Me",
        is_active=True,
    )
    teammate = models.User(
        email="teammate@example.com",
        password_hash="x",
        display_name="Teammate",
        is_active=True,
    )
    db.add_all([current_user, teammate])
    db.commit()

    board_row = db.query(models.Board).filter(models.Board.id == board["id"]).first()
    main.ensure_board_membership(board_row, current_user, "editor", db)
    main.ensure_board_membership(board_row, teammate, "viewer", db)
    db.commit()

    my_task = create_task(main, db, backlog["id"], "Mine")
    their_task = create_task(main, db, backlog["id"], "Theirs")
    unassigned_task = create_task(main, db, backlog["id"], "Unassigned")

    main.update_task(my_task["id"], main.TaskUpdate(assignee_user_id=current_user.id), db)
    main.update_task(their_task["id"], main.TaskUpdate(assignee_user_id=teammate.id), db)

    session_token, _ = main.create_user_session(current_user, db)
    saved_filter = main.create_saved_filter(
        main.SavedFilterCreate(
            name="Assigned to Me",
            board_id=board["id"],
            definition={
                "op": "and",
                "selected_task_type_id": None,
                "rules": [
                    {"field": "assignee_user_id", "operator": "eq", "value": "__me__"},
                ],
            },
        ),
        db,
        main.Request(request_with_cookie(path="/api/filters", cookie=f"{main.SESSION_COOKIE}={session_token}")),
    )
    main.update_stage_config(log_stage["id"], main.StageConfigUpdate(is_log=True, filter_id=saved_filter["id"]), db)

    request = main.Request(request_with_cookie(path=f"/api/stages?board_id={board['id']}", cookie=f"{main.SESSION_COOKIE}={session_token}"))

    stages = main.get_stages(board["id"], db, request)
    rendered_log = next(stage for stage in stages if stage["id"] == log_stage["id"])
    assert [task["id"] for task in rendered_log["tasks"]] == [my_task["id"]]
    assert all(task["id"] != their_task["id"] for task in rendered_log["tasks"])
    assert all(task["id"] != unassigned_task["id"] for task in rendered_log["tasks"])


def test_log_stage_can_filter_assigned_to_specific_user(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]
    board = create_board(main, db)
    backlog = create_stage(main, db, board["id"], "Backlog")
    log_stage = create_stage(main, db, board["id"], "Teammate Work")

    owner = models.User(
        email="owner@example.com",
        password_hash="x",
        display_name="Owner",
        role="admin",
        is_active=True,
    )
    teammate = models.User(
        email="specific@example.com",
        password_hash="x",
        display_name="Specific User",
        is_active=True,
    )
    db.add_all([owner, teammate])
    db.commit()

    board_row = db.query(models.Board).filter(models.Board.id == board["id"]).first()
    main.ensure_board_membership(board_row, teammate, "viewer", db)
    db.commit()

    mine = create_task(main, db, backlog["id"], "Mine")
    theirs = create_task(main, db, backlog["id"], "Theirs")
    main.update_task(theirs["id"], main.TaskUpdate(assignee_user_id=teammate.id), db)

    owner_token, _ = main.create_user_session(owner, db)
    saved_filter = main.create_saved_filter(
        main.SavedFilterCreate(
            name="Specific Assignee",
            board_id=board["id"],
            definition={
                "op": "and",
                "selected_task_type_id": None,
                "rules": [
                    {"field": "assignee_user_id", "operator": "eq", "value": str(teammate.id)},
                ],
            },
        ),
        db,
        main.Request(request_with_cookie(path="/api/filters", cookie=f"{main.SESSION_COOKIE}={owner_token}")),
    )
    main.update_stage_config(log_stage["id"], main.StageConfigUpdate(is_log=True, filter_id=saved_filter["id"]), db)

    request = main.Request(request_with_cookie(path=f"/api/stages?board_id={board['id']}", cookie=f"{main.SESSION_COOKIE}={owner_token}"))
    stages = main.get_stages(board["id"], db, request)
    rendered_log = next(stage for stage in stages if stage["id"] == log_stage["id"])
    assert [task["id"] for task in rendered_log["tasks"]] == [theirs["id"]]
    assert all(task["id"] != mine["id"] for task in rendered_log["tasks"])
