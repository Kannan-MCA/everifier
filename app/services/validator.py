# app/services/validator.py
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
    
    # Email regex pattern
    EMAIL_PATTERN = re.compile(
        r'^[a-zA-Z0-9][a-zA-Z0-9.!#$%&\'*+/=?^_`{|}~-]*[a-zA-Z0-9]@'
        r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
    )
    
    # Skip SMTP validation for these domains
    SKIP_SMTP_DOMAINS = {
        # 'gmail.com', 'googlemail.com',
        # 'yahoo.com', 'yahoo.co.uk', 'yahoo.co.in',
        # 'outlook.com', 'hotmail.com', 'live.com', 'msn.com',
        # 'aol.com', 'protonmail.com', 'icloud.com', 'me.com', 'mac.com'
    }
    
    # Disposable email domains
    DISPOSABLE_DOMAINS = {
        'tempmail.com', 'throwaway.email', 'guerrillamail.com',
        '10minutemail.com', 'mailinator.com', 'temp-mail.org',
        'fakeinbox.com', 'getnada.com', 'trashmail.com',
        'maildrop.cc', 'yopmail.com', 'mohmal.com'
    }
    
    # Blocklisted domains
    BLOCKLISTED_DOMAINS = {
        'spam.com', 'blocked.com', 'malicious.com'
    }
    
    # Role-based email prefixes
    ROLE_BASED_PREFIXES = {
        'admin', 'support', 'help', 'info', 'noreply', 'no-reply',
        'sales', 'marketing', 'contact', 'service', 'team',
        'hello', 'mail', 'postmaster', 'webmaster', 'abuse'
    }
    
    # SMTP ports to try
    SMTP_PORTS = [25, 587, 465]
    
    def __init__(self, 
                 from_email: str = "verify@verifyapp.syfer25.com",
                 helo_hostname: str = "mail.verifyapp.syfer25.com"):
        self.from_email = from_email
        self.helo_hostname = helo_hostname
        logger.info(f"EmailValidatorService initialized with from_email={from_email}")
    
    async def validate_email(self, email: str) -> Dict:
        """Main async validation method"""
        logger.info(f"Validating email: {email}")
        email = email.lower().strip()
        
        # Step 1: Format validation
        if not self._is_valid_format(email):
            logger.debug(f"Invalid format: {email}")
            return self._create_result(
                email, EmailValidationStatus.INVALID,
                'Invalid email format', None, None
            )
        
        domain = self._extract_domain(email)
        local_part = email.split('@')[0]
        
        # Step 2: Check blocklist
        if domain in self.BLOCKLISTED_DOMAINS:
            logger.debug(f"Blocklisted domain: {domain}")
            return self._create_result(
                email, EmailValidationStatus.BLOCKLISTED,
                'Domain is blocklisted', None, None
            )
        
        # Step 3: Check disposable
        if domain in self.DISPOSABLE_DOMAINS:
            logger.debug(f"Disposable domain: {domain}")
            return self._create_result(
                email, EmailValidationStatus.DISPOSABLE,
                'Disposable email address', None, None
            )
        
        # Step 4: Check role-based
        if local_part in self.ROLE_BASED_PREFIXES:
            logger.debug(f"Role-based email: {local_part}")
            return self._create_result(
                email, EmailValidationStatus.ROLE_BASED,
                'Role-based email address', None, None
            )
        
        # Step 5: DNS + MX validation
        dns_result = await asyncio.to_thread(self._validate_dns_mx, email)
        if not dns_result['valid']:
            logger.debug(f"DNS/MX validation failed: {dns_result['reason']}")
            return self._create_result(
                email, EmailValidationStatus.INVALID,
                dns_result['reason'], None, None
            )
        
        mx_records = dns_result['mx_records']
        
        if not mx_records:
            return self._create_result(
                email, EmailValidationStatus.INVALID,
                'No valid MX records found', None, None
            )
        
        # Step 6: Skip SMTP for major providers (if configured)
        if domain in self.SKIP_SMTP_DOMAINS:
            logger.info(f"Skipping SMTP validation for {domain}")
            return self._create_result(
                email, EmailValidationStatus.UNKNOWN,
                f'SMTP validation skipped for {domain} (port 25 blocked by provider)',
                mx_records, None
            )
        
        # Step 7: SMTP validation (run in thread pool)
        logger.info(f"Starting SMTP validation for {email}")
        status, reason, smtp_response = await asyncio.to_thread(
            self._validate_via_smtp, email, mx_records, domain
        )
        
        return self._create_result(email, status, reason, mx_records, smtp_response)
    
    def _is_valid_format(self, email: str) -> bool:
        """Validate email format using regex and email-validator"""
        if not self.EMAIL_PATTERN.match(email):
            return False
        
        try:
            validate_email_syntax(email, check_deliverability=False)
            return True
        except EmailNotValidError:
            return False
    
    def _extract_domain(self, email: str) -> str:
        """Extract domain from email address"""
        return email.split('@')[1]
    
    def _validate_dns_mx(self, email: str) -> Dict:
        """Validate DNS and MX records using dnspython (sync)"""
        try:
            domain = email.split('@')[1]
            
            # Check MX records
            try:
                mx_records = dns.resolver.resolve(domain, 'MX')
                mx_list = [str(r.exchange).rstrip('.') for r in sorted(mx_records, key=lambda x: x.preference)]
                
                if not mx_list:
                    return {
                        'valid': False,
                        'reason': 'No MX records found for domain',
                        'mx_records': None
                    }
                
                return {
                    'valid': True,
                    'mx_records': mx_list,
                    'reason': None
                }
            except dns.resolver.NoAnswer:
                return {
                    'valid': False,
                    'reason': 'No MX records found for domain',
                    'mx_records': None
                }
            except dns.resolver.NXDOMAIN:
                return {
                    'valid': False,
                    'reason': 'Domain does not exist',
                    'mx_records': None
                }
            except dns.resolver.Timeout:
                return {
                    'valid': False,
                    'reason': 'DNS lookup timeout',
                    'mx_records': None
                }
            except Exception as e:
                return {
                    'valid': False,
                    'reason': f'DNS lookup failed: {str(e)}',
                    'mx_records': None
                }
                
        except Exception as e:
            return {
                'valid': False,
                'reason': f'DNS validation error: {str(e)}',
                'mx_records': None
            }
    
    def _validate_via_smtp(
        self, 
        email: str, 
        mx_records: List[str], 
        domain: str
    ) -> Tuple[EmailValidationStatus, str, Optional[str]]:
        """Validate email via SMTP RCPT TO command (synchronous)"""
        
        # Try first 3 MX records
        code_real = 0
        msg_real = "No MX responded"
        
        for mx_host in mx_records[:3]:
            try:
                logger.info(f"Trying MX server: {mx_host}")
                code_real, msg_real = self._smtp_check(mx_host, email)
                
                if code_real != 0:  # Got a definitive response
                    break
                else:
                    logger.warning(f"{mx_host} failed, trying next MX...")
                    time.sleep(2)
                    
            except Exception as e:
                logger.error(f"Error validating via {mx_host}: {str(e)}")
                continue
        
        # If real check failed on all MX hosts
        if code_real == 0:
            return (
                EmailValidationStatus.UNKNOWN,
                f"All MX servers unresponsive: {msg_real}",
                None
            )
        
        smtp_response = f"{code_real} {msg_real}"
        logger.info(f"SMTP response: {smtp_response}")
        
        # If accepted (250), check for catch-all
        if code_real == 250:
            is_catch_all = self._detect_catch_all(mx_records[0], domain)
            
            if is_catch_all:
                return (
                    EmailValidationStatus.CATCH_ALL,
                    "Domain accepts all emails (catch-all)",
                    smtp_response
                )
            else:
                return (
                    EmailValidationStatus.VALID,
                    "Mailbox verified via SMTP",
                    smtp_response
                )
        
        return self._parse_smtp_response(code_real, smtp_response)
    
    def _smtp_check(self, mx_host: str, rcpt_email: str, retry_count: int = 2, delay: int = 3) -> Tuple[int, str]:
        """
        Open SMTP session and perform RCPT TO with retry logic.
        Returns (code, message).
        """
        for attempt in range(retry_count):
            try:
                with smtplib.SMTP(mx_host, 25, timeout=30) as server:
                    server.set_debuglevel(0)
                    server.ehlo_or_helo_if_needed()
                    
                    # TLS section - disable certificate verification for testing
                    try:
                        ctx = ssl.create_default_context()
                        ctx.check_hostname = False
                        ctx.verify_mode = ssl.CERT_NONE
                        server.starttls(context=ctx)
                        server.ehlo()
                        logger.debug("STARTTLS successful")
                    except Exception as e:
                        logger.warning(f"Skipping TLS: {e}")
                    
                    # MAIL FROM and RCPT TO
                    server.mail(self.from_email)
                    code, msg = server.rcpt(rcpt_email)
                    
                    msg_str = msg.decode(errors='ignore') if isinstance(msg, bytes) else str(msg)
                    return (code, msg_str)
                    
            except smtplib.SMTPServerDisconnected as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Connection disconnected, retrying in {delay}s... (attempt {attempt + 1}/{retry_count})")
                    time.sleep(delay)
                    continue
                return (0, f"Connection disconnected after {retry_count} attempts: {e}")
                
            except socket.timeout as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Timeout, retrying in {delay}s... (attempt {attempt + 1}/{retry_count})")
                    time.sleep(delay)
                    continue
                return (0, f"Connection timeout after {retry_count} attempts: {e}")
                
            except smtplib.SMTPConnectError as e:
                return (0, f"Connection refused: {e}")
                
            except Exception as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Error occurred, retrying in {delay}s... (attempt {attempt + 1}/{retry_count})")
                    time.sleep(delay)
                    continue
                return (0, str(e))
        
        return (0, "Max retries exceeded")
    
    def _detect_catch_all(self, mx_host: str, domain: str) -> bool:
        """Detect catch-all by testing random fake address"""
        logger.info(f"Testing catch-all for domain: {domain}")
        
        fake = ''.join(random.choices(string.ascii_lowercase + string.digits, k=15))
        fake_email = f"{fake}@{domain}"
        
        code_fake, msg_fake = self._smtp_check(mx_host, fake_email, retry_count=1, delay=2)
        
        is_catch_all = (code_fake == 250)
        logger.info(f"Catch-all detection result: {is_catch_all} (fake email code: {code_fake})")
        return is_catch_all
    
    def _parse_smtp_response(self, code: int, response: str) -> Tuple[EmailValidationStatus, str, str]:
        """Parse SMTP response code to determine email status"""
        
        response_lower = response.lower()
        
        if code in [550, 551, 553, 554]:
            if any(keyword in response_lower for keyword in [
                'user not found', 'user unknown', 'no such user',
                'mailbox not found', 'mailbox unavailable',
                'recipient rejected', 'address rejected',
                'does not exist', 'invalid recipient',
                'unknown user', 'no mailbox', '5.1.1'
            ]):
                return (
                    EmailValidationStatus.USER_NOT_FOUND,
                    "Mailbox does not exist",
                    response
                )
            
            return (
                EmailValidationStatus.INVALID,
                f"Email rejected (code {code})",
                response
            )
        
        if code in [552]:
            return (
                EmailValidationStatus.INVALID,
                "Mailbox full or policy restriction",
                response
            )
        
        if code in [450, 451, 452]:
            return (
                EmailValidationStatus.UNKNOWN,
                "Temporary failure - greylisting or rate limit",
                response
            )
        
        if code == 421:
            return (
                EmailValidationStatus.UNKNOWN,
                "Service temporarily unavailable",
                response
            )
        
        return (
            EmailValidationStatus.UNKNOWN,
            f"Unhandled SMTP code: {code}",
            response
        )
    
    def _create_result(
        self, 
        email: str, 
        status: EmailValidationStatus,
        reason: str,
        mx_records: Optional[List[str]],
        smtp_response: Optional[str]
    ) -> Dict:
        """Create standardized result dictionary"""
        return {
            'email': email,
            'status': status,
            'reason': reason,
            'mx_records': mx_records,
            'smtp_response': smtp_response,
            'validated_at': datetime.now(UTC)
        }
