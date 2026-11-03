# Import from Trello

Export a single board as JSON from Trello, then open the **top-right user ☰ menu →
Import Hub from Trello** to create a new Hub. This menu is available from the Hubs
page and within existing Hubs. The export’s board name becomes the Hub name, and
you become its owner.

To replace content in an existing Hub, go to the Hubs overview and open the
**Hub card’s ☰ menu → Import from Trello**, alongside Rename and Delete. Only
owners and administrators can replace Hub content.

Choose the JSON file and review the Stage, Objective, and checklist counts. For
replacement, the preview also shows how much existing content will be deleted.
Select the confirmation checkbox and choose **Replace content** to proceed.

## Imported content

- Every exported list becomes a normal Stage, including empty lists. List and
  card ordering is preserved, and Stages are placed in the top row.
- Unarchived cards become base Objectives with their title, Markdown description,
  due date, and completion status. Archived cards and their associated data are
  skipped. Completion follows Trello’s `dueComplete` flag rather than the list name.
- Due timestamps become dates (`YYYY-MM-DD`); the timestamp’s time is discarded.
- Checklist items retain their order and completion state. If an Objective has
  multiple checklists, item titles are prefixed with the checklist name. Checklist
  items do not create child Objectives.
- Assignee display names/usernames and attachment filenames/links are appended
  to the original description in a **Trello import notes** Markdown section.
  Objectives remain unassigned, and files are not downloaded. Use these notes to
  assign people or transfer files manually. Trello links may still require access
  to the original board. Missing member details fall back to the exported member
  ID; unavailable attachment URLs are identified in the notes.

Custom fields, Task Types, labels, automation data, recurrence settings, board
styling, and activity/comment history are ignored. The importer creates no Hub
customization, memberships for Trello members, or Task Types.

## Replacing Hub content

Replacement preserves the Hub’s ID, name, color, position, and memberships. It
removes **all existing Stages, Objectives and their associated data, and all
automations**, then imports the file. Existing Task Type definitions, Custom Field
definitions, and Saved Filters are kept, but imported Objectives use no Task Type.

Quest spawn-stage settings referencing deleted Stages are cleared. Calendar feeds
that subscribe to selected Stages lose those selections; edit the subscriptions
to select the new Stages. Feeds subscribing to all Stages continue at the same URL.
Deleted Log Stages must also be recreated if needed.

The entire file is validated before changes are made. Creation/replacement and
membership creation are committed together; an import failure rolls back all
changes. Normal Objective creation/completion automations are not run during import.

## File limits

Use a single-board UTF-8 JSON export, optionally with a UTF-8 BOM, of at most
10 MiB. The importer enforces Questline’s existing limits: 120 characters for Hub
and Stage names, 200 characters for Objective/checklist titles, and 10,000
characters for each description **including appended import notes**. Exports
exceeding these limits are rejected with a message; text is never silently
truncated. Malformed data or missing list/checklist references on retained cards
also reject the file without changing the Hub.

## Regression checks

Run the API/parser and frontend checks with
`python -m pytest tests/test_trello_import.py tests/test_trello_import_frontend.py`.
The optional end-to-end check, `node tests/browser_trello_import.cjs`, requires
Playwright and Chromium plus the app’s Python dependencies. It launches the real
app with a disposable database; set `QUESTLINE_TEST_PYTHON` to use a virtualenv’s
Python executable.
