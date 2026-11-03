"""Validate Trello board exports and import their base objectives."""
from __future__ import annotations

import html
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlsplit

from sqlalchemy.orm import Session

import models


MAX_TRELLO_IMPORT_SIZE = 10 * 1024 * 1024
MAX_TRELLO_IMPORT_REQUEST_SIZE = MAX_TRELLO_IMPORT_SIZE + 64 * 1024


@dataclass(frozen=True)
class ChecklistDraft:
    title: str
    done: bool


@dataclass(frozen=True)
class TaskDraft:
    title: str
    description: str
    due_date: str | None
    done: bool
    checklist: tuple[ChecklistDraft, ...]


@dataclass(frozen=True)
class StageDraft:
    name: str
    tasks: tuple[TaskDraft, ...]


@dataclass(frozen=True)
class TrelloDraft:
    name: str
    stages: tuple[StageDraft, ...]
    skipped_archived_card_count: int

    def summary(self) -> dict:
        return {
            "name": self.name,
            "stage_count": len(self.stages),
            "task_count": sum(len(stage.tasks) for stage in self.stages),
            "checklist_item_count": sum(
                len(task.checklist) for stage in self.stages for task in stage.tasks
            ),
            "skipped_archived_card_count": self.skipped_archived_card_count,
        }


def _text(value, label: str, limit: int | None = None, *, required=False) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{label} must be {'a nonempty string' if required else 'text'}.")
    if limit is not None and len(value) > limit:
        raise ValueError(f"{label} exceeds the {limit}-character limit.")
    return value


def _objects(value, label: str) -> list[dict]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be an array of objects.")
    return value


