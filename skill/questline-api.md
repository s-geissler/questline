---
name: questline-api
description: Use the Questline HTTP API to read and write Hubs, Stages, Objectives, Tasks, Checklists, and Recurrence rules. Load this skill whenever the user asks you to interact with a Questline instance from an external tool, CLI, or AI agent.
---

# Questline API

Questline is a self-hosted, single-instance project management app. The HTTP API is the same one the web UI uses, and it accepts bearer tokens in addition to session cookies. This skill teaches an external tool (CLI, script, AI agent) how to drive the API.

## For the human reader — how to mint a token

You only need to do this once. Open a browser, log into your Questline instance, and call the self-service token endpoint from the dev tools console while signed in:

```js
const r = await fetch("/api/tokens", {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-CSRF-Token": document.cookie.match(/questline_csrf=([^;]+)/)[1] },
  body: JSON.stringify({ name: "agent-cli" }),
});
const { raw_token, id } = await r.json();
console.log(raw_token);
```

The `raw_token` is shown exactly once. Store it somewhere safe (e.g. an env var or secret manager). To revoke later: `DELETE /api/tokens/{id}`.

For a non-human identity (a bot account), have an admin create one and mint a token for it via the admin endpoints documented in the project repo (`POST /api/admin/agents`, `POST /api/admin/agents/{id}/tokens`).

## Authentication

Set two environment variables:

- `QUESTLINE_BASE_URL` — e.g. `https://questline.example.com` (no trailing slash)
- `QUESTLINE_API_TOKEN` — the raw token from the mint call above

Every request sends:

```
Authorization: Bearer ${QUESTLINE_API_TOKEN}
Content-Type: application/json
```

That is the entire auth contract. There is no CSRF cookie, no `X-Requested-With` header, no session. Bearer-authenticated requests bypass CSRF checks.

If a request returns `401`, the token is revoked, the underlying user is deactivated, or the token never existed. Re-mint and try again.

## Terminology — use these words

The user-facing terms differ from the API/code names. Always use the **user-facing term** in messages back to the human; reference the API path when describing concrete calls.

| User-facing term | API path | What it is |
|---|---|---|
| Hub | `/api/boards` | A project workspace. The top-level container. |
| Stage | `/api/stages` | A column within a Hub. Holds Objectives, or a Log Stage (read-only, computed from a Saved Filter). The DB table is `lists`. |
| Objective | `/api/tasks` | A card in a Stage. The unit of work. The DB model is `Task`. |
| Quest | `/api/tasks` (with `task_type.is_epic = true`) | An Objective whose Task Type is an epic. Adding a checklist item to a Quest auto-spawns a child Objective. |
| Task Type | `/api/task-types` | A shape definition for Objectives. Owns Custom Field definitions. |
| Custom Field | `/api/task-types/{id}/fields` | A typed field attached to a Task Type. |
| Saved Filter | `/api/filters` | A reusable filter definition; drives Log Stages. |
| Automation | `/api/automations` | A trigger→action rule on a Hub. |

If a user says "task" or "card", they mean **Objective**. If they say "column" or "list", they mean **Stage**. If they say "board" or "project", they mean **Hub**.

## The "find the ID" pattern

Questline has no human-friendly IDs in the URL. When the user says "create a task in stage X", you must translate "X" into a numeric `stage_id`. The pattern is always:

1. List the parent collection: `GET /api/boards` → find the Hub.
2. List the children: `GET /api/stages?board_id=N` → find the Stage by name.
3. Optionally: `GET /api/task-types?board_id=N` to find a Task Type.
4. Act: `POST /api/tasks` with `{ title, stage_id, ... }`.

Always read before you write. Never guess an ID.

## Full setup workflow (Hub → Stages → Task Types → Objectives)

This is the typical bootstrap pattern: create a Hub, populate it with Stages, define Task Types with Custom Fields, then create Objectives and optionally a Quest.

