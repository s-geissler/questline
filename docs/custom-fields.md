# Custom Fields

Custom fields let you attach structured metadata to objectives. Fields are defined at the **Task Type** level — every objective of that type shares the same field definitions.

## Field Types

| `field_type` | Description | `options` used? |
|---|---|---|
| `text` | Free-form single-line string | No |
| `number` | Numeric value | No |
| `date` | ISO date string (`YYYY-MM-DD`) | No |
| `select` | Single choice from a predefined list | Yes |
| `multiselect` | Multiple choices from a predefined list | Yes |
| `checkbox` | Boolean flag | No |

## Options (for select/multiselect)

Options are stored as a JSON array on `CustomFieldDef.options`. Each option is an object:

```json
[
  { "label": "High",   "color": "#e74c3c" },
  { "label": "Medium", "color": "#f39c12" },
  { "label": "Low",    "color": null }
]
```

The API accepts both bare strings and full objects; bare strings are normalized to `{ "label": "<string>", "color": null }` on write.

## Card Display

Setting `show_on_card = true` on a field definition causes the field to be rendered on the task card in the board view (alongside the task title).

## Saved Filter Integration

Custom fields can be used as filter conditions in Saved Filters. The filter rule references a `field_def_id` and supports these operators:

| Operator | Meaning |
|---|---|
| `eq` | Equals |
| `neq` | Not equals |
| `contains` | String contains (case-insensitive) |
| `empty` | Field has no value |
| `not_empty` | Field has a value |
| `lt` | Less than |
| `gt` | Greater than |
| `lte` | Less than or equal (lexicographic for dates) |
| `gte` | Greater than or equal |

When a Task Type filter is active on a Log Stage or Saved Filter, custom field rules are validated to ensure the referenced field belongs to the selected task type.

## API

See [api.md — Task Types](api.md#task-types) for the full CRUD endpoints.
