# Calendar subscriptions

Questline can expose objective deadlines as a private, read-only iCalendar (`.ics`)
subscription. Thunderbird and other calendar apps fetch the URL periodically; changes
appear on their next refresh. Deadline edits are made in Questline.

## Create a subscription

1. Open your user menu and choose **Calendar subscriptions**. You can also use the
   subscription button in a hub's calendar toolbar, which selects that hub.
2. Give the subscription a name. Choose **All accessible hubs** or a single hub.
3. **All stages** is selected by default. Uncheck individual stages to customize,
   or clear **All stages** and check the stages you want. For all-hub subscriptions,
   stages are grouped by hub. Changing the hub resets the selection to **All stages**.
4. Optionally select **Only objectives assigned to me**.
5. Click **Create subscription**, then copy and save the URL. The full URL is shown
   only at creation or regeneration.

Every unfinished objective with a valid built-in due date appears once, as an all-day
entry on its deadline. Entries include the objective title, description, and a link
back to Questline. They do not mark you as busy. Completed objectives, objectives
without deadlines, and custom date fields are excluded. Clearing a deadline,
completing an objective, or deleting it removes its entry on the next refresh.

The all-hubs option follows your current access, including admin access to all hubs.
Gaining or losing hub access changes the feed on its next fetch. A single-hub
subscription stops working if you lose access to that hub. Deactivating or deleting
the owning user also disables their subscriptions.

## Stage selection

**All stages** includes current and future stages within the subscription's hub
scope. A custom selection includes only the checked stages and must contain at least
one stage when saved. Log views are excluded because they show objectives stored in
other stages.

Use **Edit stages** on an existing subscription to change its selection. Saving keeps
the same URL and secret; the calendar reflects the change on its next refresh. Tasks
moved into a selected stage appear, and tasks moved out disappear. Deleting a selected
stage removes it from the selection. If every selected stage is deleted, the feed is
empty until you choose other stages or **All stages**. It never automatically expands
to include other stages. Existing subscriptions default to **All stages**.

## Thunderbird

1. Create a new calendar and choose **On the Network**.
2. Paste the subscription URL into **Location**.
3. Select **This location doesn't require credentials**. The secret in the URL is
   the credential, so no Questline username or password is needed.
4. Choose **Find Calendars**, then **Subscribe**. Keep the subscription read-only.
5. Adjust the refresh interval in the calendar properties if desired. Use a manual
   refresh to check a deadline change immediately.

Subscribe to the network URL rather than importing a downloaded file, which would
produce a snapshot. The Questline server must be reachable from your calendar app.

During discovery, Thunderbird may send `PROPFIND` requests to the subscription URL,
`/.well-known/caldav`, and the server root. The resulting `405 Method Not Allowed`
and `404 Not Found` responses are expected: Questline exposes an iCalendar feed
through `GET` and `HEAD`, and does not provide CalDAV discovery. Successful refreshes
use `GET` and return `200 OK` or `304 Not Modified` when the calendar has not changed.

## Regenerate or revoke

Anyone holding a subscription URL can read its exported titles and descriptions.
Keep the URL private. The database stores only a hash of its secret, and existing
subscriptions list only its last four characters.

**Regenerate URL** immediately replaces the secret. Copy the new URL and replace the
old subscription in your calendar app. **Revoke** immediately disables future
downloads. Calendar apps may retain entries they have already downloaded; remove the
subscription there to clear those local copies. A feed secret grants no access to
the normal Questline API and cannot change objectives.

## Recurring objectives

Subscriptions export stored objective deadlines. They do not export the in-app
calendar's next-run previews or project an iCalendar recurrence rule. When recurrence
creates a new objective, it receives a new event identity. When recurrence reuses an
objective, its existing calendar entry moves to the new deadline. Invalid legacy
deadline strings are skipped and logged by objective ID; new deadline inputs require
`YYYY-MM-DD`.

## API

Management endpoints require normal session or bearer authentication. Session writes
require the usual XHR and CSRF headers. Calendar credentials do not authenticate these
endpoints.

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/calendar-feeds` | List your active subscription metadata; never return secrets |
| GET | `/api/calendar-feeds/stages` | List accessible stages and hub names without objectives or log views |
| POST | `/api/calendar-feeds` | Create a subscription and return its URL once (`201`) |
| PATCH | `/api/calendar-feeds/{id}` | Update an owned subscription's `stage_ids` without replacing its URL |
| POST | `/api/calendar-feeds/{id}/rotate` | Replace its secret and return the new URL once |
| DELETE | `/api/calendar-feeds/{id}` | Revoke an owned subscription |
| GET, HEAD | `/calendar/{id}.ics?token={secret}` | Fetch its calendar without a browser session |

Creation accepts `name` (up to 80 characters, default `Thunderbird`), nullable
`board_id` (default all accessible hubs), `assigned_only` (default `false`), and
`stage_ids` (default `null`, meaning all stages). A custom `stage_ids` value is a
nonempty list of positive stage IDs from accessible hubs within the feed's scope;
duplicates are normalized. Invalid or out-of-scope selections return `422`.
Stage updates require a `stage_ids` field; `null` restores **All stages**. Metadata
includes `stage_ids` and selected stage names, omitting names from inaccessible hubs.
Creation and rotation return `subscription_url` alongside metadata. Single-hub feeds
require at least viewer access.

Successful calendar responses use `text/calendar; charset=utf-8`, a deterministic
ETag, and `Cache-Control: private, no-cache`. `If-None-Match` supports `304` responses.
Authorization is checked before evaluating ETags. Invalid, revoked, or inaccessible
feeds return `404` without a login redirect; `HEAD` uses the same checks as `GET`.

See [deployment.md](deployment.md#calendar-subscriptions) for public URLs and secret
redaction in access logs.
