# Automations

Automations let you define rules that react automatically to events on objectives (tasks). Each automation belongs to a single Hub and can be enabled or disabled independently.

## Structure

An automation has two parts: a **trigger** and an **action**.

```
Trigger: "When [event] happens [on stage X]"
Action:  "Then [do something]"
```

## Triggers

| `trigger_type` | Description | `trigger_stage_id` used? |
|---|---|---|
| `task_created` | A new objective is created | Optional — limits to a specific stage |
| `task_moved_to_stage` | An objective is moved into a stage | Required — the target stage |
| `task_done` | An objective is marked complete | Optional — limits to a specific stage |
| `checklist_completed` | All checklist items on an objective are checked | Optional |

When `trigger_stage_id` is set, the automation only fires when the task is in (or moves into) that stage.

## Actions

| `action_type` | Description | Extra fields |
|---|---|---|
| `move_to_stage` | Move the objective to a different stage | `action_stage_id` (required) |
| `set_done` | Mark the objective as complete | — |
| `set_due_in_days` | Set the due date relative to today | `action_days_offset` (int, may be negative) |
| `set_task_type` | Change the objective's task type | `action_task_type_id` (required) |
| `set_color` | Change the objective's color | `action_color` (hex string) |

## Execution

`run_automations(task, event, db)` is called from route handlers whenever a relevant state change occurs:

- After `POST /api/tasks` → fires `task_created`
- After `PUT /api/tasks/reorder` or `PUT /api/tasks/{id}/move` when stage changes → fires `task_moved_to_stage`
- After `PUT /api/tasks/{id}` when `done` transitions to `true` → fires `task_done`
- After `PUT /api/tasks/{id}/checklist/{item_id}` when all items become done → fires `checklist_completed`
- When a Quest's checklist item is checked, the spawned child objective also gets `task_done` fired.

Multiple automations can match a single event; they all run in the order they are returned from the database.

## Example Rules

**Auto-close on move to "Done" stage**
- Trigger: `task_moved_to_stage`, stage = "Done"
- Action: `set_done`

**Set due date 7 days out when created**
- Trigger: `task_created`
- Action: `set_due_in_days`, offset = `7`

**Move to "In Review" when checklist completes**
- Trigger: `checklist_completed`
- Action: `move_to_stage`, stage = "In Review"
