from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict
from datetime import datetime
from enum import Enum

class EmailValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    USER_NOT_FOUND = "user_not_found"
    CATCH_ALL = "catch_all"
    DISPOSABLE = "disposable"
    ROLE_BASED = "role_based"
    BLOCKLISTED = "blocklisted"
    UNKNOWN = "unknown"

class EmailValidationRequest(BaseModel):
    email: EmailStr

class EmailValidationResponse(BaseModel):
    email: str
    status: EmailValidationStatus
    reason: str
    mx_records: Optional[List[str]] = None
    smtp_response: Optional[str] = None
    validated_at: datetime
    catchall_reason: Optional[str] = None

    class Config:
        from_attributes = True

class BulkEmailValidationRequest(BaseModel):
    emails: List[EmailStr]

class BulkEmailValidationResponse(BaseModel):
    total: int
    successful: int = 0
    failed: int = 0
    cached: int = 0
    results: List[EmailValidationResponse]
    errors: Optional[List[Dict]] = None
    processing_time_ms: Optional[float] = None
