"""Stage placement regressions through the public board controller methods.

Worked examples use (stage ID, row, column); row 0 is top and row 1 is bottom.
Insertion boundaries refer to the ORIGINAL columns, before removing the source.
"""

import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAIRS = [(1, 0, 0), (2, 1, 0), (3, 0, 1), (4, 1, 1), (5, 0, 2), (6, 1, 2)]


def assert_stage_placements(method, placements, arguments, expected):
    def records(rows):
        return [dict(id=stage_id, row=row, position=column) for stage_id, row, column in rows]

    board_js = ROOT / "static" / "board" / "board.js"
    script = f"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const context = {{
  document: {{ addEventListener() {{}} }},
  renderMarkdown(value) {{ return value || ''; }},
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(board_js))}, 'utf8'), context);
const board = context._createBoard();
const placements = {json.dumps(records(placements))};
const before = JSON.parse(JSON.stringify(placements));
const expected = {json.dumps(records(expected))};

const result = board[{json.dumps(method)}](placements, ...{json.dumps(arguments)});
// Convert VM objects to this realm before comparing their values/prototypes.
const actual = JSON.parse(JSON.stringify(result));
assert.deepStrictEqual(placements, before, 'input placements must remain unchanged');
assert.deepStrictEqual(actual, expected, 'worked placement example');

assert.deepStrictEqual(
  actual.map(p => p.id).sort((a, b) => a - b),
  before.map(p => p.id).sort((a, b) => a - b),
  'every original stage ID must be preserved exactly once',
);
assert.strictEqual(new Set(actual.map(p => p.id)).size, actual.length, 'unique IDs');
assert.strictEqual(
  new Set(actual.map(p => `${{p.row}}:${{p.position}}`)).size,
  actual.length,
  'each occupied slot must be unique',
);
const topColumns = new Set(actual.filter(p => p.row === 0).map(p => p.position));
assert(actual.every(p => p.row !== 1 || topColumns.has(p.position)),
  'every bottom stage must have a top stage in its column');
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "placements,dragged_id,boundary,expected",
    [
        pytest.param(
            PAIRS, 1, 2,
            [(2, 0, 0), (3, 0, 1), (4, 1, 1), (1, 0, 2), (5, 0, 3), (6, 1, 3)],
            id="top-from-left-promotes-companion-and-shifts-entire-target-pair",
        ),
        pytest.param(
            PAIRS, 5, 1,
            [(1, 0, 0), (2, 1, 0), (5, 0, 1), (3, 0, 2), (4, 1, 2), (6, 0, 3)],
            id="top-from-right-promotes-companion-before-shifting",
        ),
        pytest.param(
            PAIRS, 2, 2,
            [(1, 0, 0), (3, 0, 1), (4, 1, 1), (2, 0, 2), (5, 0, 3), (6, 1, 3)],
            id="lower-from-left-becomes-top",
        ),
        pytest.param(
            PAIRS, 6, 1,
            [(1, 0, 0), (2, 1, 0), (6, 0, 1), (3, 0, 2), (4, 1, 2), (5, 0, 3)],
            id="lower-from-right-keeps-source-top",
        ),
        pytest.param(
            [(1, 0, 0), (3, 0, 1), (4, 1, 1), (5, 0, 2), (6, 1, 2)], 1, 2,
            [(3, 0, 0), (4, 1, 0), (1, 0, 1), (5, 0, 2), (6, 1, 2)],
            id="unpaired-top-from-left-uses-original-boundary-then-closes-gap",
        ),
        pytest.param(
            [(1, 0, 0), (2, 1, 0), (3, 0, 1), (4, 1, 1), (5, 0, 2)], 5, 1,
            [(1, 0, 0), (2, 1, 0), (5, 0, 1), (3, 0, 2), (4, 1, 2)],
            id="unpaired-top-from-right-closes-empty-source-column",
        ),
        pytest.param(
            PAIRS, 6, 0,
            [(6, 0, 0), (1, 0, 1), (2, 1, 1), (3, 0, 2), (4, 1, 2), (5, 0, 3)],
            id="before-first-column-shifts-all-remaining-placements",
        ),
        pytest.param(
            PAIRS, 1, 3,
            [(2, 0, 0), (3, 0, 1), (4, 1, 1), (5, 0, 2), (6, 1, 2), (1, 0, 3)],
            id="after-last-column-promotes-source-companion",
        ),
        pytest.param(
            [(1, 0, 0), (3, 0, 1), (4, 1, 1), (5, 0, 2)], 1, 3,
            [(3, 0, 0), (4, 1, 0), (5, 0, 1), (1, 0, 2)],
            id="after-last-column-with-empty-source-normalizes-gap",
        ),
        pytest.param(
            PAIRS, 3, 1,
            [(1, 0, 0), (2, 1, 0), (3, 0, 1), (4, 0, 2), (5, 0, 3), (6, 1, 3)],
            id="adjacent-before-source-shifts-promoted-companion",
        ),
        pytest.param(
            PAIRS, 3, 2,
            [(1, 0, 0), (2, 1, 0), (4, 0, 1), (3, 0, 2), (5, 0, 3), (6, 1, 3)],
            id="adjacent-after-source-leaves-promoted-companion-before-boundary",
        ),
        pytest.param(
            [(1, 0, 0), (3, 0, 1), (5, 0, 2)], 3, 1,
            [(1, 0, 0), (3, 0, 1), (5, 0, 2)],
            id="adjacent-before-unpaired-source-is-no-op-after-normalization",
        ),
        pytest.param(
            [(1, 0, 0), (3, 0, 1), (5, 0, 2)], 3, 2,
            [(1, 0, 0), (3, 0, 1), (5, 0, 2)],
            id="adjacent-after-unpaired-source-is-no-op-after-normalization",
        ),
        pytest.param(
            PAIRS, 999, 1, PAIRS,
            id="missing-stage-leaves-placements-unchanged",
        ),
        pytest.param([], 999, 0, [], id="missing-stage-on-empty-board"),
    ],
)
def test_stage_insertion(placements, dragged_id, boundary, expected):
    assert_stage_placements(
        "applyStageInsertion", placements, [dragged_id, boundary], expected
    )


