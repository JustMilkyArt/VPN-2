from pydantic import BaseModel
from typing import Optional


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AdminUserCreate(BaseModel):
    username: str
    password: str


class AdminUserRead(BaseModel):
    id: int
    username: str
    is_active: bool

    class Config:
        from_attributes = True
