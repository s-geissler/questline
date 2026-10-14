# Deployment

## Overview

Questline is intended to run behind a reverse proxy such as nginx. For internet exposure, terminate HTTPS at the proxy edge and forward requests to the FastAPI app over a private network or local socket.

## HTTPS

- Serve Questline over HTTPS only.
- Redirect plain HTTP to HTTPS.
- Keep `QUESTLINE_ENV=production` in deployed environments so insecure cookie settings are rejected at startup.

## HSTS

HSTS should be configured at the HTTPS edge, not in the application.

Example nginx directive:

```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

Notes:

- Apply this only on the HTTPS server block.
- Use `includeSubDomains` only if every subdomain is intended to be HTTPS-only.
- Do not add `preload` unless you explicitly want preload-list behavior and have verified the domain-wide requirements.

## Proxy Headers

Questline ignores `X-Forwarded-For` unless the immediate peer IP is inside `QUESTLINE_TRUSTED_PROXIES`.

Recommended values:

- Local nginx on the same host: `QUESTLINE_TRUSTED_PROXIES=127.0.0.1/32`
- Reverse proxy on a private subnet: set the exact proxy subnet or IPs, for example `10.0.0.0/24`
- Multiple proxies: use a comma-separated list of IPs/CIDRs

Do not set this to overly broad ranges unless those addresses are actually restricted to trusted proxy infrastructure.

## Recommended Environment

For a typical HTTPS deployment behind nginx:

```bash
QUESTLINE_ENV=production
QUESTLINE_SESSION_MAX_AGE_DAYS=30
QUESTLINE_SESSION_COOKIE_SAMESITE=lax
QUESTLINE_TRUSTED_PROXIES=127.0.0.1/32
```

Additional guidance:

- Leave `QUESTLINE_ALLOW_INSECURE_COOKIES` unset in deployed environments.
- Leave `QUESTLINE_SESSION_COOKIE_SECURE` unset unless you need an explicit override.
- Consider `QUESTLINE_SESSION_MAX_AGE_DAYS=7` or `14` if you want shorter-lived sessions.
- Leave `QUESTLINE_AUDIT_LOG_PATH` unset if you want audit events captured by `systemd`/journald or container stdout logging.
- Set `QUESTLINE_AUDIT_LOG_PATH` only if you explicitly want a dedicated audit log file.

## nginx Notes

Suggested baseline responsibilities for nginx:

- TLS termination
- HTTP to HTTPS redirect
- HSTS header
- forwarding `Host`, `X-Forwarded-Proto`, and `X-Forwarded-For`
- request size and timeout limits appropriate for your environment; allow at least 10 MiB plus 64 KiB of multipart overhead for task attachment uploads and `.eml` imports

## Calendar Subscriptions

Set the externally reachable URL so subscription URLs and links to objectives use
your public HTTPS origin, even when the app runs behind a reverse proxy:

```bash
QUESTLINE_PUBLIC_BASE_URL=https://questline.example
```

The URL must have no username, password, query string, or fragment. Production requires
HTTPS. When unset, URLs derive from the incoming request's base URL; ensure your proxy
forwards the correct host and scheme. This setting does not change proxy trust or
cookie behavior. For local development, `http://localhost:8000` is supported with
`QUESTLINE_ENV=development`.

Subscription secrets are query parameters. Questline redacts query strings for
calendar URLs in Uvicorn's access logger, and the app's timing logs contain only paths.
Configure nginx and any other proxy or monitoring service to avoid recording calendar
query strings. For example, define a format that uses `$uri` instead of `$request` or
`$request_uri`, then select it for the calendar location (adapt upstream settings):

```nginx
# In the http context:
log_format questline_calendar '$remote_addr "$request_method $uri $server_protocol" $status';

# In the HTTPS server context:
location /calendar/ {
    access_log /var/log/nginx/questline-calendar.log questline_calendar;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Allow `GET` and `HEAD` for these URLs and preserve query parameters when proxying.
Keep them out of shared caches. Errors must not redirect calendar clients to an HTML
login page. See [calendar.md](calendar.md) for subscription setup and revocation.

## Database Backups

Task attachments are stored as BLOBs in the configured database. Questline enables SQLite WAL mode, so do not back up a running instance by copying only the main `.db` file; committed data may still be in the WAL file. Use SQLite's online backup API or stop Questline and checkpoint the WAL before copying the database.

## Audit Logs

Questline emits security-sensitive audit events on the `questline.audit` logger as JSON lines.

Recommended defaults:

- use stdout/stderr logging and let `systemd` capture events in journald
- inspect with `journalctl -u <service-name>`

Optional file logging:

```bash
QUESTLINE_AUDIT_LOG_PATH=/var/log/questline/audit.log
QUESTLINE_AUDIT_LOG_LEVEL=INFO
```

## Verification

After deployment:

1. Confirm HTTPS is enforced and HTTP redirects cleanly.
2. Confirm `Strict-Transport-Security` is present on HTTPS responses.
3. Confirm session cookies are marked `Secure`.
4. Confirm `QUESTLINE_TRUSTED_PROXIES` matches the actual proxy peer seen by the app.
5. Confirm login and registration rate limiting still behaves as expected through the proxy.
