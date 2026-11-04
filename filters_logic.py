import json
import logging
import re
import time
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

import models
from authz import get_accessible_boards, require_board_access, _require_task_type_in_board
from services.tasks import deadline_datetime, normalize_due_date, task_assignees, task_assigned_to, task_has_assignees

logger = logging.getLogger("questline.logs")
SLOW_LOG_STAGE_MS = 150.0
MAX_SORT_RULES = 10
SORT_FIELDS = {
    "title", "description", "due_date", "created_at", "updated_at", "done",
    "task_type_id", "assignee_user_id", "color", "has_parent_task",
}


def _valid_sort_rule(rule) -> bool:
    if not isinstance(rule, dict) or not isinstance(rule.get("field"), str):
        return False
    if not isinstance(rule.get("direction"), str) or rule["direction"] not in {"asc", "desc"}:
        return False
    field = rule["field"]
    return field in SORT_FIELDS or (
        re.fullmatch(r"custom:[1-9][0-9]{0,18}", field) is not None
        and int(field.split(":", 1)[1]) <= 2**63 - 1
    )


def _task_detail_load_options():
    return (
        joinedload(models.Task.stage).joinedload(models.Stage.board),
        joinedload(models.Task.task_type).selectinload(models.TaskType.custom_fields),
        joinedload(models.Task.parent_task)
        .joinedload(models.Task.stage)
        .joinedload(models.Stage.board),
        joinedload(models.Task.assignee),
        selectinload(models.Task.assignees),
        selectinload(models.Task.custom_field_values),
        selectinload(models.Task.checklist_items),
        selectinload(models.Task.attachments),
        joinedload(models.Task.recurrence),
    )


def default_filter_definition():
    return {"op": "and", "selected_task_type_id": None, "source_board_ids": [], "rules": [], "sort_rules": []}


def parse_filter_definition(definition: str | None) -> dict:
    parsed = default_filter_definition()
    if not definition:
        return parsed
    try:
        raw = json.loads(definition)
    except json.JSONDecodeError:
        return parsed
    if not isinstance(raw, dict):
        return parsed
    parsed["op"] = raw.get("op") if raw.get("op") in {"and", "or"} else "and"
    parsed["selected_task_type_id"] = raw.get("selected_task_type_id")
    source_board_ids = raw.get("source_board_ids") if isinstance(raw.get("source_board_ids"), list) else []
    parsed["source_board_ids"] = [
        int(board_id)
        for board_id in source_board_ids
        if isinstance(board_id, int) or (isinstance(board_id, str) and board_id.isdigit())
    ]
    rules = raw.get("rules") if isinstance(raw.get("rules"), list) else []
    parsed["rules"] = [
        {
            "field": rule.get("field"),
            "operator": rule.get("operator"),
            "value": rule.get("value"),
        }
        for rule in rules
        if isinstance(rule, dict) and rule.get("field") and rule.get("operator")
    ]
    sort_rules = raw.get("sort_rules")
    if isinstance(sort_rules, list):
        parsed["sort_rules"] = [
            {"field": rule["field"], "direction": rule["direction"]}
            for rule in sort_rules[:MAX_SORT_RULES] if _valid_sort_rule(rule)
        ]
    return parsed


