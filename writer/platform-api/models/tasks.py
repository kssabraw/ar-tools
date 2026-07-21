"""Pydantic schemas for the native task manager (Phase 0 endpoints).

Config (statuses / categories / library checklists) + monthly generation +
the native workload read. Task CRUD schemas land with the Phase 1 router.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TaskStatusItem(BaseModel):
    key: str
    label: str
    color: Optional[str] = None
    category: str = "in_progress"  # not_started | in_progress | blocked | done
    is_initial: bool = False
    is_done: bool = False
    sort_order: int = 0
    active: bool = True


class TaskStatusReplaceRequest(BaseModel):
    items: list[TaskStatusItem] = Field(default_factory=list)


class TaskCategoryItem(BaseModel):
    key: str
    label: str
    color: Optional[str] = None
    sort_order: int = 0
    active: bool = True


class TaskCategoryReplaceRequest(BaseModel):
    items: list[TaskCategoryItem] = Field(default_factory=list)


class LibraryChecklist(BaseModel):
    library_name: str
    subtasks: list[str] = Field(default_factory=list)


class TaskCreateRequest(BaseModel):
    name: str
    client_id: Optional[str] = None
    section_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    description: Optional[str] = None
    assignee_gid: Optional[str] = None
    assignee_name: Optional[str] = None
    status_key: Optional[str] = None
    category: Optional[str] = None
    due_date: Optional[str] = None
    start_date: Optional[str] = None
    est_hours: Optional[float] = None
    sort_order: int = 0


class TaskUpdateRequest(BaseModel):
    """Partial update — only provided fields change (None clears a nullable
    field only when explicitly present in the payload)."""

    name: Optional[str] = None
    description: Optional[str] = None
    section_id: Optional[str] = None
    assignee_gid: Optional[str] = None
    assignee_name: Optional[str] = None
    status_key: Optional[str] = None
    category: Optional[str] = None
    due_date: Optional[str] = None
    start_date: Optional[str] = None
    est_hours: Optional[float] = None
    sort_order: Optional[int] = None
    # Client-facing note (Weekly Pulse) — NOT the internal description.
    client_note: Optional[str] = None
    # Explicit QA rubric override (qa_signals RUBRIC_*); "" / null = auto-detect
    # from the task name. Validated against qa_signals.RUBRIC_KEYS at the router.
    qa_rubric: Optional[str] = None
    # Website-page sub-type for QA's structural design-fit reference selection
    # (service / local_landing / location); "" / null = auto (priority order).
    qa_page_type: Optional[str] = None


class TaskSectionCreateRequest(BaseModel):
    name: str
    kind: str = "custom"  # month | backlog | custom
    period_month: Optional[str] = None


class TaskSectionUpdateRequest(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None


class TaskReorderRequest(BaseModel):
    ordered_ids: list[str] = Field(default_factory=list)


class TaskCommentRequest(BaseModel):
    body: str


class TaskViewRequest(BaseModel):
    name: str
    config: dict  # {view, group_by?, filters:{q, assignee, category, section, preset}, scope?}
    shared: bool = False


class TaskDuplicateRequest(BaseModel):
    with_subtasks: bool = True


class TaskGenerateMonthRequest(BaseModel):
    # "YYYY-MM" or "YYYY-MM-DD"; omitted → the current month.
    month: Optional[str] = None


class TaskGenerateMonthResponse(BaseModel):
    status: str
    section: str
    created: int = 0
    existing: int = 0
    reason: Optional[str] = None
    errors: list[str] = Field(default_factory=list)