@pytest.mark.parametrize(
    "placements,dragged_id,target_row,target_column,expected",
    [
        pytest.param(PAIRS, 1, 0, 0, PAIRS, id="same-top-slot-with-companion-is-no-op"),
        pytest.param(PAIRS, 2, 1, 0, PAIRS, id="same-lower-slot-is-no-op"),
        pytest.param(
            [(1, 0, 0), (3, 0, 1)], 1, 0, 0,
            [(1, 0, 0), (3, 0, 1)],
            id="same-top-slot-without-companion-is-no-op",
        ),
        pytest.param(
            PAIRS, 1, 0, 1,
            [(2, 0, 0), (3, 1, 0), (1, 0, 1), (4, 1, 1), (5, 0, 2), (6, 1, 2)],
            id="occupied-top-displaced-to-source-lower-after-promotion",
        ),
        pytest.param(
            PAIRS, 1, 1, 1,
            [(2, 0, 0), (4, 1, 0), (3, 0, 1), (1, 1, 1), (5, 0, 2), (6, 1, 2)],
            id="occupied-lower-displaced-to-source-lower-after-promotion",
        ),
        pytest.param(
            PAIRS, 2, 0, 1,
            [(1, 0, 0), (3, 1, 0), (2, 0, 1), (4, 1, 1), (5, 0, 2), (6, 1, 2)],
            id="lower-onto-occupied-top-displaces-to-original-lower-slot",
        ),
        pytest.param(
            PAIRS, 2, 1, 1,
            [(1, 0, 0), (4, 1, 0), (3, 0, 1), (2, 1, 1), (5, 0, 2), (6, 1, 2)],
            id="occupied-lower-slots-swap",
        ),
        pytest.param(
            [(1, 0, 0), (3, 0, 1), (4, 1, 1)], 1, 0, 1,
            [(3, 0, 0), (1, 0, 1), (4, 1, 1)],
            id="unpaired-top-displaces-occupied-top-to-source-top",
        ),
        pytest.param(
            PAIRS, 1, 1, 0,
            [(2, 0, 0), (1, 1, 0), (3, 0, 1), (4, 1, 1), (5, 0, 2), (6, 1, 2)],
            id="own-lower-slot-promotes-companion",
        ),
        pytest.param(
            [(1, 0, 0), (3, 0, 1), (5, 0, 2), (6, 1, 2)], 1, 1, 1,
            [(3, 0, 0), (1, 1, 0), (5, 0, 1), (6, 1, 1)],
            id="empty-lower-target-closes-empty-source-column",
        ),
        pytest.param(
            PAIRS, 1, 0, 3,
            [(2, 0, 0), (3, 0, 1), (4, 1, 1), (5, 0, 2), (6, 1, 2), (1, 0, 3)],
            id="empty-top-target-promotes-source-companion",
        ),
        pytest.param(PAIRS, 999, 0, 1, PAIRS, id="missing-stage-is-no-op"),
        pytest.param([], 999, 0, 0, [], id="missing-stage-on-empty-board"),
    ],
)
def test_stage_drop(placements, dragged_id, target_row, target_column, expected):
    assert_stage_placements(
        "applyStageDrop", placements, [dragged_id, target_row, target_column], expected
    )


@pytest.mark.parametrize(
    "placements,expected",
    [
        pytest.param(
            [(6, 1, 9), (3, 0, 5), (2, 1, 2), (5, 0, 9), (1, 0, 2)],
            [(1, 0, 0), (2, 1, 0), (3, 0, 1), (5, 0, 2), (6, 1, 2)],
            id="removes-leading-and-interior-empty-columns-and-orders-pairs",
        ),
        pytest.param(PAIRS, PAIRS, id="already-normalized-pairs-unchanged"),
        pytest.param([], [], id="empty-board"),
    ],
)
def test_normalize_stage_placements(placements, expected):
    assert_stage_placements("normalizeStagePlacements", placements, [], expected)


def test_inserted_column_layout_persists_without_moving_tasks(app_env):
    main, db = app_env["main"], app_env["db"]
    board = main.create_board(main.BoardCreate(name="Insertion"), db)
    stages = {}
    for name, row, position in [
        ("A", 0, 0), ("B", 0, 1), ("C", 0, 2),
        ("a", 1, 0), ("b", 1, 1), ("c", 1, 2),
    ]:
        stages[name] = main.create_stage(
            main.StageCreate(name=name, board_id=board["id"], row=row, position=position),
            db,
        )
    task = main.create_task(main.TaskCreate(title="Stays in C", stage_id=stages["C"]["id"]), db)
    # Insert C between A and B: B/b move together, c is promoted at the source.
    expected = [("A", 0, 0), ("a", 1, 0), ("C", 0, 1), ("B", 0, 2), ("b", 1, 2), ("c", 0, 3)]
    placements = [
        {"id": stages[name]["id"], "row": row, "position": position}
        for name, row, position in expected
    ]
    assert main.reorder_stages(main.ReorderStages(stages=placements), db) == {"ok": True}
    reloaded = main.get_stages(board["id"], db)
    assert sorted((stage["name"], stage["row"], stage["position"]) for stage in reloaded) == sorted(expected)
    assert main.get_task(task["id"], db)["stage_id"] == stages["C"]["id"]
