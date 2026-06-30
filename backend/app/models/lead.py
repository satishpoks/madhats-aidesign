from __future__ import annotations

from pydantic import BaseModel, EmailStr


class CreateLeadRequest(BaseModel):
    session_id: str
    name: str
    email: EmailStr
    phone: str | None = None


class LeadResponse(BaseModel):
    lead_id: str


class VerifySendRequest(BaseModel):
    lead_id: str
