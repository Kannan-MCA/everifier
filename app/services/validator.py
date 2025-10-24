from email_validator import validate_email as core_validate_email, EmailNotValidError
from fastapi import HTTPException
import dns.resolver
import smtplib
import socket

# Blocklists
DISPOSABLE_DOMAINS = {"mailinator.com", "10minutemail.com", "guerrillamail.com"}
ROLE_PREFIXES = {"admin", "support", "info", "sales", "contact", "help"}
def smtp_check(email: str) -> bool:
    domain = email.split('@')[1]
    try:
        mx_records = dns.resolver.resolve(domain, 'MX')
        mx_host = str(mx_records[0].exchange)
        server = smtplib.SMTP(mx_host, timeout=10)
        server.helo()
        server.mail('validator@example.com')
        code, _ = server.rcpt(email)
        server.quit()
        return code == 250
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, socket.timeout, smtplib.SMTPException):
        return False

def is_disposable(email: str) -> bool:
    domain = email.split('@')[1].lower()
    return domain in DISPOSABLE_DOMAINS

def is_role_address(email: str) -> bool:
    prefix = email.split('@')[0].lower()
    return prefix in ROLE_PREFIXES

def validate(email: str) -> dict:
    try:
        result = core_validate_email(email, check_deliverability=True)
        clean_email = result.email
        smtp_valid = smtp_check(clean_email)
        disposable = is_disposable(clean_email)
        role_address = is_role_address(clean_email)

        return {
            "email": clean_email,
            "format_valid": True,
            "mx_valid": True,
            "smtp_valid": smtp_valid,
            "disposable": disposable,
            "role_address": role_address
        }

    except EmailNotValidError as e:
        raise HTTPException(status_code=400, detail=str(e))