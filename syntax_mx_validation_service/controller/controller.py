import asyncio
import csv
import io
import re
from typing import List, Tuple
from models.models import ESPDomain

import aiodns
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import EmailValidationTransaction, EmailSyntaxMXValidation
from dependencies import get_async_session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone

router = APIRouter()

EMAIL_REGEX = re.compile(
    r"^(?P<local>[-!#$%&'*+/=?^_`{|}~0-9A-Za-z]+(\.[-!#$%&'*+/=?^_`{|}~0-9A-Za-z]+)*|\"([ !#-\[\]-~]|(\\[\t -~]))+\")@(?P<domain>[A-Za-z0-9]+([-.][A-Za-z0-9]+)*\.[A-Za-z]{2,})$"
)

def validate_syntax(email: str) -> bool:
    return bool(EMAIL_REGEX.fullmatch(email))

async def check_mx_records(domain: str) -> List[Tuple[int, str]]:
    resolver = aiodns.DNSResolver()
    try:
        response = await resolver.query(domain, 'MX')
        mx_records = sorted([(r.priority, r.host) for r in response], key=lambda x: x[0])
        return mx_records
    except Exception as e:
        print(f"[MX Lookup Error] Domain: {domain} - {e}")
        return []

class ValidateRequest(BaseModel):
    emails: List[EmailStr]
    transaction_id: str
    description: str

class ValidateResult(BaseModel):
    email: str
    syntax_valid: bool
    mx_records: List[dict]
    is_smtp_checked: bool
    is_syntax_mx_valid: bool
    is_level1_checked: bool
    is_level2_checked: bool
    is_catchall_checked: bool
    esp_category: str
    transaction_id: str

class ValidateResponse(BaseModel):
    transaction_id: str
    results: List[ValidateResult]

async def validate_one(email: str, transaction_id: str, session: AsyncSession) -> ValidateResult:
    email_lower = email.lower()
    syntax_valid = validate_syntax(email_lower)
    mx_records: List[Tuple[int, str]] = []
    is_syntax_mx_valid = False

    if syntax_valid:
        domain = email_lower.split("@")[-1]
        esp_category = await get_or_create_esp(domain, session)
        mx_records = await check_mx_records(domain)
        if mx_records:
            is_syntax_mx_valid = True

    mx_str = ", ".join(f"{pref}:{host}" for pref, host in mx_records) if mx_records else None

    stmt = select(EmailSyntaxMXValidation).where(
        EmailSyntaxMXValidation.email == email_lower,
        EmailSyntaxMXValidation.transaction_id == transaction_id,
    )
    result = await session.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        record = EmailSyntaxMXValidation(
            email=email_lower,
            transaction_id=transaction_id,
            syntax_valid=syntax_valid,
            mx_records=mx_str,
            is_smtp_checked=False,
            smtp_valid=None,
            smtp_response=None,
            smtp_status=None,
            is_syntax_mx_valid=is_syntax_mx_valid,
            is_level1_checked=False,
            is_level2_checked=False,
            is_catchall_checked=False,
            validated_at=None,
            smtp_validated_at=None,
        )
        session.add(record)
    else:
        record.syntax_valid = syntax_valid
        record.mx_records = mx_str
        record.is_syntax_mx_valid = is_syntax_mx_valid
        # Reset downstream flags if syntax or MX changed
        if not is_syntax_mx_valid:
            record.is_level1_checked = False
            record.is_level2_checked = False
            record.is_catchall_checked = False

    await session.commit()

    return ValidateResult(
        email=email_lower,
        syntax_valid=syntax_valid,
        mx_records=[{"preference": pref, "host": host} for pref, host in mx_records],
        is_smtp_checked=record.is_smtp_checked,
        is_syntax_mx_valid=record.is_syntax_mx_valid,
        is_level1_checked=record.is_level1_checked,
        is_level2_checked=record.is_level2_checked,
        is_catchall_checked=record.is_catchall_checked,
        esp_category=record.esp_category,
        transaction_id=transaction_id,
    )