def _ids(value, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array of IDs.")
    return [_text(item, label, required=True) for item in value]


def _boolean(value, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be true or false.")
    return value


def _position(item: dict) -> int | float:
    value = item.get("pos", 0)
    try:
        valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("Trello positions must be finite numbers.")
    return value


def _markdown_text(value: str) -> str:
    # Keep exported names on one line and prevent them from introducing markup.
    value = html.escape(" ".join(value.split()), quote=False)
    return re.sub(r"([\\`*_\[\]~])", r"\\\1", value)


def _attachment_note(attachment: dict) -> str:
    name = _text(attachment.get("name") or attachment.get("fileName") or "Attachment", "Attachment name")
    label = _markdown_text(name)
    url = _text(attachment.get("url") or "", "Attachment URL").strip()
    try:
        parsed = urlsplit(url)
        safe = parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        safe = False
    if not safe or any(ord(char) < 32 for char in url):
        return f"- {label} (link unavailable)"
    # Encode delimiters that could end a Markdown link or introduce HTML.
    url = quote(url, safe=":/?#@!$&'*+,;=%~.-_")
    return f"- [{label}]({url})"


def _description(card: dict, members: dict[str, dict]) -> str:
    description = _text(card.get("desc") or "", "Objective description")
    member_ids = _ids(card.get("idMembers", []), "Card assignees")
    attachments = _objects(card.get("attachments", []), "Card attachments")
    notes = []
    if member_ids:
        names = []
        for member_id in member_ids:
            member = members.get(member_id, {})
            name = _text(member.get("fullName") or "", "Assignee name")
            username = _text(member.get("username") or "", "Assignee username")
            if name and username:
                display = f"{name} (@{username})"
            else:
                display = name or (f"@{username}" if username else f"Unknown Trello member ({member_id})")
            names.append(_markdown_text(display))
        notes.append("**Assigned in Trello:** " + ", ".join(names))
    if attachments:
        notes.append("**Attachments:**\n" + "\n".join(_attachment_note(item) for item in sorted(attachments, key=_position)))
    if notes:
        description += ("\n\n---\n\n" if description else "") + "### Trello import notes\n\n" + "\n\n".join(notes)
    return _text(description, "Objective description including import notes", 10_000)


def _due_date(value) -> str | None:
    if value is None:
        return None
    _text(value, "Objective due date", required=True)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError as error:
        raise ValueError("Objective due date must be an ISO date or timestamp.") from error


def _invalid_constant(value):
    raise ValueError(f"Invalid JSON number: {value}")


def parse_trello_export(content: bytes) -> TrelloDraft:
    """Validate everything before any existing Hub content can be removed."""
    try:
        data = json.loads(content.decode("utf-8-sig"), parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("This file is not valid UTF-8 JSON.") from error
    if not isinstance(data, dict) or not {"name", "lists", "cards"}.issubset(data):
        raise ValueError("Choose a Trello board JSON export containing name, lists, and cards.")

    name = _text(data["name"], "Hub name", 120, required=True)
    lists = _objects(data["lists"], "Trello lists")
    stage_names = {}
    for stage in lists:
        stage_id = _text(stage.get("id"), "List ID", required=True)
        if stage_id in stage_names:
            raise ValueError("The export contains duplicate list IDs.")
        stage_names[stage_id] = _text(stage.get("name"), "Stage name", 120, required=True)

    members = {}
    for member in _objects(data.get("members", []), "Trello members"):
        members[_text(member.get("id"), "Member ID", required=True)] = member

    cards = {}
    skipped = 0
    for card in _objects(data["cards"], "Trello cards"):
        if _boolean(card.get("closed", False), "Card archive status"):
            skipped += 1
            continue
        card_id = _text(card.get("id"), "Card ID", required=True)
        if card_id in cards:
            raise ValueError("The export contains duplicate card IDs.")
        stage_id = _text(card.get("idList"), "Card list ID", required=True)
        if stage_id not in stage_names:
            raise ValueError("An unarchived card references a list missing from the export.")
        cards[card_id] = card

    checklists = {}
    groups_by_card = {card_id: [] for card_id in cards}
    for checklist in _objects(data.get("checklists", []), "Trello checklists"):
        card_id = _text(checklist.get("idCard"), "Checklist card ID", required=True)
        if card_id not in cards:
            continue
        checklist_id = _text(checklist.get("id"), "Checklist ID", required=True)
        if checklist_id in checklists:
            raise ValueError("The export contains duplicate checklist IDs.")
        checklists[checklist_id] = checklist
        groups_by_card[card_id].append(checklist)

    for card_id, card in cards.items():
        for checklist_id in _ids(card.get("idChecklists", []), "Card checklist IDs"):
            if checklist_id not in checklists or checklists[checklist_id]["idCard"] != card_id:
                raise ValueError("A card references a checklist missing from the export or belonging to another card.")

    tasks_by_stage = {stage_id: [] for stage_id in stage_names}
    for card_id, card in sorted(cards.items(), key=lambda entry: _position(entry[1])):
        groups = sorted(groups_by_card[card_id], key=_position)
        items = []
        for group in groups:
            group_name = _text(group.get("name", "Checklist"), "Checklist name", required=True)
            for item in sorted(_objects(group.get("checkItems", []), "Checklist items"), key=_position):
                title = _text(item.get("name"), "Checklist item title", required=True)
                if len(groups) > 1:
                    title = f"{group_name}: {title}"
                _text(title, "Checklist item title", 200)
                state = item.get("state", "incomplete")
                if state not in ("complete", "incomplete"):
                    raise ValueError("Checklist item state must be complete or incomplete.")
                items.append(ChecklistDraft(title=title, done=state == "complete"))
        tasks_by_stage[card["idList"]].append(TaskDraft(
            title=_text(card.get("name"), "Objective title", 200, required=True),
            description=_description(card, members),
            due_date=_due_date(card.get("due")),
            done=_boolean(card.get("dueComplete", False), "Card completion status"),
            checklist=tuple(items),
        ))

    return TrelloDraft(
        name=name,
        stages=tuple(StageDraft(stage_names[stage["id"]], tuple(tasks_by_stage[stage["id"]])) for stage in sorted(lists, key=_position)),
        skipped_archived_card_count=skipped,
    )


def import_trello_content(draft: TrelloDraft, board: models.Board, db: Session):
    """Replace content without committing or running ordinary creation automations."""
    old_stages = list(board.stages)
    for automation in list(board.automations):
        db.delete(automation)

    # Allocate new IDs before deleting the old rows, so links to old Objectives
    # and local Stage viewing state cannot point at the newly imported content.
    for position, stage_draft in enumerate(draft.stages):
        stage = models.Stage(board=board, name=stage_draft.name, row=0, position=position, is_log=False)
        db.add(stage)
        for task_position, task_draft in enumerate(stage_draft.tasks):
            task = models.Task(
                stage=stage,
                title=task_draft.title,
                description=task_draft.description,
                due_date=task_draft.due_date,
                done=task_draft.done,
                position=task_position,
            )
            db.add(task)
            for item in task_draft.checklist:
                db.add(models.ChecklistItem(task=task, title=item.title, done=item.done))
    db.flush()
    for stage in old_stages:
        db.delete(stage)
    db.flush()
