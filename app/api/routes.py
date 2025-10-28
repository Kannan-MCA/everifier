from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, status, Query
from sqlalchemy.orm import Session
from collections import defaultdict
import pandas as pd
import io
import time
import asyncio
import random

from slowapi import Limiter
from slowapi.util import get_remote_address

from ..database import get_db
from ..schemas import (
    EmailValidationRequest,
    EmailValidationResponse,
    BulkEmailValidationRequest,
    BulkEmailValidationResponse,
    EmailValidationStatus
)
from ..services.validator import EmailValidatorService
from ..models import EmailValidation
from ..services.catchall import CatchAllDetector

router = APIRouter(prefix="/api/v1", tags=["Email Validation"])
limiter = Limiter(key_func=get_remote_address)
validator_service = EmailValidatorService()
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# Prepare catchall detector with validator's SMTP check function
async def smtp_verify(mx_host: str, recipient: str):
    return await asyncio.to_thread(validator_service._smtp_check, mx_host, recipient, 1, 1)
catchall_detector = CatchAllDetector(smtp_verify_func=smtp_verify)

@router.post("/validate", response_model=EmailValidationResponse)
@limiter.limit("10/minute")
async def validate_single_email(request: Request, email_request: EmailValidationRequest, db: Session = Depends(get_db)):
    email = email_request.email.lower()
    existing = db.query(EmailValidation).filter(EmailValidation.email == email).first()
    if existing:
        return EmailValidationResponse(
            email=existing.email,
            status=EmailValidationStatus(existing.status),
            reason=existing.reason,
            mx_records=existing.mx_records.split(", ") if existing.mx_records else None,
            smtp_response=existing.smtp_response,
            validated_at=existing.validated_at
        )
    else:
        result = await validator_service.validate_email(email)
        validation_record = EmailValidation(
            email=result['email'],
            status=result['status'].value,
            reason=result['reason'],
            mx_records=", ".join(result['mx_records']) if result['mx_records'] else None,
            smtp_response=result['smtp_response'],
            validated_at=result['validated_at']
        )
        db.add(validation_record)
        db.commit()
        db.refresh(validation_record)
        existing = validation_record
    return EmailValidationResponse(
        email=existing.email,
        status=EmailValidationStatus(existing.status),
        reason=existing.reason,
        mx_records=existing.mx_records.split(", ") if existing.mx_records else None,
        smtp_response=existing.smtp_response,
        validated_at=existing.validated_at
    )

@router.post("/validate/bulk", response_model=BulkEmailValidationResponse)
@limiter.limit("5/minute")
async def validate_bulk_emails(request: Request, bulk_request: BulkEmailValidationRequest, db: Session = Depends(get_db)):
    start_time = time.time()
    results = []
    cached = 0
    successful = 0
    failed = 0
    for email in bulk_request.emails:
        email_lower = email.lower()
        existing = db.query(EmailValidation).filter(EmailValidation.email == email_lower).first()
        if existing:
            cached += 1
            results.append(EmailValidationResponse(
                email=existing.email,
                status=EmailValidationStatus(existing.status),
                reason=existing.reason,
                mx_records=existing.mx_records.split(", ") if existing.mx_records else None,
                smtp_response=existing.smtp_response,
                validated_at=existing.validated_at
            ))
            if existing.status == EmailValidationStatus.VALID.value:
                successful += 1
            else:
                failed += 1
        else:
            result = await validator_service.validate_email(email_lower)
            validation_record = EmailValidation(
                email=result['email'],
                status=result['status'].value,
                reason=result['reason'],
                mx_records=", ".join(result['mx_records']) if result['mx_records'] else None,
                smtp_response=result['smtp_response'],
                validated_at=result['validated_at']
            )
            db.add(validation_record)
            results.append(EmailValidationResponse(
                email=result['email'],
                status=result['status'],
                reason=result['reason'],
                mx_records=result['mx_records'],
                smtp_response=result['smtp_response'],
                validated_at=result['validated_at']
            ))
            if result['status'] == EmailValidationStatus.VALID:
                successful += 1
            else:
                failed += 1
            await asyncio.sleep(random.uniform(0.3, 1.0))
    db.commit()
    processing_time = (time.time() - start_time) * 1000
    return BulkEmailValidationResponse(
        total=len(results),
        successful=successful,
        failed=failed,
        cached=cached,
        results=results,
        processing_time_ms=round(processing_time, 2)
    )

