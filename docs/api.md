# API Reference

All API endpoints are prefixed with `/api`. Authentication is via session cookie (see [auth.md](auth.md)). Responses are JSON. Errors follow FastAPI's default `{"detail": "..."}` format.

The interactive Swagger UI is available at `/docs` when the server is running.

---

## Auth

### `POST /api/auth/register`

Register a new account. The first account becomes admin.

**Body**
```json
{ "email": "user@example.com", "password": "...", "display_name": "Alice" }
```

**Returns** user object. `403` if registration is disabled.

---

### `POST /api/auth/login`

**Body**
```json
{ "email": "user@example.com", "password": "..." }
```

Sets the `questline_session` cookie on success. **Returns** user object.

---

### `POST /api/auth/logout`

Clears the session cookie and invalidates the server-side session.

---

### `GET /api/auth/me`

Returns the currently authenticated user object. `401` if not logged in.

**User object fields**
```json
{
  "id": 1,
  "email": "user@example.com",
  "display_name": "Alice",
  "role": "user",
  "is_active": true
}
```

---

### `PUT /api/auth/profile`

Update the current user's display name and/or password.

**Body**
```json
{ "display_name": "Alice", "password": "newpassword123" }
```

`password` is optional. If provided, must be at least 8 characters. Changing the password invalidates all existing sessions and issues a new session cookie automatically.

---

## Notifications

### `GET /api/notifications`

Returns up to 20 most recent notifications for the current user.

```json
{
  "items": [ { "id": 1, "type": "task_due_today", "title": "...", "body": "...", "link_url": "...", "read_at": null, "created_at": "..." } ],
  "unread_count": 3
}
```

---

### `POST /api/notifications/{id}/read`

Mark a notification as read.

---

### `POST /api/notifications/read-all`

Mark all notifications for the current user as read.

---

## Boards

### `GET /api/boards`

Returns all boards accessible to the current user (all boards for admins, memberships only for regular users).

```json
[{ "id": 1, "name": "My Board", "color": "#3498db", "position": 0, "role": "owner", "is_shared": false }]
```

---

### `POST /api/boards`

Create a board. Creator is automatically added as owner.

**Body**
```json
{ "name": "Sprint Board", "color": "#e74c3c" }
```

---

### `PUT /api/boards/{board_id}`

Update board name and/or color. Requires `owner` role.

**Body** (all fields optional)
```json
{ "name": "New Name", "color": "#2ecc71" }
```

---

### `DELETE /api/boards/{board_id}`

Delete a board and all its contents. Requires `owner` role.

---

## Board Members

### `GET /api/boards/{board_id}/members`

Returns current user's role and the full member list.

```json
{
  "current_role": "owner",
  "members": [{ "user_id": 5, "email": "...", "display_name": "...", "role": "editor", "account_role": "user", "is_active": true }]
}
```

---

### `POST /api/boards/{board_id}/members`

Add a member by email. Requires `owner` role.

**Body**
```json
{ "email": "user@example.com", "role": "editor" }
```

Valid roles: `viewer`, `editor`, `owner`.

---

### `PUT /api/boards/{board_id}/members/{user_id}`

Update a member's role. Requires `owner` role. Cannot demote the last owner.

**Body**
```json
{ "role": "viewer" }
```

---

### `DELETE /api/boards/{board_id}/members/{user_id}`

Remove a member. Requires `owner` role. Cannot remove the last owner.

---

## Stages

### `GET /api/stages?board_id={id}`

Returns all stages for a board, ordered by position. Requires `viewer`.

**Stage object**
```json
{
  "id": 1,
  "name": "To Do",
  "position": 0,
  "is_log": false,
  "filter_id": null,
  "tasks": [ /* task objects */ ]
}
```

---

### `POST /api/stages`

Create a stage. Requires `editor`.

**Body**
```json
{ "name": "In Progress", "board_id": 1 }
```

---

### `PUT /api/stages/{stage_id}`

Update a stage name. Requires `editor`.

**Body**
```json
{ "name": "Done" }
```

---

### `PUT /api/stages/{stage_id}/config`

Update a stage's log-mode settings. Requires `editor`.

**Body** (all optional)
```json
{ "is_log": true, "filter_id": 3 }
```

`is_log` cannot be set to `true` if the stage already contains tasks. `filter_id` is only meaningful when `is_log` is `true`; set to `null` to clear.

---

### `POST /api/stages/{stage_id}/clear-completed`

Delete all completed tasks in a stage (including their descendants). Requires `editor`.

**Returns**
```json
{ "ok": true, "deleted": 5 }
```

---

