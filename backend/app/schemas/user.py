import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, StringConstraints

from app.schemas.common import RoleReference


class UserCreate(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64)]
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    password: str
    email: EmailStr | None = None
    phone: str | None = None
    status: Literal["active", "disabled"] = "active"
    role_ids: list[uuid.UUID] = []


class UserUpdate(BaseModel):
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    email: EmailStr | None = None
    phone: str | None = None
    role_ids: list[uuid.UUID] | None = None


class UserStatusUpdate(BaseModel):
    status: Literal["active", "disabled"]


class PasswordReset(BaseModel):
    password: str


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    email: str | None = None
    phone: str | None = None


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    phone: str | None
    status: str
    is_deleted: bool
    is_builtin: bool
    roles: list[RoleReference]
    created_at: str | None
    updated_at: str | None

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    items: list[UserResponse]
    page: int
    page_size: int
    total: int