```bash
# ── 1. Create a Hub ──────────────────────────────────────────────
HUB=$(curl -sS -X POST "$QUESTLINE_BASE_URL/api/boards" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d '{"name": "My Project", "color": "#3498db"}')
HUB_ID=$(echo "$HUB" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# ── 2. Create Stages ─────────────────────────────────────────────
# Position controls left-to-right order. Row 0 is the top row.
STAGE1=$(curl -sS -X POST "$QUESTLINE_BASE_URL/api/stages" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d "{\"name\": \"Backlog\", \"board_id\": $HUB_ID, \"position\": 0}")
S1_ID=$(echo "$STAGE1" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

STAGE2=$(curl -sS -X POST "$QUESTLINE_BASE_URL/api/stages" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d "{\"name\": \"In Progress\", \"board_id\": $HUB_ID, \"position\": 1}")
S2_ID=$(echo "$STAGE2" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

STAGE3=$(curl -sS -X POST "$QUESTLINE_BASE_URL/api/stages" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d "{\"name\": \"Done\", \"board_id\": $HUB_ID, \"position\": 2}")

# ── 3. Create Task Types ──────────────────────────────────────────
# A regular Task Type (is_epic: false)
TT=$(curl -sS -X POST "$QUESTLINE_BASE_URL/api/task-types" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d "{\"name\": \"Task\", \"board_id\": $HUB_ID, \"color\": \"#2ecc71\", \"is_epic\": false}")
TT_ID=$(echo "$TT" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# A Quest / epic Task Type (is_epic: true — checklist items auto-spawn child Objectives)
QT=$(curl -sS -X POST "$QUESTLINE_BASE_URL/api/task-types" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d "{\"name\": \"Quest\", \"board_id\": $HUB_ID, \"color\": \"#9b59b6\", \"is_epic\": true}")
QT_ID=$(echo "$QT" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# ── 4. Add Custom Fields to a Task Type ───────────────────────────
# Dropdown field
curl -sS -X POST "$QUESTLINE_BASE_URL/api/task-types/$TT_ID/fields" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d '{"name": "Priority", "field_type": "dropdown", "show_on_card": true, "options": ["Low", "Medium", "High", "Critical"]}'

# Number field
curl -sS -X POST "$QUESTLINE_BASE_URL/api/task-types/$TT_ID/fields" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d '{"name": "Story Points", "field_type": "number", "show_on_card": true}'

# Text field (with color accent)
curl -sS -X POST "$QUESTLINE_BASE_URL/api/task-types/$TT_ID/fields" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d '{"name": "Notes", "field_type": "text", "show_on_card": false, "color": "#1abc9c"}'

# ── 5. Create Objectives (with Task Type) ─────────────────────────
curl -sS -X POST "$QUESTLINE_BASE_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d "{\"title\": \"Investigate network topology\", \"stage_id\": $S1_ID, \"task_type_id\": $TT_ID}"

# ── 6. Set Custom Field Values on an Objective ────────────────────
# Use PUT with a custom_fields dict. Keys are the field definition IDs (strings).
# First, find the field IDs from the task type:
curl -sS -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  "$QUESTLINE_BASE_URL/api/task-types/$TT_ID"
# → custom_fields[].id = field_def_id

curl -sS -X PUT "$QUESTLINE_BASE_URL/api/tasks/1" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d '{"custom_fields": {"1": "High", "2": "5", "3": "Needs review"}}'

# ── 7. Create a Quest (epic Objective) ────────────────────────────
QUEST=$(curl -sS -X POST "$QUESTLINE_BASE_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d "{\"title\": \"LRZ-JMU Measurement Study\", \"stage_id\": $S1_ID, \"task_type_id\": $QT_ID}")
QUEST_ID=$(echo "$QUEST" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Add a checklist item — on a Quest this auto-spawns a child Objective
curl -sS -X POST "$QUESTLINE_BASE_URL/api/tasks/$QUEST_ID/checklist" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d '{"title": "Deploy monitoring agents"}'
# Response includes spawned_task_id for the auto-created child Objective

# ── 8. Mark an Objective as done ──────────────────────────────────
curl -sS -X PUT "$QUESTLINE_BASE_URL/api/tasks/1" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d '{"done": true}'
```