### `DELETE /api/stages/{stage_id}`

Delete a stage and all its tasks. Requires `editor`.

---

### `PUT /api/stages/reorder`

Reorder stages within a board. Requires `editor`.

**Body**
```json
{ "ids": [2, 1, 3] }
```

---

## Tasks

### `GET /api/tasks/{task_id}`

Returns a single task. Requires `viewer` on the task's board.

**Task object**
```json
{
  "id": 1,
  "title": "Implement login",
  "description": "...",
  "stage_id": 2,
  "task_type_id": 1,
  "task_type": { "id": 1, "name": "Feature", "color": "#3498db", "is_epic": false },
  "position": 0,
  "done": false,
  "color": null,
  "due_date": "2024-06-01",
  "parent_task": null,
  "assignee": null,
  "assignee_user_id": null,
  "show_description_on_card": null,
  "effective_show_description_on_card": false,
  "show_checklist_on_card": null,
  "effective_show_checklist_on_card": false,
  "custom_field_values": { "3": "high" },
  "checklist": [],
  "board_id": 1,
  "board_name": "My Board",
  "stage_name": "To Do",
  "recurrence": null
}
```

---

### `POST /api/tasks`

Create a task. Requires `editor`.

**Body**
```json
{
  "title": "My task",
  "stage_id": 2,
  "task_type_id": 1,
  "due_date": "2024-06-01"
}
```

Fires `task_created` automations after creation.

---

### `PUT /api/tasks/{task_id}`

Update a task. Requires `editor`. All fields are optional.

**Body**
```json
{
  "title": "Updated title",
  "description": "...",
  "task_type_id": 2,
  "done": true,
  "due_date": "2024-07-01",
  "assignee_user_id": 5,
  "color": "#e74c3c",
  "show_description_on_card": true,
  "show_checklist_on_card": false,
  "custom_fields": { "3": "medium" }
}
```

Setting `done: true` fires `task_done` automations.

---

### `PUT /api/tasks/reorder`

Reorder tasks within a stage (drag-and-drop). Requires `editor`. Cannot target a Log Stage.

**Body**
```json
{ "stage_id": 2, "ids": [5, 3, 1, 4] }
```

---

### `PUT /api/tasks/{task_id}/move`

Move a task to a different stage. Requires `editor`. Cannot target a Log Stage.

**Body**
```json
{ "stage_id": 3, "position": 0 }
```

Fires `task_moved_to_stage` automations if the stage changed.

---

### `DELETE /api/tasks/{task_id}`

Delete a task. Requires `editor`.

Deleting a task also deletes its recurrence rule, if present.

---

## Task Recurrence

### `PUT /api/tasks/{task_id}/recurrence`

Create or update a recurrence rule for a task. Requires `editor`.

**Body**
```json
{
  "enabled": true,
  "mode": "create_new",
  "frequency": "weekly",
  "interval": 1,
  "next_run_on": "2026-04-10",
  "spawn_stage_id": 2
}
```

Valid `frequency` values: `daily`, `weekly`, `monthly`.
Valid `mode` values: `create_new`, `reuse_existing`.

`spawn_stage_id` must belong to the same board and cannot be a Log Stage.

**Returns**
```json
{
  "enabled": true,
  "mode": "create_new",
  "frequency": "weekly",
  "interval": 1,
  "next_run_on": "2026-04-10",
  "spawn_stage_id": 2
}
```

Recurrence is attached to the source task.

- `create_new` creates a new task in `spawn_stage_id`
- `reuse_existing` resets and moves the same task back to `spawn_stage_id`

In both cases, `spawn_stage_id` is the source of truth for where the next cycle starts, so completion automations moving the task elsewhere do not affect recurrence placement.

---

### `DELETE /api/tasks/{task_id}/recurrence`

Delete a task's recurrence rule. Requires `editor`.

---

## Checklist Items

### `POST /api/tasks/{task_id}/checklist`

Add a checklist item. Requires `editor`.

**Body**
```json
{ "title": "Write tests" }
```

If the parent task's type has `is_epic = true`, a child objective is automatically spawned in the configured spawn stage (or the current stage if none is set). The spawned task's ID is returned as `spawned_task_id`.

---

### `PUT /api/tasks/{task_id}/checklist/{item_id}`

Update a checklist item. Requires `editor`.

**Body**
```json
{ "title": "Updated title", "done": true }
```

Checking `done: true` also marks the linked spawned task as done and fires `task_done`. When all items become done, `checklist_completed` is fired on the parent task.

---

### `DELETE /api/tasks/{task_id}/checklist/{item_id}`

