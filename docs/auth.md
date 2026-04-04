# Authentication & Authorization

## Authentication

Questline uses **session cookies**. On login a random 32-byte URL-safe token is generated, its SHA-256 hash is stored in `user_sessions`, and the raw token is sent to the browser as an `httponly` cookie named `questline_session`.

Unsafe API requests are protected with a session-bound CSRF token exposed to the browser as the `questline_csrf` cookie. The frontend echoes that value in `X-CSRF-Token`, and unsafe `/api/` requests must also present `X-Requested-With: XMLHttpRequest`.

Passwords are stored as `pbkdf2_sha256$<iterations>$<salt>$<digest>` using 120,000 PBKDF2-HMAC-SHA-256 iterations.

### Session Cookie Settings

| Env var | Default | Effect |
|---|---|---|
| `QUESTLINE_SESSION_COOKIE_SECURE` | `""` (off) | Set to `1` or `true` to add the `Secure` flag (HTTPS-only) |
| `QUESTLINE_SESSION_COOKIE_SAMESITE` | `lax` | Accepts `lax`, `strict`, or `none` |

### Registration

- Open registration can be toggled by an admin via instance settings.
- The **first registered user** is automatically promoted to `admin`.
- New accounts can be set to inactive by default (configurable by admin).

## User Roles (Instance-level)

| Role | Description |
|---|---|
| `user` | Normal user — access gated by board membership |
| `admin` | Can access all boards, manage users, change instance settings |

The instance must always have at least one admin; demoting the last admin is blocked.

## Board Membership Roles

Access to a board is controlled by a membership record. The roles form an ordered hierarchy:

```
viewer  <  editor  <  owner  <  admin
  1           2          3        4
```

| Role | Permissions |
|---|---|
| `viewer` | Read board, stages, tasks, filters, automations, members |
| `editor` | All viewer permissions + create/update/delete tasks, stages, filters, automations, task types |
| `owner` | All editor permissions + manage membership (add/remove/promote members) |
| `admin` | Full access to all boards regardless of membership |

A board must always retain at least one owner; removing or demoting the last owner is blocked.

## Authorization Flow

Every API handler calls `_authorize_board_request(request, db, board_id, min_role)`:

1. Read `questline_session` cookie → look up `UserSession` by token hash → load `User`.
2. If no valid session → `401 Unauthorized`.
3. If user is instance `admin` → pass (effective role = `"admin"`).
4. Look up `BoardMembership` for `(board_id, user.id)` → compare role rank against `min_role`.
5. If rank is insufficient → `403 Forbidden`.

## Endpoints Requiring No Authentication

- `GET /login`
- `GET /register`
- `POST /api/auth/login` (XHR-only)
- `POST /api/auth/register` (when registration is enabled, XHR-only)
