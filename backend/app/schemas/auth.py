import uuid

from pydantic import BaseModel

from app.schemas.common import RoleReference


class LoginRequest(BaseModel):
    username: str
    password: str


class CurrentUserResponse(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    roles: list[RoleReference]
    permissions: list[str]
    menu_permissions: list[str]
    assignable_roles: list[RoleReference] | None = None
    sync_feishu_enabled: bool = False
