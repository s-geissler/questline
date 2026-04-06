# Architecture

## Concept Hierarchy

```
Instance
└── Hub (Board)
    ├── Stage (column) — regular or Log Stage
    │   └── Objective (Task)
    │       ├── Checklist Items
    │       │   └── spawned Objective (if Quest type)
    │       └── Custom Field Values
    │       └── Recurrence Rule
    ├── Task Types (define shape of Objectives)
    │   └── Custom Field Definitions
    ├── Saved Filters
    └── Automations
```

A **Hub** is a board that multiple users can be members of with different roles. Each Hub has its own **Stages**, **Task Types**, **Saved Filters**, and **Automations** — all scoped to that board and not shared across boards.

A **Stage** is either a normal stage (holds ordered tasks) or a **Log Stage** (read-only virtual view driven by a Saved Filter).

A **Quest** is an Objective whose Task Type has `is_epic = true`. Adding a checklist item to a Quest automatically creates a linked child Objective in the board.

## Module Overview

| File | Responsibility |
|---|---|
| `main.py` | FastAPI app, all route handlers, automation engine, notification creation |
| `models.py` | SQLAlchemy ORM models — the authoritative schema |
| `authz.py` | Session handling, password hashing, RBAC helpers |
| `filters_logic.py` | Saved filter parsing, task matching, Log Stage resolution |
| `database.py` | Engine setup, SQLite PRAGMA tuning, slow-query logging |

## Database Schema (ER Diagram)

```
users
  id, email, display_name, password_hash, role (user|admin), is_active, created_at

user_sessions
  id, user_id → users, token_hash, csrf_token_hash, created_at

boards
  id, name, color, position, owner_user_id → users

board_memberships
  id, board_id → boards, user_id → users, role (viewer|editor|owner), created_at
  UNIQUE (board_id, user_id)

lists  [= Stages]
  id, name, board_id → boards, position, is_log, filter_id → saved_filters

saved_filters
  id, name, board_id → boards, definition (JSON)

task_types
  id, name, board_id → boards, color, is_epic, spawn_list_id → lists,
  show_description_on_card, show_checklist_on_card

custom_field_defs
  id, task_type_id → task_types, name, field_type, options (JSON), color, show_on_card

tasks
  id, title, description, stage_id → lists, task_type_id → task_types,
  parent_task_id → tasks, assignee_user_id → users,
  position, color, due_date, done, show_description_on_card, show_checklist_on_card,
  created_at

task_recurrences
  id, task_id → tasks (UNIQUE), enabled, mode, frequency, interval,
  next_run_on, spawn_stage_id → lists, created_at

custom_field_values
  id, task_id → tasks, field_def_id → custom_field_defs, value

checklist_items
  id, task_id → tasks, title, done, spawned_task_id → tasks

automations
  id, board_id → boards, name, enabled,
  trigger_type, trigger_list_id → lists,
  action_type, action_list_id → lists, action_task_type_id → task_types,
  action_color, action_days_offset

notifications
  id, user_id → users, type, title, body,
  link_url, board_id, task_id, read_at, created_at, dedupe_key (UNIQUE)

instance_settings
  id, key, value
```

## Database Notes

- Default storage is SQLite with WAL mode enabled for concurrent reads.
- Foreign keys are enforced via `PRAGMA foreign_keys=ON`.
- Schema migrations run automatically at startup via `_run_column_migrations()` — `ALTER TABLE ... ADD COLUMN` for any missing columns.
- The `lists` table name is the physical name for Stages (legacy); the application layer uses "stage" terminology.
- Recurring objectives are processed by a background worker that polls due recurrence rows and creates new tasks from the source objective.

## Request Lifecycle

```
HTTP request
  → FastAPI route handler (main.py)
  → _authorize_board_request()   ← reads session cookie, checks board role
  → business logic / ORM queries
  → run_automations() if task state changed
  → create_notification() if relevant event
  → JSON response
```

## Performance Indexes

All hot paths have covering indexes: board membership lookups, task stage+position ordering, notification user+read+created ordering, checklist item task lookups. Slow queries (>200 ms by default) are logged at WARNING level via the `questline.db` logger.
