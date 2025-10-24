import os
import io
import asyncio
import logging
from typing import List


import dns.resolver
import pandas as pd
from validate_email import validate_email as ve_validate_email
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, ValidationError
from dotenv import load_dotenv


# Load environment variables
load_dotenv()


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


router = APIRouter()


# Pydantic Models
class MXResult(BaseModel):
    mx_host: str


class EmailValidationResponse(BaseModel):
    email: str
    status: str  # valid, invalid, user-notfound, catchall, blocklisted


# Email syntax model for validation
class EmailModel(BaseModel):
    email: EmailStr


# MX record resolution
async def resolve_mx(domain: str) -> List[str]:
    try:
        answers = dns.resolver.resolve(domain, 'MX')
        return [str(r.exchange).rstrip('.') for r in sorted(answers, key=lambda r: r.preference)]
    except Exception as e:
        logger.warning(f"MX resolution failed for {domain}: {e}")
        return []


# Email syntax check using Pydantic model
def is_valid_syntax(email: str) -> bool:
    try:
        EmailModel(email=email)
        return True
    except ValidationError:
        return False


# Stub for blocklist detection - needs your logic or third party integration
def is_blocklisted(email: str) -> bool:
    # Implement your blocklist check here, e.g. domain or full email matching
    return False


# Stub for catchall detection - requires SMTP probe or heuristics; here just false
def is_catchall(domain: str) -> bool:
    # Implement your catchall detection logic if possible, else return False
    return False


# Main validation function with SMTP RCPT TO probing using validate_email library
async def validate_email(email: str) -> dict:
    if not is_valid_syntax(email):
        return {
            "email": email,
            "status": "invalid",
        }

    if is_blocklisted(email):
        return {
            "email": email,
            "status": "blocklisted",
        }

    domain = email.split('@')[-1]
    mx_records = await resolve_mx(domain)

    if not mx_records:
        return {
            "email": email,
            "status": "invalid",
        }

    # Use validate_email library to verify domain, mailbox existence with SMTP RCPT TO check
    try:
        is_valid = ve_validate_email(
            email_address=email,
            check_regex=True,
            check_mx=True,
            verify=True,  # Enables SMTP RCPT TO verification
            smtp_timeout=10,
            dns_timeout=10,
        )
    except Exception as e:
        logger.warning(f"validate_email SMTP exception for {email}: {e}")
        is_valid = False

    if not is_valid:
        # Here assuming user-notfound if MX exists but validation fails
        return {
            "email": email,
            "status": "user-notfound",
        }

    # Check catchall heuristics if implemented
    if is_catchall(domain):
        return {
            "email": email,
            "status": "catchall",
        }

    return {
        "email": email,
        "status": "valid",
    }


# Routes
@router.post("/validate", response_model=EmailValidationResponse)
async def validate_single(email: str = Form(...)):
    try:
        result = await validate_email(email)
        return result
    except Exception as e:
        logger.exception("Validation failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/validate-batch", response_model=List[EmailValidationResponse])
async def validate_batch(emails: List[str] = Body(...)):
    tasks = [validate_email(email) for email in emails]
    results = await asyncio.gather(*tasks)
    return results


@router.post("/validate-csv")
async def validate_csv(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        df = pd.read_csv(io.StringIO(contents.decode("utf-8")))

        if "email" not in df.columns:
            return JSONResponse(content={"error": "CSV must contain an 'email' column"}, status_code=400)

        tasks = [validate_email(email) for email in df["email"]]
        results = await asyncio.gather(*tasks)
        df_out = pd.DataFrame(results)

        output = io.StringIO()
        df_out.to_csv(output, index=False)
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=validation_results.csv"},
        )
    except Exception as e:
        logger.exception("CSV validation failed")
        return JSONResponse(content={"error": str(e)}, status_code=400)
