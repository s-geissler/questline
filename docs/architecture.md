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

A **Hub** is the top-level workspace that multiple users can be members of with different roles. Each Hub has its own **Stages**, **Task Types**, **Saved Filters**, and **Automations** — all scoped to that hub and not shared across hubs.

A **Stage** is either a normal stage (holds ordered tasks) or a **Log Stage** (read-only virtual view driven by a Saved Filter).

A **Quest** is an Objective whose Task Type has `is_epic = true`. Adding a checklist item to a Quest automatically creates a linked child Objective in the hub.

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
  id, email, display_name, password_hash, role (user|admin), is_active,
  password_reset_requested, created_at

user_sessions
  id, user_id → users, token_hash, csrf_token_hash, created_at, expires_at

boards
  id, name, color, position, view_toggle_position, owner_user_id → users

board_memberships
  id, board_id → boards, user_id → users, role (viewer|editor|owner), created_at
  UNIQUE (board_id, user_id)

lists  [= Stages]
  id, name, board_id → boards, position, is_log, filter_id → saved_filters

saved_filters
  id, name, board_id → boards, definition (JSON)
  definition.sort_rules optionally stores ordered field/direction pairs for logs.
  An absent or empty list retains newest-first ordering; no schema migration.

task_types
  id, name, board_id → boards, color, is_epic, spawn_list_id → lists,
  show_description_on_card, show_checklist_on_card, hide_name_on_card

custom_field_defs
  id, task_type_id → task_types, name, field_type, options (JSON), color, show_on_card

tasks
  id, title, description, stage_id → lists, task_type_id → task_types,
  parent_task_id → tasks, assignee_user_id → users,
  position, color, due_date, due_time, due_timezone, done, show_description_on_card, show_checklist_on_card,
  created_at

task_assignees
  task_id → tasks, user_id → users (composite primary key)
  Existing tasks.assignee_user_id values are copied here at startup. The legacy
  column remains synchronized to the first assignee for compatibility.

task_recurrences
  id, task_id → tasks (UNIQUE), enabled, mode, frequency, interval,
  next_run_on, spawn_stage_id → lists, created_at

task_history_events
  id, task_id → tasks, event_type, actor_user_id → users (SET NULL),
  actor_name (snapshot, or Automation), subject (checklist item title), created_at (UTC)
  INDEX (task_id, id); removed with the task

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

Operational note:
- Existing databases receive nullable `tasks.due_time` and `tasks.due_timezone`
  columns through the idempotent startup migrations. Existing date strings and
  calendar identities are preserved; a null time retains date-only behavior.
- `boards.owner_user_id` may be `NULL`, which represents an orphaned hub.
- The admin UI exposes orphan discovery, manual deletion, bulk orphan cleanup, and explicit ownership assignment.

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

For request-derived client IPs, Questline trusts `X-Forwarded-For` only when the immediate peer address is inside `QUESTLINE_TRUSTED_PROXIES`; otherwise it uses the socket peer IP directly.

## Performance Indexes

All hot paths have covering indexes: board membership lookups, task stage+position ordering, notification user+read+created ordering, checklist item task lookups. Slow queries (>200 ms by default) are logged at WARNING level via the `questline.db` logger.
