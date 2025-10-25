from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
import pandas as pd
import io

from ..database import get_db
from ..schemas import (
    EmailValidationRequest,
    EmailValidationResponse,
    BulkEmailValidationRequest,
    BulkEmailValidationResponse
)
from ..services.validator import EmailValidatorService
from ..models import EmailValidation

router = APIRouter(prefix="/api/v1", tags=["Email Validation"])

validator_service = EmailValidatorService()


@router.post("/validate", response_model=EmailValidationResponse)
async def validate_single_email(
    request: EmailValidationRequest,
    db: Session = Depends(get_db)
):
    """Validate a single email address"""
    
    # Check if email already validated in database
    existing = db.query(EmailValidation).filter(
        EmailValidation.email == request.email.lower()
    ).first()
    
    if existing:
        return EmailValidationResponse(
            email=existing.email,
            status=existing.status,
            reason=existing.reason,
            mx_records=existing.mx_records.split(", ") if existing.mx_records else None,
            smtp_response=existing.smtp_response,
            validated_at=existing.validated_at
        )
    
    # Perform validation
    result = validator_service.validate_email(request.email)
    
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
async def validate_bulk_emails(
    request: BulkEmailValidationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Validate multiple email addresses"""
    
    results = []
    
    for email in request.emails:
        email_lower = email.lower()
        
        # Check cache in database
        existing = db.query(EmailValidation).filter(
            EmailValidation.email == email_lower
        ).first()
        
        if existing:
            results.append(EmailValidationResponse(
                email=existing.email,
                status=existing.status,
                reason=existing.reason,
                mx_records=existing.mx_records.split(", ") if existing.mx_records else None,
                smtp_response=existing.smtp_response,
                validated_at=existing.validated_at
            ))
        else:
            # Perform validation
            result = validator_service.validate_email(email)
            
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
    
    db.commit()
    
    return BulkEmailValidationResponse(
        total=len(results),
        results=results
    )


@router.post("/validate/upload", response_model=BulkEmailValidationResponse)
async def validate_from_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Validate emails from CSV file upload"""
    
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")
    
    # Read CSV
    contents = await file.read()
    df = pd.read_csv(io.StringIO(contents.decode('utf-8')))
    
    if 'email' not in df.columns:
        raise HTTPException(status_code=400, detail="CSV must contain 'email' column")
    
    emails = df['email'].dropna().tolist()
    
    if len(emails) > 1000:
        raise HTTPException(status_code=400, detail="Maximum 1000 emails per upload")
    
    results = []
    
    for email in emails:
        try:
            email_lower = str(email).lower().strip()
            
            # Check database cache
            existing = db.query(EmailValidation).filter(
                EmailValidation.email == email_lower
            ).first()
            
            if existing:
                results.append(EmailValidationResponse(
                    email=existing.email,
                    status=existing.status,
                    reason=existing.reason,
                    mx_records=existing.mx_records.split(", ") if existing.mx_records else None,
                    smtp_response=existing.smtp_response,
                    validated_at=existing.validated_at
                ))
            else:
                # Perform validation
                result = validator_service.validate_email(email_lower)
                
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
        except Exception as e:
            continue
    
    db.commit()
    
    return BulkEmailValidationResponse(
        total=len(results),
        results=results
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
        status=record.status,
        reason=record.reason,
        mx_records=record.mx_records.split(", ") if record.mx_records else None,
        smtp_response=record.smtp_response,
        validated_at=record.validated_at
    )
