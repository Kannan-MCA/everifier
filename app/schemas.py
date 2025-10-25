from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum

class EmailValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    CATCH_ALL = "catch_all"
    DISPOSABLE = "disposable"
    BLOCKLISTED = "blocklisted"
    USER_NOT_FOUND = "user_not_found"
    UNKNOWN = "unknown"

class EmailValidationRequest(BaseModel):
    email: EmailStr

class BulkEmailValidationRequest(BaseModel):
    emails: List[EmailStr] = Field(..., max_items=1000)

class EmailValidationResponse(BaseModel):
    email: str
    status: EmailValidationStatus
    reason: str
    mx_records: Optional[List[str]] = None
    smtp_response: Optional[str] = None
    validated_at: datetime

    class Config:
        from_attributes = True

class BulkEmailValidationResponse(BaseModel):
    total: int
    results: List[EmailValidationResponse]
