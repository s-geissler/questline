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
- request size and timeout limits appropriate for your environment

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
