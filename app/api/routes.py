# app/api/routes.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from sqlalchemy.orm import Session
from typing import List
import pandas as pd
import io
import time
from collections import defaultdict
import asyncio

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


router = APIRouter(prefix="/api/v1", tags=["Email Validation"])
limiter = Limiter(key_func=get_remote_address)

# Initialize validator service
validator_service = EmailValidatorService()

# File size limit (5MB)
MAX_FILE_SIZE = 5 * 1024 * 1024


@router.post("/validate", response_model=EmailValidationResponse)
@limiter.limit("10/minute")
async def validate_single_email(
    request: Request,
    email_request: EmailValidationRequest,
    db: Session = Depends(get_db)
):
    """Validate a single email address"""
    
    email = email_request.email.lower()
    
    # Check if email already validated in database
    existing = db.query(EmailValidation).filter(
        EmailValidation.email == email
    ).first()
    
    if existing:
        return EmailValidationResponse(
            email=existing.email,
            status=EmailValidationStatus(existing.status),
            reason=existing.reason,
            mx_records=existing.mx_records.split(", ") if existing.mx_records else None,
            smtp_response=existing.smtp_response,
            validated_at=existing.validated_at
        )
    
    # Perform async validation
    result = await validator_service.validate_email(email)
    
    # Save to database
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
    
    return EmailValidationResponse(
        email=result['email'],
        status=result['status'],
        reason=result['reason'],
        mx_records=result['mx_records'],
        smtp_response=result['smtp_response'],
        validated_at=result['validated_at']
    )


@router.post("/validate/bulk", response_model=BulkEmailValidationResponse)
@limiter.limit("5/minute")
async def validate_bulk_emails(
    request: Request,
    bulk_request: BulkEmailValidationRequest,
    db: Session = Depends(get_db)
):
    """Validate multiple email addresses with domain-based rate limiting"""
    
    start_time = time.time()
    results = []
    cached = 0
    successful = 0
    failed = 0
    
    # Group emails by domain to prevent overwhelming same MX server
    by_domain = defaultdict(list)
    for email in bulk_request.emails:
        domain = email.split('@')[1].lower()
        by_domain[domain].append(email.lower())
    
    # Process each domain group with delays
    for domain, domain_emails in by_domain.items():
        for email in domain_emails:
            # Check cache
            existing = db.query(EmailValidation).filter(
                EmailValidation.email == email
            ).first()
            
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
                
                if existing.status == "valid":
                    successful += 1
                else:
                    failed += 1
            else:
                # Perform validation
                result = await validator_service.validate_email(email)
                
                # Save to database
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
            
            # Small delay between emails to same domain
            import random
            await asyncio.sleep(random.uniform(0.3, 1.0))
    
    db.commit()
    
    processing_time = (time.time() - start_time) * 1000  # Convert to ms
    
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
async def validate_from_csv(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Validate emails from CSV file upload"""
    
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")
    
    # Read and check file size
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024*1024)}MB"
        )
    
    # Parse CSV
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
    
    # Group by domain
    by_domain = defaultdict(list)
    for idx, email in enumerate(emails, start=2):
        try:
            email_lower = str(email).lower().strip()
            
            if not email_lower or '@' not in email_lower:
                errors.append({"row": idx, "email": email, "error": "Invalid email format"})
                continue
            
            domain = email_lower.split('@')[1]
            by_domain[domain].append((idx, email_lower))
        except Exception as e:
            errors.append({"row": idx, "email": str(email), "error": str(e)})
    
    # Process each domain group
    for domain, domain_emails in by_domain.items():
        for idx, email in domain_emails:
            try:
                # Check database cache
                existing = db.query(EmailValidation).filter(
                    EmailValidation.email == email
                ).first()
                
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
                    
                    if existing.status == "valid":
                        successful += 1
                    else:
                        failed += 1
                else:
                    # Perform validation
                    result = await validator_service.validate_email(email)
                    
                    # Save to database
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
                
                # Delay between emails to same domain
                import random
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
    """Get validation history for a specific email"""
    
    record = db.query(EmailValidation).filter(
        EmailValidation.email == email.lower()
    ).first()
    
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