## Hub management

| Action | Method | Path | Notes |
|--------|--------|------|-------|
| List all accessible Hubs | `GET` | `/api/boards` | Returns array with `id`, `name`, `color`, `role` |
| Create a Hub | `POST` | `/api/boards` | Body: `{ name: str, color?: str }`. Requires `editor` role on the board (creator becomes owner). |
| Update a Hub | `PUT` | `/api/boards/{id}` | Requires `owner` role. |
| Delete a Hub | `DELETE` | `/api/boards/{id}` | Requires `owner` role. |

## Stage management

| Action | Method | Path | Notes |
|--------|--------|------|-------|
| List Stages in a Hub | `GET` | `/api/stages?board_id=N` | Each stage includes `name`, `row`, `position`, `is_log` |
| Create a Stage | `POST` | `/api/stages` | Body: `{ name: str, board_id: int, row?: int (0=top), position?: int }`. If `position` is omitted, appends to end of row. Requires `editor`. |
| Update a Stage | `PUT` | `/api/stages/{id}` | — |
| Delete a Stage | `DELETE` | `/api/stages/{id}` | — |

A **Log Stage** (`is_log: true`) is read-only. Created by assigning a `filter_id` at update time — you cannot POST a Log Stage directly.

## Task Type and Custom Field management

| Action | Method | Path | Notes |
|--------|--------|------|-------|
| List Task Types in a Hub | `GET` | `/api/task-types?board_id=N` | Returns array with `custom_fields` nested. |
| Create a Task Type | `POST` | `/api/task-types` | Body: `{ name: str, board_id: int, is_epic?: bool, color?: str, show_description_on_card?: bool, show_checklist_on_card?: bool }`. Requires `editor`. |
| Update a Task Type | `PUT` | `/api/task-types/{id}` | — |
| Delete a Task Type | `DELETE` | `/api/task-types/{id}` | — |
| Add a Custom Field | `POST` | `/api/task-types/{id}/fields` | Body: `{ name: str, field_type?: "text"\|"number"\|"date"\|"dropdown", show_on_card?: bool, options?: str[]\|dict[], color?: str }`. Requires `editor`. |
| Delete a Custom Field | `DELETE` | `/api/task-types/{type_id}/fields/{field_id}` | — |

**`options` detail:** For `dropdown` fields, each option can be a plain string (`"High"`) or a dict `{ "label": "High", "color": "#e74c3c" }`. Max 100 options.

### Custom field type reference

| field_type | value stored | options field |
|-----------|-------------|---------------|
| `text` | Free string | Ignored |
| `number` | Stringified number (e.g. `"5"`) | Ignored |
| `date` | String date (e.g. `"2026-08-01"`) | Ignored |
| `dropdown` | Selected option label string | Array of option labels or `{label, color}` dicts |

## Objective (Task) management

| Action | Method | Path | Notes |
|--------|--------|------|-------|
| List Objectives in a Stage | `GET` | `/api/tasks?stage_id=N` | Returns array of task objects. |
| Create an Objective | `POST` | `/api/tasks` | Body: `{ title: str, stage_id: int, task_type_id?: int, due_date?: str }`. Requires `editor` on the board. Cannot target a Log Stage. |
| Update an Objective | `PUT` | `/api/tasks/{id}` | Body: partial update with any of `title`, `description`, `due_date`, `task_type_id`, `assignee_user_id`, `color`, `done`, `custom_fields`. Setting `done: true` fires `task_done` automations. |
| Move an Objective | `PUT` | `/api/tasks/{id}/move` | Body: `{ stage_id: int, position?: int }`. Target cannot be a Log Stage. |
| Delete an Objective | `DELETE` | `/api/tasks/{id}` | — |

