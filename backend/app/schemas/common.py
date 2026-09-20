import uuid
from typing import Generic, TypeVar

from fastapi import Request
from pydantic import BaseModel

T = TypeVar("T")


class RoleReference(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class SuccessResponse(BaseModel, Generic[T]):
    data: T
    message: str = "OK"
    request_id: str


def success(request: Request, data: T, message: str = "OK") -> dict:
    return {"data": data, "message": message, "request_id": request.state.request_id}
