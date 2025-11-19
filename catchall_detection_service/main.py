import os
import re
import asyncio
import ssl
import smtplib
import socket
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, select

import dns.resolver

# Environment variable: DATABASE_URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:Mothere54345$$@158.69.0.165:5432/everifier"
)

# Setup logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Create engine and session factory
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

Base = declarative_base()

# Database model
class EmailCatchAllValidation(Base):
    __tablename__ = "email_catchall_validation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain = Column(String(255), unique=True, nullable=False, index=True)
    catch_all = Column(Boolean, nullable=True)
    catchall_checked = Column(Boolean, nullable=False, default=False)
    catchall_reason = Column(Text, nullable=True)
    validated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(tz=timezone.utc), nullable=False)

app = FastAPI(title="Catch-All Detection Service")

# Response schema
from pydantic import BaseModel
class CatchAllResponse(BaseModel):
    domain: str
    catch_all: Optional[bool] = None
    reason: Optional[str] = None

# SMTP check function
def smtp_check(mx_host: str, test_email: str, retry_count: int = 2, delay: int = 3) -> Tuple[int, str]:
    for attempt in range(retry_count):
        try:
            with smtplib.SMTP(mx_host, 25, timeout=30) as server:
                server.set_debuglevel(0)
                server.ehlo_or_helo_if_needed()
                try:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    server.starttls(context=ctx)
                except Exception as e:
                    logger.warning(f"Skipping TLS for {mx_host}: {e}")
                server.mail("emailverification842@verifyapp.syfer25.com")
                code, msg = server.rcpt(test_email)
                msg_str = msg.decode(errors='ignore') if isinstance(msg, bytes) else str(msg)
                return code, msg_str
        except (smtplib.SMTPServerDisconnected, socket.timeout) as e:
            logger.warning(f"SMTP attempt {attempt + 1} failed for {mx_host}: {e} - retrying in {delay}s")
            time.sleep(delay)
        except Exception as e:
            logger.error(f"Unexpected SMTP error on {mx_host}: {e}")
            time.sleep(delay)
    return 0, "Max retries exceeded"

# DNS MX lookup & catch-all detection
def detect_catch_all(domain: str) -> Tuple[bool, str]:
    try:
        answers = dns.resolver.resolve(domain, "MX")
        mx_records = sorted([(r.preference, str(r.exchange).rstrip(".")) for r in answers])
    except Exception as e:
        logger.warning(f"MX lookup failed for {domain}: {e}")
        return False, f"MX lookup failed: {e}"

    if not mx_records:
        return False, "No MX records found"

    # Test top 3 MX servers
    mx_hosts = [record[1] for record in mx_records[:3]]
    test_email = f"randomnonexistent{int(time.time())}@{domain}"

    for mx_host in mx_hosts:
        code, msg = smtp_check(mx_host, test_email)
        if code == 250:
            return True, f"Server accepts all emails (catch-all), response: {msg}"
        if code in {550, 551, 553, 554}:
            return False, f"Rejected unknown address with code {code}: {msg}"

    return False, "Unable to determine catch-all status conclusively"

# Startup event: create tables
@app.on_event("startup")
async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Endpoint: validate catch-all domain
@app.post("/validate/catchall/{domain}", response_model=CatchAllResponse)
async def validate_catchall(domain: str):
    domain = domain.lower().strip()
    if not domain or not re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", domain):
        raise HTTPException(status_code=400, detail="Invalid domain format")
    async with async_session() as session:
        # Check cache
        result = await session.execute(select(EmailCatchAllValidation).where(EmailCatchAllValidation.domain == domain))
        existing = result.scalar_one_or_none()

        # Use cache if valid
        if existing and existing.catchall_checked:
            return {
                "domain": domain,
                "catch_all": existing.catch_all,
                "reason": existing.catchall_reason
            }

        # Run detection in thread
        catch_all, reason = await asyncio.to_thread(detect_catch_all, domain)

        # Update or create record
        if existing:
            existing.catch_all = catch_all
            existing.catchall_checked = True
            existing.catchall_reason = reason
            existing.validated_at = datetime.now(tz=timezone.utc)
        else:
            new_record = EmailCatchAllValidation(
                domain=domain,
                catch_all=catch_all,
                catchall_checked=True,
                catchall_reason=reason,
                validated_at=datetime.now(tz=timezone.utc)
            )
            session.add(new_record)

        await session.commit()

        return {
            "domain": domain,
            "catch_all": catch_all,
            "reason": reason
        }
