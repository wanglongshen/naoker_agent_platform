import uuid
from typing import Literal

from pydantic import BaseModel


class PermissionSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    module: str
    description: str | None

    model_config = {"from_attributes": True}


class RoleSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    status: Literal["active", "disabled"]
    is_system: bool
    permission_count: int
    parent_role_id: uuid.UUID | None
    parent_role_code: str | None = None
    parent_role_name: str | None = None

    model_config = {"from_attributes": True}


class RoleDetail(RoleSummary):
    permissions: list[PermissionSummary]
    assigned_user_count: int


class RoleCreate(BaseModel):
    code: str
    name: str
    description: str | None = None
    parent_role_id: uuid.UUID | None = None
    permission_ids: list[uuid.UUID] = []


class RoleUpdate(BaseModel):
    name: str
    description: str | None = None
    parent_role_id: uuid.UUID | None = None
    permission_ids: list[uuid.UUID] | None = None


class RoleStatusUpdate(BaseModel):
    status: Literal["active", "disabled"]
