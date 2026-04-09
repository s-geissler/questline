# Authentication & Authorization

## Authentication

Questline uses **session cookies**. On login a random 32-byte URL-safe token is generated, its SHA-256 hash is stored in `user_sessions`, and the raw token is sent to the browser as an `httponly` cookie named `questline_session`.

Sessions have an absolute server-side lifetime controlled by `QUESTLINE_SESSION_MAX_AGE_DAYS` and default to 30 days. Expired sessions are rejected and deleted on use. The browser cookies use the same lifetime via `Max-Age`.

Unsafe API requests are protected with a session-bound CSRF token exposed to the browser as the `questline_csrf` cookie. The frontend echoes that value in `X-CSRF-Token`, and unsafe `/api/` requests must also present `X-Requested-With: XMLHttpRequest`.

Passwords are stored as `pbkdf2_sha256$<iterations>$<salt>$<digest>` using 120,000 PBKDF2-HMAC-SHA-256 iterations.

### Session Cookie Settings

| Env var | Default | Effect |
|---|---|---|
| `QUESTLINE_ENV` | `production` | Production mode requires secure session cookies |
| `QUESTLINE_ALLOW_INSECURE_COOKIES` | unset | Set to `1` or `true` in development to allow non-`Secure` cookies |
| `QUESTLINE_SESSION_COOKIE_SECURE` | unset | Explicit override for the `Secure` flag |
| `QUESTLINE_SESSION_COOKIE_SAMESITE` | `lax` | Accepts `lax`, `strict`, or `none` |
| `QUESTLINE_SESSION_MAX_AGE_DAYS` | `30` | Absolute session lifetime in days; must be a positive integer |

### Proxy Trust

| Env var | Default | Effect |
|---|---|---|
| `QUESTLINE_TRUSTED_PROXIES` | unset | Comma-separated proxy IPs/CIDRs trusted to supply `X-Forwarded-For` |

If `QUESTLINE_TRUSTED_PROXIES` is unset, Questline ignores `X-Forwarded-For` and uses the direct peer IP for login and registration rate limiting. Set this when running behind nginx or another reverse proxy and include only the proxy addresses that connect directly to the app.

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

```text
viewer  <  editor  <  owner
  1           2          3
```

| Role | Permissions |
|---|---|
| `viewer` | Read board, stages, tasks, filters, automations, members |
| `editor` | All viewer permissions + create/update/delete tasks, stages, filters, automations, task types |
| `owner` | All editor permissions + manage membership (add/remove/promote members) |

A board must always retain at least one owner; removing or demoting the last owner is blocked.

Instance `admin` is not stored as a board membership role. Admin users bypass membership checks and are treated as having full access to every board.

## Authorization Flow

Every API handler calls `_authorize_board_request(request, db, board_id, min_role)`:

1. Read `questline_session` cookie → look up `UserSession` by token hash.
2. If the session is missing, expired, or the user is inactive → reject it (`401 Unauthorized` for protected endpoints).
3. Load `User`.
4. If user is instance `admin` → pass (effective role = `"admin"`).
5. Look up `BoardMembership` for `(board_id, user.id)` → compare role rank against `min_role`.
6. If rank is insufficient → `403 Forbidden`.

## Endpoints Requiring No Authentication

- `GET /login`
- `GET /register`
- `POST /api/auth/login` (XHR-only)
- `POST /api/auth/register` (when registration is enabled, XHR-only)
