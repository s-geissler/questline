# Questline

Questline is a self-hosted project management tool built around a kanban-style board. Work is organized into **Hubs** (boards), **Stages** (columns), and **Objectives** (tasks). Objectives can be grouped under **Quests** (epics) whose checklist items automatically spawn child objectives.

Objectives can also be configured to **repeat on a schedule**. Recurrence is attached to an individual objective, generates future copies into an explicit start stage, and is processed by a background worker.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the development server
uvicorn main:app --reload

# Open in browser
open http://localhost:8000
```

The first registered account is automatically promoted to admin.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `QUESTLINE_DATABASE_URL` | `sqlite:///./questline.db` | SQLAlchemy database URL |
| `QUESTLINE_SLOW_QUERY_MS` | `200` | Log threshold for slow SQL queries (ms) |
| `QUESTLINE_SESSION_COOKIE_SECURE` | `""` | Set to `1` or `true` to require HTTPS for the session cookie |
| `QUESTLINE_SESSION_COOKIE_SAMESITE` | `lax` | Cookie SameSite policy (`lax`, `strict`, or `none`) |

## Built-in URLs

| Path | Description |
|---|---|
| `/` | Hub overview / home page |
| `/board/{id}` | Board view |
| `/board/{id}/task-types` | Task type configuration |
| `/board/{id}/automations` | Automation rules |
| `/board/{id}/filters` | Saved filters |
| `/admin` | Admin panel (admin-only) |
| `/login` | Login page |
| `/register` | Registration page |
| `/docs` | Auto-generated OpenAPI docs (FastAPI) |

## Documentation

- [architecture.md](architecture.md) — Data model, module overview, ER diagram
- [auth.md](auth.md) — Authentication, sessions, and role-based access control
- [api.md](api.md) — REST API reference
- [automations.md](automations.md) — Automation engine: triggers, conditions, actions
- [custom-fields.md](custom-fields.md) — Custom field types and usage
- [development.md](development.md) — Local setup, testing, contributing