@router.post("/validate", response_model=ValidateResponse)
async def validate_emails(
    request: ValidateRequest,
    session: AsyncSession = Depends(get_async_session)
):
    seen = set()
    unique_emails = []
    for email in request.emails:
        email_lower = email.lower()
        if email_lower not in seen:
            seen.add(email_lower)
            unique_emails.append(email)

    existing = await session.get(EmailValidationTransaction, request.transaction_id)
    if not existing:
        session.add(EmailValidationTransaction(id=request.transaction_id, description=request.description))
        await session.commit()

    results = await asyncio.gather(*(validate_one(email, request.transaction_id, session) for email in unique_emails))
    return ValidateResponse(transaction_id=request.transaction_id, results=results)

@router.post("/upload_csv", response_model=ValidateResponse)
async def upload_csv_emails(
    transaction_id: str,
    description: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_async_session)
):
    existing = await session.get(EmailValidationTransaction, transaction_id)
    if not existing:
        session.add(EmailValidationTransaction(id=transaction_id, description=description))
        await session.commit()

    content = await file.read()
    try:
        decoded = content.decode("utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file encoding. UTF-8 required.")

    reader = csv.reader(io.StringIO(decoded))
    seen = set()
    emails = []
    for row in reader:
        if row:
            email_candidate = row[0].strip()
            email_lower = email_candidate.lower()
            if validate_syntax(email_candidate) and email_lower not in seen:
                seen.add(email_lower)
                emails.append(email_candidate)

    if not emails:
        raise HTTPException(status_code=400, detail="No valid emails found in CSV file.")

    results = await asyncio.gather(*(validate_one(email, transaction_id, session) for email in emails))
    return ValidateResponse(transaction_id=transaction_id, results=results)

@router.get("/results/{transaction_id}", response_model=ValidateResponse)
async def get_results(
    transaction_id: str,
    session: AsyncSession = Depends(get_async_session)
):
    stmt = select(EmailSyntaxMXValidation).where(EmailSyntaxMXValidation.transaction_id == transaction_id)
    result = await session.execute(stmt)
    records = result.scalars().all()

    results = []
    for rec in records:
        mx_list = []
        if rec.mx_records:
            for item in rec.mx_records.split(","):
                if ":" in item:
                    pref, host = item.split(":", 1)
                    try:
                        mx_list.append({"preference": int(pref.strip()), "host": host.strip()})
                    except ValueError:
                        pass
        results.append(ValidateResult(
            email=rec.email,
            syntax_valid=rec.syntax_valid,
            mx_records=mx_list,
            is_smtp_checked=rec.is_smtp_checked,
            is_syntax_mx_valid=rec.is_syntax_mx_valid,
            is_level1_checked=rec.is_level1_checked,
            is_level2_checked=rec.is_level2_checked,
            is_catchall_checked=rec.is_catchall_checked,
            transaction_id=rec.transaction_id
        ))
    return ValidateResponse(transaction_id=transaction_id, results=results)
async def get_or_create_esp(domain: str, session: AsyncSession) -> str:
    domain_lower = domain.lower()
    now = datetime.now(timezone.utc)
    
    # Try to find existing record
    stmt = select(ESPDomain).where(ESPDomain.domain == domain_lower)
    result = await session.execute(stmt)
    record = result.scalar_one_or_none()
    
    if record:
        # Update last_seen_at timestamp on existing record
        record.last_seen_at = now
        await session.commit()
        return record.esp_name

    # If not found, create new, ensuring unique domain
    new_esp = ESPDomain(
        domain=domain_lower,
        esp_name="Unknown",  # Default ESP name, can be updated later
        last_seen_at=now,
        is_active=True,
    )

    session.add(new_esp)
    try:
        await session.commit()
    except IntegrityError:
        # In rare race condition that domain was inserted concurrently, roll back and retry fetch
        await session.rollback()
        result = await session.execute(stmt)
        record_retry = result.scalar_one_or_none()
        if record_retry:
            return record_retry.esp_name
        else:
            raise  # escalate exception if unexpected

    return new_esp.esp_name