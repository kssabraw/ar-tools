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
