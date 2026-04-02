from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text, DateTime, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class Board(Base):
    __tablename__ = "boards"
    __table_args__ = (
        Index("ix_boards_position", "position"),
        Index("ix_boards_owner_user_id", "owner_user_id"),
    )
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    color = Column(String, nullable=True)
    position = Column(Integer, default=0)
    stages = relationship(
        "Stage",
        back_populates="board",
        cascade="all, delete-orphan",
        foreign_keys="Stage.board_id",
    )
    task_types = relationship(
        "TaskType",
        back_populates="board",
        cascade="all, delete-orphan",
    )
    automations = relationship(
        "Automation",
        back_populates="board",
        cascade="all, delete-orphan",
    )
    saved_filters = relationship(
        "SavedFilter",
        back_populates="board",
        cascade="all, delete-orphan",
    )
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    memberships = relationship(
        "BoardMembership",
        back_populates="board",
        cascade="all, delete-orphan",
    )


class Stage(Base):
    __tablename__ = "lists"
    __table_args__ = (
        Index("ix_lists_board_position", "board_id", "position"),
        Index("ix_lists_filter_id", "filter_id"),
    )
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    position = Column(Integer, default=0)
    is_log = Column(Boolean, default=False)
    filter_id = Column(Integer, ForeignKey("saved_filters.id", ondelete="SET NULL"), nullable=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=True)
    board = relationship("Board", back_populates="stages", foreign_keys=[board_id])
    saved_filter = relationship("SavedFilter", foreign_keys=[filter_id])
    tasks = relationship(
        "Task",
        back_populates="stage",
        cascade="all, delete-orphan",
        foreign_keys="Task.stage_id",
        order_by="Task.position",
    )


class SavedFilter(Base):
    __tablename__ = "saved_filters"
    __table_args__ = (
        Index("ix_saved_filters_board_id", "board_id"),
    )
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False)
    name = Column(String, nullable=False)
    definition = Column(Text, nullable=False)
    board = relationship("Board", back_populates="saved_filters")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    sessions = relationship(
        "UserSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    board_memberships = relationship(
        "BoardMembership",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_token_hash", "token_hash"),
        Index("ix_user_sessions_user_id", "user_id"),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, server_default=func.now())
    user = relationship("User", back_populates="sessions")


class BoardMembership(Base):
    __tablename__ = "board_memberships"
    __table_args__ = (
        Index("ix_board_memberships_board_user", "board_id", "user_id"),
        Index("ix_board_memberships_user_id", "user_id"),
        Index("ix_board_memberships_board_role", "board_id", "role"),
    )
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String, nullable=False, default="owner")
    created_at = Column(DateTime, server_default=func.now())
    board = relationship("Board", back_populates="memberships")
    user = relationship("User", back_populates="board_memberships")


class TaskType(Base):
    __tablename__ = "task_types"
    __table_args__ = (
        Index("ix_task_types_board_id", "board_id"),
        Index("ix_task_types_spawn_stage_id", "spawn_list_id"),
    )
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    color = Column(String, nullable=True)
    is_epic = Column(Boolean, default=False)
    show_description_on_card = Column(Boolean, default=False)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=True)
    spawn_stage_id = Column("spawn_list_id", Integer, ForeignKey("lists.id", ondelete="SET NULL"), nullable=True)
    board = relationship("Board", back_populates="task_types")
    spawn_stage = relationship("Stage", foreign_keys=[spawn_stage_id])
    custom_fields = relationship(
        "CustomFieldDef", back_populates="task_type", cascade="all, delete-orphan"
    )
    tasks = relationship("Task", back_populates="task_type")