### Setting custom field values

Use `PUT /api/tasks/{id}` with a `custom_fields` dict mapping field-definition-ID (as string) to value:

```json
{
  "custom_fields": {
    "1": "High",
    "2": "5",
    "3": "Needs review"
  }
}
```

- Keys are `str(field_def_id)` — find these from `GET /api/task-types/{id}` via the `custom_fields[].id` field.
- Values are always stored as strings, even for `number` or `date` types.
- The handler upserts: sets the value if the task already has a value for that field, otherwise inserts a new row.
- The task must have a `task_type_id` that owns the referenced field definitions.

## Quest (epic) management

A Quest is an Objective whose Task Type has `is_epic: true`. It behaves identically to a regular Objective except:

- **Adding a checklist item** (`POST /api/tasks/{id}/checklist`) auto-creates a child Objective. The response includes `spawned_task_id`.
- The child lands in the **spawn stage** configured on the Task Type (`spawn_stage_id`, initially `null`). If no spawn stage is set, the child lands in the same stage as the Quest.
- To configure the spawn stage, update the Task Type: `PUT /api/task-types/{id}` with `{ "spawn_stage_id": N }`.

### Create a Quest

```bash
curl -sS -X POST "$QUESTLINE_BASE_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d "{\"title\": \"My Quest\", \"stage_id\": \$STAGE_ID, \"task_type_id\": \$QUEST_TYPE_ID}"
```

### Add a checklist item (spawns child Objective)

```bash
curl -sS -X POST "$QUESTLINE_BASE_URL/api/tasks/$TASK_ID/checklist" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUESTLINE_API_TOKEN" \
  -d '{"title": "Sub-task description"}'
# Response: { "id": ..., "title": "...", "done": false, "spawned_task_id": 42 }
```

The spawned child Objective can be fetched with `GET /api/tasks?stage_id=N` or directly at `GET /api/tasks/{spawned_task_id}`.

## Recurrence

Set up a recurring Objective with `PUT /api/tasks/{id}/recurrence`:

```json
{
  "enabled": true,
  "mode": "create_new",
  "frequency": "weekly",
  "interval": 1,
  "next_run_on": "2026-08-01",
  "spawn_stage_id": 5
}
```

`mode` is `create_new` (clone the task on each cycle) or `reuse_existing` (reset the same task back to `spawn_stage_id`). `frequency` is `daily`, `weekly`, or `monthly`.

## Error handling

| Status | Meaning |
|---|---|
| `200`/`201` | Success — read the JSON body. |
| `400` | Your request was malformed. Read `detail`. |
| `401` | Token is missing, revoked, or the owning user is inactive. Re-mint. |
| `403` | Either CSRF validation failed (you sent a session-cookie request without the CSRF token) or you don't have board access for this action. With a bearer token, you should never see 403 for CSRF. |
| `404` | The ID you used doesn't exist. Re-list and try again. |
| `429` | You hit a rate limit (login attempts, registrations). Back off. |

A Log Stage cannot receive new Objectives or be the target of a move — `POST /api/tasks` and `PUT /api/tasks/{id}/move` will return `400 "Cannot add tasks to a log stage"`. List stages and pick a non-Log one.

## Reference

- Full API reference: `<project-root>/docs/api.md`
- Domain glossary: `<project-root>/CONTEXT.md`
- Auth details: `<project-root>/docs/auth.md`
- Why the `agent` role exists: `<project-root>/docs/adr/0001-agent-role-as-tag.md`

For an LLM agent working in a checkout, the references are the project files. For an external tool, the docs are also served at `${QUESTLINE_BASE_URL}/docs` (FastAPI Swagger UI) when the server is running.
