import asyncio
import random
import smtplib
import socket
import ssl
import time
from typing import List, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import EmailValidationTransaction, EmailSyntaxMXValidation


from dependencies import get_async_session

router = APIRouter()



class CatchAllValidationRequest(BaseModel):
    transaction_id: str


CATCHALL_FROM = "noreply@verifyapp.syfer25.com"
CATCHALL_TIMEOUT = 12
CATCHALL_PORT = 25
ACCEPT_CODES = {250}
REJECT_CODES = {550, 551, 553, 554}

# Public mailbox providers to skip for catch-all
SKIP_CATCHALL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "yahoo.co.in",
    "ymail.com",
    "rocketmail.com",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "msn.com",
    "icloud.com",
    "me.com",
}


async def perform_catchall_check(domain: str, mx_hosts: List[str]) -> Tuple[bool | None, str]:
    """
    Run blocking catch-all detection in a thread pool and return (is_catchall, reason).
    True  -> catch-all
    False -> not catch-all
    None  -> inconclusive
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _catchall_check(domain, mx_hosts))


def _catchall_check(domain: str, mx_hosts: List[str]) -> Tuple[bool | None, str]:
    """
    Blocking catch-all detection:
    - Uses a guaranteed non-existent local part.
    - Tests up to first 3 MX on port 25.
    """
    test_email = _generate_nonexistent_email(domain)
    tested_hosts: List[str] = []

    for mx_host in mx_hosts[:3]:
        tested_hosts.append(mx_host)
        try:
            with smtplib.SMTP(mx_host, CATCHALL_PORT, timeout=CATCHALL_TIMEOUT) as server:
                server.ehlo_or_helo_if_needed()

                # Try STARTTLS; not mandatory for catch-all logic
                try:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    server.starttls(context=ctx)
                    server.ehlo_or_helo_if_needed()
                except Exception:
                    pass

                server.mail(CATCHALL_FROM)
                code, msg = server.rcpt(test_email)
                msg_str = msg.decode(errors="ignore") if isinstance(msg, bytes) else str(msg)

                # Catch-all: accepts unknown user
                if code in ACCEPT_CODES:
                    return True, f"Catch-all detected on {mx_host} (code {code}): {msg_str[:200]}"

                # Not catch-all: rejects unknown user
                if code in REJECT_CODES:
                    return False, f"No catch-all on {mx_host} (code {code}): {msg_str[:200]}"

        except (smtplib.SMTPServerDisconnected, socket.timeout, smtplib.SMTPConnectError):
            continue
        except Exception as e:
            return None, f"Error testing {mx_host}: {e}"

    return None, f"Inconclusive catch-all check; tested {len(tested_hosts)} MX hosts"


def _generate_nonexistent_email(domain: str) -> str:
    """
    Generate a very low probability real address, for catch-all testing.
    """
    ts = int(time.time() * 1000)
    rnd = random.randint(100000, 999999)
    return f"nonexistent{rnd}{ts}@{domain}"


@router.post("/validate/catchall/by-transaction")
async def validate_catchall_by_transaction(
    request: CatchAllValidationRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Level 3 catch-all validation by transaction:
    - Skips public providers (gmail, yahoo, hotmail, etc.)
    - Runs catch-all only for business domains
    """
    # 1) Ensure transaction exists
    transaction = await session.get(EmailValidationTransaction, request.transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # 2) Get all syntax+MX valid, SMTP checked records
    stmt = select(EmailSyntaxMXValidation).where(
        EmailSyntaxMXValidation.transaction_id == request.transaction_id,
        EmailSyntaxMXValidation.is_syntax_mx_valid == True,
        EmailSyntaxMXValidation.is_smtp_checked == True,
    )
    result = await session.execute(stmt)
    records = result.scalars().all()
    if not records:
        raise HTTPException(
            status_code=404,
            detail="No emails eligible for catch-all in this transaction",
        )

    results = []

    for record in records:
        # Skip if catch-all was already checked
        if getattr(record, "is_catchall_checked", False):
            continue

        # Derive domain
        domain = record.email.split("@")[-1].lower()

        # 2a) Skip public mail providers
        if domain in SKIP_CATCHALL_DOMAINS:
            record.is_catchall_checked = True
            record.is_catchall = None
            record.catchall_reason = "Catch-all check skipped for public provider"
            await session.commit()

            results.append(
                {
                    "email": record.email,
                    "domain": domain,
                    "is_catchall": record.is_catchall,
                    "catchall_reason": record.catchall_reason,
                    "is_catchall_checked": record.is_catchall_checked,
                    "smtp_valid": getattr(record, "smtp_valid", None),
                    "smtp_status": getattr(record, "smtp_status", None),
                }
            )
            continue

        # 2b) Build MX hosts list for business domains
        mx_hosts: List[str] = []
        if record.mx_records:
            for item in record.mx_records.split(","):
                item = item.strip()
                if ":" in item:
                    _, host = item.split(":", 1)
                    mx_hosts.append(host.strip())
                else:
                    mx_hosts.append(item)
        else:
            mx_hosts = [domain]

        # 3) Run catch-all detection
        is_catchall, reason = await perform_catchall_check(domain, mx_hosts)

        # 4) Persist result
        record.is_catchall_checked = True
        record.is_catchall = is_catchall
        record.catchall_reason = reason
        await session.commit()

        results.append(
            {
                "email": record.email,
                "domain": domain,
                "is_catchall": is_catchall,
                "catchall_reason": reason,
                "is_catchall_checked": record.is_catchall_checked,
                "smtp_valid": getattr(record, "smtp_valid", None),
                "smtp_status": getattr(record, "smtp_status", None),
            }
        )

    if not results:
        return {
            "results": [],
            "message": "All emails in this transaction already have catch-all checked",
        }

    return {"results": results}
