import asyncio
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import EmailValidationTransaction, EmailSyntaxMXValidation
from dependencies import get_async_session

import smtplib
import ssl
import random
import socket

router = APIRouter()

class SMTPValidationRequest(BaseModel):
    transaction_id: str
    level: int = 1  # 1 for high priority MX + port 25, 2 for all MXs and ports

FROM_EMAILS = ["noreply@example.com", "test@example.com"]
SMTP_TIMEOUT = 10
LEVEL1_SMTP_PORTS = [25]
LEVEL2_SMTP_PORTS = [25, 587, 465]

SMTP_STATUS_MAP = {
    250: "valid",
    251: "valid",
    550: "mailbox not found",
    551: "user not found",
    552: "mailbox full",
    553: "invalid mailbox",
    554: "rejected",
}

async def perform_smtp_check(email: str, mx_hosts: List[str], ports: List[int]) -> (str, str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _smtp_check(email, mx_hosts, ports))

def _smtp_check(email: str, mx_hosts: List[str], ports: List[int]) -> (str, str):
    from_email = random.choice(FROM_EMAILS)

    for mx_host in mx_hosts:
        for port in ports:
            try:
                if port == 465:
                    context = ssl.create_default_context()
                    with smtplib.SMTP_SSL(mx_host, port, timeout=SMTP_TIMEOUT, context=context) as server:
                        server.ehlo_or_helo_if_needed()
                        server.mail(from_email)
                        code, msg = server.rcpt(email)
                        status = SMTP_STATUS_MAP.get(code, f"unknown ({code})")
                        return status, msg.decode() if isinstance(msg, bytes) else str(msg)
                else:
                    with smtplib.SMTP(mx_host, port, timeout=SMTP_TIMEOUT) as server:
                        server.ehlo_or_helo_if_needed()
                        if port == 587:
                            try:
                                ctx = ssl.create_default_context()
                                ctx.check_hostname = False
                                ctx.verify_mode = ssl.CERT_NONE
                                server.starttls(context=ctx)
                                server.ehlo()
                            except Exception:
                                pass
                        server.mail(from_email)
                        code, msg = server.rcpt(email)
                        status = SMTP_STATUS_MAP.get(code, f"unknown ({code})")
                        return status, msg.decode() if isinstance(msg, bytes) else str(msg)
            except (smtplib.SMTPServerDisconnected, socket.timeout, smtplib.SMTPConnectError):
                continue
            except Exception as e:
                return "error", f"Unexpected error: {e}"
    return "no response", "No SMTP server responded successfully"

@router.post("/validate/smtp/by-transaction")
async def validate_emails(
    request: SMTPValidationRequest,
    session: AsyncSession = Depends(get_async_session)
):
    transaction = await session.get(EmailValidationTransaction, request.transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Get emails that are syntax+MX valid and not yet checked for the requested level
    stmt = select(EmailSyntaxMXValidation).where(
        EmailSyntaxMXValidation.transaction_id == request.transaction_id,
        EmailSyntaxMXValidation.is_syntax_mx_valid == True
    )
    result = await session.execute(stmt)
    records = result.scalars().all()
    if not records:
        raise HTTPException(status_code=404, detail="No valid emails to validate in transaction")

    results = []

    for record in records:
        # Skip if the requested level check is already done
        if request.level == 1 and record.is_level1_checked:
            continue
        if request.level == 2 and record.is_level2_checked:
            continue

        mx_list = []
        if record.mx_records:
            for item in record.mx_records.split(","):
                if ":" in item:
                    _, host = item.split(":", 1)
                    mx_list.append(host.strip())
        else:
            domain = record.email.split("@")[-1]
            mx_list = [domain]

        ports = LEVEL1_SMTP_PORTS if request.level == 1 else LEVEL2_SMTP_PORTS
        mx_hosts = mx_list[:1] if request.level == 1 else mx_list

        smtp_status, smtp_response = await perform_smtp_check(record.email, mx_hosts, ports)

        record.is_smtp_checked = True
        record.smtp_valid = smtp_status == "valid"
        record.smtp_response = smtp_response
        record.smtp_status = smtp_status
        if request.level == 1:
            record.is_level1_checked = True
        elif request.level == 2:
            record.is_level2_checked = True
        # For catchall checks, similar logic can be added when implemented

        await session.commit()

        results.append({
            "email": record.email,
            "smtp_status": record.smtp_status,
            "smtp_valid": record.smtp_valid,
            "smtp_response": record.smtp_response,
            "is_level1_checked": record.is_level1_checked,
            "is_level2_checked": record.is_level2_checked,
            "is_catchall_checked": record.is_catchall_checked,
        })

    return {"results": results}
