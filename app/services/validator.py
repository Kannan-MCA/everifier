import re
import asyncio
import ssl
import smtplib
import socket
import random
import string
import time
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, UTC
import dns.resolver
from email_validator import validate_email as validate_email_syntax, EmailNotValidError

from ..schemas import EmailValidationStatus

logger = logging.getLogger(__name__)

class EmailValidatorService:
    EMAIL_PATTERN = re.compile(
        r'^[a-zA-Z0-9][a-zA-Z0-9.!#$%&\'*+/=?^_`{|}~-]*[a-zA-Z0-9]@'
        r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
    )
    SKIP_SMTP_DOMAINS = set()
    DISPOSABLE_DOMAINS = set()
    BLOCKLISTED_DOMAINS = set()
    ROLE_BASED_PREFIXES = set()
    SMTP_PORTS = [25, 587, 465]

    def __init__(self, from_email="verify@verifyapp.syfer25.com", helo_hostname="mail.verifyapp.syfer25.com"):
        self.from_email = from_email
        self.helo_hostname = helo_hostname
        logger.info(f"EmailValidatorService initialized with from_email={from_email}")

    async def validate_email(self, email: str) -> Dict:
        logger.info(f"Validating email: {email}")
        email = email.lower().strip()

        if not self._is_valid_format(email):
            return self._create_result(email, EmailValidationStatus.INVALID, "Invalid email format", None, None)

        domain = self._extract_domain(email)
        local_part = email.split('@')[0]

        if domain in self.BLOCKLISTED_DOMAINS:
            return self._create_result(email, EmailValidationStatus.BLOCKLISTED, "Domain is blocklisted", None, None)

        if domain in self.DISPOSABLE_DOMAINS:
            return self._create_result(email, EmailValidationStatus.DISPOSABLE, "Disposable email address", None, None)

        if local_part in self.ROLE_BASED_PREFIXES:
            return self._create_result(email, EmailValidationStatus.ROLE_BASED, "Role-based email address", None, None)

        dns_result = await asyncio.to_thread(self._validate_dns_mx, email)
        if not dns_result or not dns_result.get('valid', False):
            reason = dns_result['reason'] if dns_result else 'DNS validation error'
            return self._create_result(email, EmailValidationStatus.INVALID, reason, None, None)

        mx_records = dns_result.get('mx_records', None)
        if not mx_records:
            return self._create_result(email, EmailValidationStatus.INVALID, "No valid MX records found", None, None)

        if domain in self.SKIP_SMTP_DOMAINS:
            return self._create_result(email, EmailValidationStatus.UNKNOWN, f"SMTP validation skipped for {domain} (port 25 blocked by provider)", mx_records, None)

        status, reason, smtp_response = await asyncio.to_thread(self._validate_via_smtp, email, mx_records, domain)

        # Catch-all detection to be handled outside, after initial validation

        return self._create_result(email, status, reason, mx_records, smtp_response)

    def _is_valid_format(self, email: str) -> bool:
        if not self.EMAIL_PATTERN.match(email):
            return False
        try:
            validate_email_syntax(email, check_deliverability=False)
            return True
        except EmailNotValidError:
            return False

    def _extract_domain(self, email: str) -> str:
        return email.split('@')[1]

    def _validate_dns_mx(self, email: str) -> Optional[Dict]:
        try:
            domain = self._extract_domain(email)
            try:
                mx_records = dns.resolver.resolve(domain, 'MX')
                mx_list = [str(r.exchange).rstrip('.') for r in sorted(mx_records, key=lambda x: x.preference)]
                if not mx_list:
                    return {'valid': False, 'reason': 'No MX records found for domain', 'mx_records': None}
                return {'valid': True, 'mx_records': mx_list, 'reason': None}
            except dns.resolver.NoAnswer:
                return {'valid': False, 'reason': 'No MX records found for domain', 'mx_records': None}
            except dns.resolver.NXDOMAIN:
                return {'valid': False, 'reason': 'Domain does not exist', 'mx_records': None}
            except dns.resolver.Timeout:
                return {'valid': False, 'reason': 'DNS lookup timeout', 'mx_records': None}
            except Exception as e:
                return {'valid': False, 'reason': f'DNS lookup failed: {str(e)}', 'mx_records': None}
        except Exception as e:
            return {'valid': False, 'reason': f'DNS validation error: {str(e)}', 'mx_records': None}

    def _validate_via_smtp(self, email: str, mx_records: List[str], domain: str) -> Tuple[EmailValidationStatus, str, Optional[str]]:
        code_real = 0
        msg_real = "No MX responded"
        for mx_host in mx_records[:3]:
            try:
                logger.info(f"Trying MX server: {mx_host}")
                code_real, msg_real = self._smtp_check(mx_host, email)
                if code_real != 0:
                    break
                else:
                    logger.warning(f"{mx_host} did not respond definitively, trying next MX...")
                    time.sleep(2)
            except Exception as e:
                logger.error(f"Error validating via {mx_host}: {str(e)}")
                continue
        if code_real == 0:
            return EmailValidationStatus.UNKNOWN, f"All MX servers unresponsive: {msg_real}", None
        smtp_response = f"{code_real} {msg_real}"
        logger.info(f"SMTP response: {smtp_response}")
        if code_real == 250:
            return EmailValidationStatus.VALID, "Mailbox verified via SMTP", smtp_response
        return self._parse_smtp_response(code_real, smtp_response)

    def _smtp_check(self, mx_host: str, rcpt_email: str, retry_count: int = 2, delay: int = 3) -> Tuple[int, str]:
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
                        server.ehlo()
                        logger.debug("STARTTLS successful")
                    except Exception as e:
                        logger.warning(f"Skipping TLS: {e}")
                    server.mail(self.from_email)
                    code, msg = server.rcpt(rcpt_email)
                    msg_str = msg.decode(errors='ignore') if isinstance(msg, bytes) else str(msg)
                    return code, msg_str
            except smtplib.SMTPServerDisconnected as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Connection disconnected, retrying in {delay}s... (attempt {attempt + 1}/{retry_count})")
                    time.sleep(delay)
                    continue
                return 0, f"Connection disconnected after {retry_count} attempts: {e}"
            except socket.timeout as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Timeout, retrying in {delay}s... (attempt {attempt + 1}/{retry_count})")
                    time.sleep(delay)
                    continue
                return 0, f"Connection timeout after {retry_count} attempts: {e}"
            except smtplib.SMTPConnectError as e:
                return 0, f"Connection refused: {e}"
            except Exception as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Error occurred, retrying in {delay}s... (attempt {attempt + 1}/{retry_count})")
                    time.sleep(delay)
                    continue
                return 0, str(e)
        return 0, "Max retries exceeded"

    async def _detect_catch_all_async(self, mx_hosts: List[str], domain: str, attempts_per_mx: int = 3, positive_threshold: float = 0.8) -> bool:
        positive_responses = 0
        total_attempts = len(mx_hosts) * attempts_per_mx
        for mx_host in mx_hosts:
            for _ in range(attempts_per_mx):
                random_local = ''.join(random.choices(string.ascii_lowercase + string.digits, k=15))
                fake_email = f"{random_local}@{domain}"
                code, _ = await asyncio.to_thread(self._smtp_check, mx_host, fake_email, 1, 1)
                if code == 250:
                    positive_responses += 1
                await asyncio.sleep(random.uniform(0.2, 1.0))
        ratio = positive_responses / total_attempts if total_attempts > 0 else 0.0
        return ratio >= positive_threshold

    def _parse_smtp_response(self, code: int, response: str) -> Tuple[EmailValidationStatus, str, str]:
        response_lower = response.lower()
        if code in {550, 551, 553, 554}:
            if any(keyword in response_lower for keyword in [
                'user not found', 'user unknown', 'no such user',
                'mailbox not found', 'mailbox unavailable',
                'recipient rejected', 'address rejected',
                'does not exist', 'invalid recipient',
                'unknown user', 'no mailbox', '5.1.1'
            ]):
                return EmailValidationStatus.USER_NOT_FOUND, "Mailbox does not exist", response
            return EmailValidationStatus.INVALID, f"Email rejected (code {code})", response
        if code == 552:
            return EmailValidationStatus.INVALID, "Mailbox full or policy restriction", response
        if code in {450, 451, 452}:
            return EmailValidationStatus.UNKNOWN, "Temporary failure - greylisting or rate limit", response
        if code == 421:
            return EmailValidationStatus.UNKNOWN, "Service temporarily unavailable", response
        return EmailValidationStatus.UNKNOWN, f"Unhandled SMTP code: {code}", response

    def _create_result(self, email: str, status: EmailValidationStatus, reason: str, mx_records: Optional[List[str]], smtp_response: Optional[str]) -> Dict:
        return {
            'email': email,
            'status': status,
            'reason': reason,
            'mx_records': mx_records,
            'smtp_response': smtp_response,
            'validated_at': datetime.now(UTC)
        }