@router.post("/validate/upload", response_model=BulkEmailValidationResponse)
@limiter.limit("3/minute")
async def validate_from_csv(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024*1024)}MB")
    try:
        df = pd.read_csv(io.StringIO(contents.decode('utf-8')))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid CSV file: {str(e)}")
    if 'email' not in df.columns:
        raise HTTPException(status_code=400, detail="CSV must contain 'email' column")
    emails = df['email'].dropna().tolist()
    if len(emails) > 1000:
        raise HTTPException(status_code=400, detail="Maximum 1000 emails per upload")
    start_time = time.time()
    results = []
    errors = []
    cached = 0
    successful = 0
    failed = 0
    for idx, email in enumerate(emails, start=2):
        try:
            email_lower = str(email).lower().strip()
            if not email_lower or '@' not in email_lower:
                errors.append({"row": idx, "email": email, "error": "Invalid email format"})
                continue
            domain = email_lower.split('@')[1]
            existing = db.query(EmailValidation).filter(EmailValidation.email == email_lower).first()
            if existing:
                cached += 1
                results.append(EmailValidationResponse(
                    email=existing.email,
                    status=EmailValidationStatus(existing.status),
                    reason=existing.reason,
                    mx_records=existing.mx_records.split(", ") if existing.mx_records else None,
                    smtp_response=existing.smtp_response,
                    validated_at=existing.validated_at
                ))
                if existing.status == EmailValidationStatus.VALID.value:
                    successful += 1
                else:
                    failed += 1
            else:
                result = await validator_service.validate_email(email_lower)
                validation_record = EmailValidation(
                    email=result['email'],
                    status=result['status'].value,
                    reason=result['reason'],
                    mx_records=", ".join(result['mx_records']) if result['mx_records'] else None,
                    smtp_response=result['smtp_response'],
                    validated_at=result['validated_at']
                )
                db.add(validation_record)
                results.append(EmailValidationResponse(
                    email=result['email'],
                    status=result['status'],
                    reason=result['reason'],
                    mx_records=result['mx_records'],
                    smtp_response=result['smtp_response'],
                    validated_at=result['validated_at']
                ))
                if result['status'] == EmailValidationStatus.VALID:
                    successful += 1
                else:
                    failed += 1
                await asyncio.sleep(random.uniform(0.3, 1.0))
        except Exception as e:
            errors.append({"row": idx, "email": email, "error": str(e)})
            failed += 1
    db.commit()
    processing_time = (time.time() - start_time) * 1000
    return BulkEmailValidationResponse(
        total=len(results),
        successful=successful,
        failed=failed,
        cached=cached,
        results=results,
        errors=errors if errors else None,
        processing_time_ms=round(processing_time, 2)
    )

@router.get("/history/{email}", response_model=EmailValidationResponse)
async def get_validation_history(email: str, db: Session = Depends(get_db)):
    record = db.query(EmailValidation).filter(EmailValidation.email == email.lower()).first()
    if not record:
        raise HTTPException(status_code=404, detail="Email not found in validation history")
    return EmailValidationResponse(
        email=record.email,
        status=EmailValidationStatus(record.status),
        reason=record.reason,
        mx_records=record.mx_records.split(", ") if record.mx_records else None,
        smtp_response=record.smtp_response,
        validated_at=record.validated_at
    )

@router.post("/reset-db", status_code=status.HTTP_200_OK)
async def reset_email_validation_db(db: Session = Depends(get_db)):
    try:
        deleted_count = db.query(EmailValidation).delete()
        db.commit()
        return {"detail": f"Database reset successful. {deleted_count} records deleted."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to reset database: {str(e)}")

@router.post("/catchall-batch")
@limiter.limit("3/minute")
async def batch_catchall_check(request: Request, db: Session = Depends(get_db), limit: int = 100):
    # Fetch records pending catch-all detection
    records = (
        db.query(EmailValidation)
        .filter(EmailValidation.catchall_checked == False)
        .limit(limit)
        .all()
    )
    if not records:
        return {"detail": "No records pending catchall validation."}
    # Group emails by domain
    domain_emails = defaultdict(list)
    for record in records:
        try:
            domain = record.email.split('@')[1].lower()
            domain_emails[domain].append(record.email)
        except:
            continue
    results = []

    # Loop domain-wise, run catch-all detection
    for domain, emails in domain_emails.items():
        try:
            dns_result = await asyncio.to_thread(validator_service._validate_dns_mx, f"user@{domain}")
            if not dns_result["valid"] or not dns_result["mx_records"]:
                results.append({"domain": domain, "catch_all": None, "message": "Invalid domain or no MX records"})
                continue
            mx_records = dns_result["mx_records"][:3]
            catch_all_flag = await catchall_detector.check_catch_all(mx_records, domain)

            # Batch update
            db.query(EmailValidation).filter(EmailValidation.email.in_(emails)).update(
                {"catch_all": catch_all_flag, "catchall_checked": True},
                synchronize_session=False
            )
            results.append({
                "domain": domain,
                "catch_all": catch_all_flag,
                "message": "Catch-all detected and updated" if catch_all_flag else "Not catch-all",
                "emails_processed": len(emails)
            })
        except Exception as e:
            results.append({"domain": domain, "catch_all": None, "error": str(e), "emails_processed": len(emails)})

    db.commit()
    return {"processed_domains": len(results), "results": results}

@router.get("/filter-emails", response_model=list[EmailValidationResponse])
@limiter.limit("10/minute")
async def filter_emails(request: Request, status: EmailValidationStatus = Query(None, description="Filter by email validation status"), db: Session=Depends(get_db)):
    query = db.query(EmailValidation)
    if status is not None:
        query = query.filter(EmailValidation.status == status.value)
    # Optionally filter catch_all
    results = [EmailValidationResponse(
        email=rec.email,
        status=EmailValidationStatus(rec.status),
        reason=rec.reason,
        mx_records=rec.mx_records.split(", ") if rec.mx_records else None,
        smtp_response=rec.smtp_response,
        validated_at=rec.validated_at
    ) for rec in query.all()]
    return results
