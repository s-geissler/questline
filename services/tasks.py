"""Business logic for task and checklist operations."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models


def collect_descendant_task_ids(root_task_ids: list[int], db: Session) -> set[int]:
    all_ids = set(root_task_ids)
    frontier = set(root_task_ids)

    while frontier:
        child_ids = {
            task_id
            for (task_id,) in db.query(models.ChecklistItem.spawned_task_id)
            .filter(
                models.ChecklistItem.task_id.in_(frontier),
                models.ChecklistItem.spawned_task_id.is_not(None),
            )
            .all()
        }
        child_ids -= all_ids
        if not child_ids:
            break
        all_ids.update(child_ids)
        frontier = child_ids

    return all_ids


def _create_checklist_item_internal(task: models.Task, title: str, db: Session) -> models.ChecklistItem:
    item = models.ChecklistItem(task_id=task.id, title=title)
    db.add(item)
    db.flush()

    if task.task_type and task.task_type.is_epic:
        target_stage_id = task.task_type.spawn_stage_id or task.stage_id
        target_stage = db.query(models.Stage).filter(models.Stage.id == target_stage_id).first()
        if target_stage and target_stage.is_log:
            raise HTTPException(status_code=400, detail="Cannot spawn tasks into a log stage")
        new_pos = db.query(models.Task).filter(models.Task.stage_id == target_stage_id).count()
        spawned = models.Task(
            title=title,
            stage_id=target_stage_id,
            position=new_pos,
            color=task.task_type.color,
            parent_task_id=task.id,
        )
        db.add(spawned)
        db.flush()
        item.spawned_task_id = spawned.id
    return item


def _sync_spawned_task_title_from_checklist_item(item: models.ChecklistItem, db: Session):
    if not item.spawned_task_id:
        return
    spawned = db.query(models.Task).filter(models.Task.id == item.spawned_task_id).first()
    if spawned:
        spawned.title = item.title


def _sync_checklist_item_title_from_spawned_task(task: models.Task, db: Session):
    linked_item = (
        db.query(models.ChecklistItem)
        .filter(models.ChecklistItem.spawned_task_id == task.id)
        .first()
    )
    if linked_item:
        linked_item.title = task.title


def delete_tasks_by_ids(task_ids: set[int], db: Session):
    if not task_ids:
        return 0

    linked_items = (
        db.query(models.ChecklistItem)
        .filter(models.ChecklistItem.spawned_task_id.in_(task_ids))
        .all()
    )
    for item in linked_items:
        db.delete(item)

    tasks = db.query(models.Task).filter(models.Task.id.in_(task_ids)).all()
    for task in tasks:
        db.delete(task)
    db.commit()
    return len(tasks)
