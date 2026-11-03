import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("account_role", ["admin", "user"])
def test_overview_shows_owned_and_shared_hubs_including_admin_name(app_env, account_role):
    main, db, models = (app_env[key] for key in ("main", "db", "models"))
    user = models.User(email="member@example.com", display_name="Member", password_hash="unused", role=account_role)
    owner = models.User(email="owner@example.com", display_name="Owner", password_hash="unused")
    other = models.User(email="other@example.com", display_name="Other", password_hash="unused")
    db.add_all([user, owner, other])
    db.flush()

    owned = models.Board(name="My Hub", owner_user_id=user.id, position=0)
    shared = [
        models.Board(name=name, owner_user_id=owner.id, position=position)
        for position, name in enumerate(("admin", "Shared Editor", "Shared Owner"), start=1)
    ]
    unrelated = models.Board(name="Shared with someone else", owner_user_id=owner.id, position=4)
    orphan = models.Board(name="Orphan Hub", position=5)
    db.add_all([owned, *shared, unrelated, orphan])
    db.flush()
    main.ensure_board_membership(owned, user, "owner", db)
    for board, role in zip(shared, ("viewer", "editor", "owner")):
        main.ensure_board_membership(board, owner, "owner", db)
        main.ensure_board_membership(board, user, role, db)
    main.ensure_board_membership(unrelated, owner, "owner", db)
    main.ensure_board_membership(unrelated, other, "viewer", db)
    token, _ = main.create_user_session(user, db)
    db.commit()

    request = main.Request({
        "type": "http", "method": "GET", "path": "/api/boards",
        "headers": [(b"cookie", f"questline_session={token}".encode())],
    })
    payload = main.get_boards(request, db)
    expected_ids = [owned.id, *(board.id for board in shared)]

    # Exercise the real overview controller using the API's response. Admin role
    # alone, or a Hub being shared with other people, must not make it appear.
    script = f"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = Object.fromEntries(
  ['#home-boards-grid', '#home-empty-state', '#home-create-form', '#home-new-board-name']
    .map(selector => [selector, {{innerHTML: '', classList: {{toggle() {{}}}}}}])
);
const root = {{addEventListener() {{}}, querySelector(selector) {{return nodes[selector];}}}};
const context = {{
  root,
  document: {{addEventListener() {{}}}},
  async fetch(url) {{
    assert.equal(url, '/api/boards');
    return {{async json() {{return {json.dumps(payload)};}}}};
  }},
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(ROOT / 'static' / 'home.js'))}, 'utf8'), context);
const controller = vm.runInContext('new HomePageController(root)', context);
(async () => {{
  await controller.init();
  assert.deepEqual(Array.from(controller.boards, board => board.id), {json.dumps(expected_ids)});
  assert(nodes['#home-boards-grid'].innerHTML.includes('>admin</span>'));
  assert(!nodes['#home-boards-grid'].innerHTML.includes('Shared with someone else'));
  assert(!nodes['#home-boards-grid'].innerHTML.includes('Orphan Hub'));
}})().catch(error => {{console.error(error); process.exitCode = 1;}});
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    if account_role == "admin":
        unrelated_payload = next(board for board in payload if board["id"] == unrelated.id)
        assert unrelated_payload["is_shared"] is True
        assert unrelated_payload["is_member"] is False
        assert unrelated_payload["is_owner"] is False