Delete a checklist item. Requires `editor`.

---

## Task Types

### `GET /api/task-types?board_id={id}`

Returns all task types for a board. Requires `viewer`.

```json
[{
  "id": 1,
  "name": "Feature",
  "color": "#3498db",
  "is_epic": false,
  "show_description_on_card": false,
  "show_checklist_on_card": false,
  "spawn_stage_id": null,
  "custom_fields": []
}]
```

---

### `POST /api/task-types`

Create a task type. Requires `editor`.

**Body**
```json
{
  "name": "Bug",
  "board_id": 1,
  "color": "#e74c3c",
  "is_epic": false,
  "show_description_on_card": false,
  "show_checklist_on_card": false
}
```

---

### `PUT /api/task-types/{type_id}`

Update a task type. Requires `editor`. All fields optional.

**Body**
```json
{
  "name": "Epic",
  "is_epic": true,
  "spawn_stage_id": 4,
  "color": "#9b59b6",
  "show_description_on_card": true,
  "show_checklist_on_card": true
}
```

`spawn_stage_id` cannot be a Log Stage.

If `spawn_stage_id` points at a stage in a different board, the caller must also have `editor` access to that board.

---

### `DELETE /api/task-types/{type_id}`

Delete a task type. Requires `editor`.

---

### `POST /api/task-types/{type_id}/fields`

Add a custom field definition. Requires `editor`.

**Body**
```json
{
  "name": "Priority",
  "field_type": "select",
  "show_on_card": true,
  "color": null,
  "options": [
    { "label": "High", "color": "#e74c3c" },
    { "label": "Low",  "color": null }
  ]
}
```

---

### `PUT /api/task-types/{type_id}/fields/{field_id}`

Update a custom field definition. Only `show_on_card`, `options`, and `color` are updated by the current implementation.

---

### `DELETE /api/task-types/{type_id}/fields/{field_id}`

Delete a custom field definition. Requires `editor`.

---

## Saved Filters

### `GET /api/filters?board_id={id}`

Returns all saved filters for a board. Requires `viewer`.

---

### `POST /api/filters`

Create a saved filter. Requires `editor`.

**Body**
```json
{
  "name": "Open Bugs",
  "board_id": 1,
  "definition": {
    "op": "and",
    "selected_task_type_id": 2,
    "source_board_ids": [1],
    "rules": [
      { "field": "done", "operator": "eq", "value": false }
    ]
  }
}
```

See [custom-fields.md](custom-fields.md) for available filter operators.

---

### `PUT /api/filters/{filter_id}`

Update a saved filter. Requires `editor`.

---

### `DELETE /api/filters/{filter_id}`

Delete a saved filter. Any Log Stages using it will have their `filter_id` cleared. Requires `editor`.

---

## Automations

### `GET /api/automations?board_id={id}`

Returns all automations for a board. Requires `viewer`.

---

### `POST /api/automations`

Create an automation. Requires `editor`. See [automations.md](automations.md) for trigger/action types.

**Body**
```json
{
  "name": "Auto-close on Done",
  "board_id": 1,
  "trigger_type": "task_moved_to_stage",
  "trigger_stage_id": 5,
  "action_type": "set_done",
  "action_stage_id": null,
  "action_task_type_id": null,
  "action_color": null,
  "action_days_offset": null
}
```

---

### `PUT /api/automations/{auto_id}`

Update an automation. Requires `editor`. All fields optional.

```json
{ "name": "Renamed rule", "enabled": false }
```

---

### `DELETE /api/automations/{auto_id}`

Delete an automation. Requires `editor`.

---

## Admin

All admin endpoints require the `admin` instance role.

### `GET /api/admin/users`

Returns all users with board membership counts.

---

### `PUT /api/admin/users/{user_id}`

Update a user's role or active status.

**Body**
```json
{ "role": "admin", "is_active": true }
```

Deactivating a user immediately invalidates all their sessions. The last admin cannot be demoted. A user cannot deactivate their own account.

---

### `GET /api/admin/settings`

Returns current instance settings.

```json
{
  "registration_enabled": true,
  "default_board_color": "#3d5a80",
  "new_accounts_active_by_default": true,
  "instance_theme_color": "#3d5a80",
  "recurrence_worker_interval_seconds": 60
}
```

---

### `PUT /api/admin/settings`

Update instance settings.

**Body**
```json
{
  "registration_enabled": false,
  "default_board_color": "#e74c3c",
  "new_accounts_active_by_default": false,
  "instance_theme_color": "#e74c3c",
  "recurrence_worker_interval_seconds": 45
}
```