def _validated_filter_definition(
    definition: dict | None,
    owning_board_id: int,
    db: Session,
    user: Optional[models.User] = None,
) -> dict:
    parsed = parse_filter_definition(json.dumps(definition or default_filter_definition()))
    sort_rules = (definition or {}).get("sort_rules", [])
    if not isinstance(sort_rules, list) or len(sort_rules) > MAX_SORT_RULES:
        raise HTTPException(status_code=400, detail=f"Provide at most {MAX_SORT_RULES} sorting rules")
    seen_sort_fields = set()
    for rule in sort_rules:
        if not _valid_sort_rule(rule):
            raise HTTPException(status_code=400, detail="Invalid sorting rule")
        if rule["field"] in seen_sort_fields:
            raise HTTPException(status_code=400, detail="A sort field can only be used once")
        seen_sort_fields.add(rule["field"])
        if rule["field"].startswith("custom:"):
            field_id = int(rule["field"].split(":", 1)[1])
            field_def = db.get(models.CustomFieldDef, field_id)
            if not field_def or not field_def.task_type or field_def.task_type.board_id != owning_board_id:
                raise HTTPException(status_code=400, detail="Invalid custom sort field")
            if parsed["selected_task_type_id"] is not None and field_def.task_type_id != parsed["selected_task_type_id"]:
                raise HTTPException(status_code=400, detail="Custom sort field does not match selected type")
    if parsed["selected_task_type_id"] is not None:
        _require_task_type_in_board(parsed["selected_task_type_id"], owning_board_id, db)

    validated_source_board_ids = []
    for board_id in parsed.get("source_board_ids") or []:
        board = db.query(models.Board).filter(models.Board.id == board_id).first()
        if not board:
            raise HTTPException(status_code=400, detail="Invalid source board")
        if user is not None:
            require_board_access(board_id, user, db, "viewer")
        validated_source_board_ids.append(board_id)
    parsed["source_board_ids"] = list(dict.fromkeys(validated_source_board_ids))

    for rule in parsed.get("rules") or []:
        if rule["field"] == "task_type_id" and rule.get("value") not in {None, ""}:
            try:
                task_type_id = int(rule["value"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid task type rule")
            _require_task_type_in_board(task_type_id, owning_board_id, db)
        if rule["field"] == "assignee_user_id" and rule.get("value") not in {None, ""}:
            if rule["value"] == "__me__":
                if user is None:
                    raise HTTPException(status_code=400, detail="Invalid assignee rule")
            else:
                try:
                    assignee_user_id = int(rule["value"])
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail="Invalid assignee rule")
                assignee = db.query(models.User).filter(models.User.id == assignee_user_id).first()
                has_board_access = (
                    assignee is not None
                    and (
                        assignee.role == "admin"
                        or db.query(models.BoardMembership)
                        .filter(
                            models.BoardMembership.board_id == owning_board_id,
                            models.BoardMembership.user_id == assignee_user_id,
                        )
                        .first()
                        is not None
                    )
                )
                if not has_board_access:
                    raise HTTPException(status_code=400, detail="Invalid assignee rule")
        if rule["field"].startswith("custom:"):
            try:
                field_id = int(rule["field"].split(":", 1)[1])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid custom field rule")
            field_def = db.query(models.CustomFieldDef).filter(models.CustomFieldDef.id == field_id).first()
            if not field_def or not field_def.task_type or field_def.task_type.board_id != owning_board_id:
                raise HTTPException(status_code=400, detail="Invalid custom field rule")
            if parsed["selected_task_type_id"] is not None and field_def.task_type_id != parsed["selected_task_type_id"]:
                raise HTTPException(status_code=400, detail="Custom field rule does not match selected type")
    return parsed


def saved_filter_to_dict(saved_filter: models.SavedFilter) -> dict:
    return {
        "id": saved_filter.id,
        "board_id": saved_filter.board_id,
        "name": saved_filter.name,
        "definition": parse_filter_definition(saved_filter.definition),
    }


def stage_to_dict(stage: models.Stage) -> dict:
    return {
        "id": stage.id,
        "name": stage.name,
        "row": stage.row or 0,
        "position": stage.position,
        "is_log": stage.is_log,
        "filter_id": stage.filter_id,
        "saved_filter": saved_filter_to_dict(stage.saved_filter) if stage.saved_filter else None,
    }


def _task_field_value(task: models.Task, field: str):
    if field == "title":
        return task.title or ""
    if field == "description":
        return task.description or ""
    if field == "done":
        return task.done
    if field == "due_date":
        return task.due_date
    if field == "color":
        return task.color or ""
    if field == "task_type_id":
        return task.task_type_id
    if field == "assignee_user_id":
        return [user.id for user in task_assignees(task)]
    if field == "has_parent_task":
        return bool(task.parent_task_id)
    if field.startswith("custom:"):
        try:
            field_id = int(field.split(":", 1)[1])
        except (TypeError, ValueError):
            return None
        for cfv in task.custom_field_values:
            if cfv.field_def_id == field_id:
                return cfv.value
        return None
    return None


def _resolve_dynamic_filter_value(expected, current_user: Optional[models.User]):
    if expected == "__me__":
        return current_user.id if current_user is not None else None
    return expected


def _rule_matches(task: models.Task, rule: dict, current_user: Optional[models.User] = None) -> bool:
    value = _task_field_value(task, rule["field"])
    operator = rule["operator"]
    expected = _resolve_dynamic_filter_value(rule.get("value"), current_user)

    if expected == "today":
        expected = date.today().isoformat()

    if rule["field"] == "assignee_user_id":
        if operator == "empty":
            return not value
        if operator == "not_empty":
            return bool(value)
        if operator in {"eq", "neq"}:
            matches = expected is not None and str(expected) in {str(user_id) for user_id in value}
            return matches if operator == "eq" else not matches
        return False

    if rule["field"] in {"done", "has_parent_task"}:
        if isinstance(expected, str):
            expected = expected.lower() == "true"

    if operator == "contains":
        return expected is not None and str(expected).lower() in str(value or "").lower()
    if operator == "eq":
        return value == expected if isinstance(expected, bool) else str(value) == str(expected)
    if operator == "neq":
        return value != expected if isinstance(expected, bool) else str(value) != str(expected)
    if operator == "empty":
        return value is None or str(value).strip() == ""
    if operator == "not_empty":
        return value is not None and str(value).strip() != ""
    if operator == "lt":
        return value is not None and expected is not None and str(value) < str(expected)
    if operator == "gt":
        return value is not None and expected is not None and str(value) > str(expected)
    if operator == "lte":
        return value is not None and expected is not None and str(value) <= str(expected)
    if operator == "gte":
        return value is not None and expected is not None and str(value) >= str(expected)
    return False


def _task_matches_filter(task: models.Task, definition: dict, current_user: Optional[models.User] = None) -> bool:
    if definition.get("selected_task_type_id"):
        if task.task_type_id != definition["selected_task_type_id"]:
            return False
    rules = definition.get("rules") or []
    if not rules:
        return True
    matches = [_rule_matches(task, rule, current_user) for rule in rules]
    return all(matches) if definition.get("op") != "or" else any(matches)


def _prefilter_log_query(query, definition: dict, current_user: Optional[models.User] = None):
    if definition.get("selected_task_type_id") is not None:
        query = query.filter(models.Task.task_type_id == definition["selected_task_type_id"])

    for rule in definition.get("rules") or []:
        field = rule["field"]
        operator = rule["operator"]
        value = rule.get("value")

        if field == "done" and operator in {"eq", "neq"}:
            expected = value if isinstance(value, bool) else str(value).lower() == "true"
            query = query.filter(models.Task.done == expected if operator == "eq" else models.Task.done != expected)
        elif field == "due_date":
            if operator == "empty":
                query = query.filter(or_(models.Task.due_date.is_(None), models.Task.due_date == ""))
            elif operator == "not_empty":
                query = query.filter(models.Task.due_date.is_not(None), models.Task.due_date != "")
            elif operator in {"lt", "lte", "gt", "gte", "eq"} and value is not None:
                expected = date.today().isoformat() if value == "today" else str(value)
                column = models.Task.due_date
                if operator == "lt":
                    query = query.filter(column < expected)
                elif operator == "lte":
                    query = query.filter(column <= expected)
                elif operator == "gt":
                    query = query.filter(column > expected)
                elif operator == "gte":
                    query = query.filter(column >= expected)
                elif operator == "eq":
                    query = query.filter(column == expected)
        elif field == "task_type_id":
            if operator == "empty":
                query = query.filter(models.Task.task_type_id.is_(None))
            elif operator == "not_empty":
                query = query.filter(models.Task.task_type_id.is_not(None))
            elif operator in {"eq", "neq"} and value not in {None, ""}:
                expected = int(value)
                if operator == "eq":
                    query = query.filter(models.Task.task_type_id == expected)
                else:
                    query = query.filter(or_(models.Task.task_type_id.is_(None), models.Task.task_type_id != expected))
        elif field == "assignee_user_id":
            if operator == "empty":
                query = query.filter(~task_has_assignees())
            elif operator == "not_empty":
                query = query.filter(task_has_assignees())
            elif operator in {"eq", "neq"} and value not in {None, ""}:
                expected = _resolve_dynamic_filter_value(value, current_user)
                if expected is None:
                    query = query.filter(models.Task.id == -1)
                elif operator == "eq":
                    query = query.filter(task_assigned_to(expected))
                else:
                    query = query.filter(~task_assigned_to(expected))
        elif field == "has_parent_task" and operator in {"eq", "neq"}:
            expected = value if isinstance(value, bool) else str(value).lower() == "true"
            condition = models.Task.parent_task_id.is_not(None) if expected else models.Task.parent_task_id.is_(None)
            query = query.filter(condition if operator == "eq" else ~condition)

    return query


def _sort_value(task: models.Task, field: str, custom_fields: dict):
    if field == "due_date":
        try:
            day = normalize_due_date(task.due_date)
            if day is None:
                return None
            instant = deadline_datetime(task.due_date, task.due_time, task.due_timezone)
            return (day, instant is not None, instant or datetime.min.replace(tzinfo=UTC))
        except ValueError:
            return None
    if field in {"created_at", "updated_at"}:
        value = getattr(task, field)
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value
    if field == "task_type_id":
        return task.task_type.name.casefold() if task.task_type else None
    if field == "assignee_user_id":
        names = sorted((user.display_name or user.email).casefold() for user in task_assignees(task))
        return tuple(names) if names else None
    value = _task_field_value(task, field)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if field.startswith("custom:"):
        field_def = custom_fields.get(int(field.split(":", 1)[1]))
        if field_def is None:
            return None  # A deleted field must not prevent an existing filter from loading.
        if field_def.field_type == "number":
            try:
                number = Decimal(value)
                return number if number.is_finite() else None
            except (InvalidOperation, ValueError):
                return None
        if field_def.field_type == "date":
            try:
                return normalize_due_date(value)
            except ValueError:
                return None
        if field_def.field_type == "dropdown":
            try:
                options = json.loads(field_def.options or "[]")
            except (TypeError, ValueError):
                return None
            if not isinstance(options, list):
                return None
            labels = [
                option.get("label", option.get("value")) if isinstance(option, dict) else option
                for option in options
            ]
            return labels.index(value) if value in labels else None
    return value.strip().casefold() if isinstance(value, str) else value


def _sort_log_tasks(tasks: list, sort_rules: list, db: Session) -> list:
    if not sort_rules:
        return tasks
    field_ids = [
        int(rule["field"].split(":", 1)[1])
        for rule in sort_rules if rule["field"].startswith("custom:")
    ]
    custom_fields = {
        field.id: field
        for field in db.query(models.CustomFieldDef).filter(models.CustomFieldDef.id.in_(field_ids)).all()
    } if field_ids else {}
    # Stable sorts preserve the existing newest-first order when all keys tie.
    for rule in reversed(sort_rules):
        present, missing = [], []
        for task in tasks:
            value = _sort_value(task, rule["field"], custom_fields)
            if value is None:
                missing.append(task)
            else:
                present.append((value, task))
        present.sort(key=lambda item: item[0], reverse=rule["direction"] == "desc")
        tasks = [task for _, task in present] + missing
    return tasks


def get_stage_tasks(stage: models.Stage, db: Session, current_user: Optional[models.User] = None):
    if not stage.is_log:
        return (
            db.query(models.Task)
            .options(*_task_detail_load_options())
            .filter(models.Task.stage_id == stage.id)
            .order_by(models.Task.position)
            .all()
        )

    started = time.perf_counter()
    definition = parse_filter_definition(stage.saved_filter.definition) if stage.saved_filter else default_filter_definition()
    source_board_ids = definition.get("source_board_ids") or [stage.board_id]
    if current_user is not None:
        accessible_board_ids = {board.id for board in get_accessible_boards(current_user, db)}
        source_board_ids = [board_id for board_id in source_board_ids if board_id in accessible_board_ids]
    if not source_board_ids:
        return []
    query = (
        db.query(models.Task)
        .options(*_task_detail_load_options())
        .join(models.Stage, models.Task.stage_id == models.Stage.id)
        .filter(
            models.Stage.board_id.in_(source_board_ids),
            models.Stage.id != stage.id,
            or_(models.Stage.is_log == False, models.Stage.is_log.is_(None)),
        )
        .order_by(models.Task.created_at.desc(), models.Task.id.desc())
    )
    query = _prefilter_log_query(query, definition, current_user)
    tasks = [task for task in query.all() if _task_matches_filter(task, definition, current_user)]
    tasks = _sort_log_tasks(tasks, definition["sort_rules"], db)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms >= SLOW_LOG_STAGE_MS:
        logger.warning("slow_log_stage %.1fms stage_id=%s source_boards=%s matched=%s", elapsed_ms, stage.id, source_board_ids, len(tasks))
    return tasks