class CustomFieldDef(Base):
    __tablename__ = "custom_field_defs"
    __table_args__ = (
        Index("ix_custom_field_defs_task_type_id", "task_type_id"),
    )
    id = Column(Integer, primary_key=True)
    task_type_id = Column(Integer, ForeignKey("task_types.id"), nullable=False)
    name = Column(String, nullable=False)
    field_type = Column(String, default="text")  # text, number, date, dropdown
    options = Column(Text, nullable=True)  # JSON array of strings, used for dropdown
    color = Column(String, nullable=True)
    show_on_card = Column(Boolean, default=False)
    task_type = relationship("TaskType", back_populates="custom_fields")
    values = relationship(
        "CustomFieldValue", back_populates="field_def", cascade="all, delete-orphan"
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_stage_position", "list_id", "position"),
        Index("ix_tasks_task_type_id", "task_type_id"),
        Index("ix_tasks_parent_task_id", "parent_task_id"),
        Index("ix_tasks_done", "done"),
        Index("ix_tasks_due_date", "due_date"),
        Index("ix_tasks_created_at", "created_at"),
    )
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    due_date = Column(String, nullable=True)
    parent_task_id = Column(Integer, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    show_description_on_card = Column(Boolean, nullable=True)
    stage_id = Column("list_id", Integer, ForeignKey("lists.id"), nullable=False)
    task_type_id = Column(Integer, ForeignKey("task_types.id"), nullable=True)
    color = Column(String, nullable=True)
    position = Column(Integer, default=0)
    done = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

    stage = relationship("Stage", back_populates="tasks", foreign_keys=[stage_id])
    task_type = relationship("TaskType", back_populates="tasks")
    parent_task = relationship("Task", foreign_keys=[parent_task_id], remote_side=[id])
    custom_field_values = relationship(
        "CustomFieldValue", back_populates="task", cascade="all, delete-orphan"
    )
    checklist_items = relationship(
        "ChecklistItem",
        back_populates="task",
        cascade="all, delete-orphan",
        foreign_keys="ChecklistItem.task_id",
    )


class CustomFieldValue(Base):
    __tablename__ = "custom_field_values"
    __table_args__ = (
        Index("ix_custom_field_values_task_field", "task_id", "field_def_id"),
        Index("ix_custom_field_values_field_def_id", "field_def_id"),
    )
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    field_def_id = Column(Integer, ForeignKey("custom_field_defs.id"), nullable=False)
    value = Column(Text, default="")
    task = relationship("Task", back_populates="custom_field_values")
    field_def = relationship("CustomFieldDef", back_populates="values")


class ChecklistItem(Base):
    __tablename__ = "checklist_items"
    __table_args__ = (
        Index("ix_checklist_items_task_id", "task_id"),
        Index("ix_checklist_items_spawned_task_id", "spawned_task_id"),
    )
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    title = Column(String, nullable=False)
    done = Column(Boolean, default=False)
    spawned_task_id = Column(
        Integer, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    task = relationship("Task", back_populates="checklist_items", foreign_keys=[task_id])
    spawned_task = relationship("Task", foreign_keys=[spawned_task_id])


class Automation(Base):
    __tablename__ = "automations"
    __table_args__ = (
        Index("ix_automations_board_enabled_trigger", "board_id", "enabled", "trigger_type"),
        Index("ix_automations_trigger_stage_id", "trigger_list_id"),
        Index("ix_automations_action_stage_id", "action_list_id"),
    )
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=True)
    # Trigger
    trigger_type = Column(String, nullable=False)  # "task_done"
    trigger_stage_id = Column("trigger_list_id", Integer, ForeignKey("lists.id", ondelete="SET NULL"), nullable=True)
    # Action
    action_type = Column(String, nullable=False)  # "move_to_stage"
    action_stage_id = Column("action_list_id", Integer, ForeignKey("lists.id", ondelete="SET NULL"), nullable=True)
    action_task_type_id = Column(Integer, ForeignKey("task_types.id", ondelete="SET NULL"), nullable=True)
    action_color = Column(String, nullable=True)
    action_days_offset = Column(Integer, nullable=True)
    enabled = Column(Boolean, default=True)

    board = relationship("Board", back_populates="automations")
    trigger_stage = relationship("Stage", foreign_keys=[trigger_stage_id])
    action_stage = relationship("Stage", foreign_keys=[action_stage_id])
    action_task_type = relationship("TaskType", foreign_keys=[action_task_type_id])
