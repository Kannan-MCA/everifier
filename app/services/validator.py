import re
import dns.resolver
import smtplib
import socket
from typing import Dict, List, Optional, Tuple
from datetime import datetime, UTC
from ..schemas import EmailValidationStatus

class EmailValidatorService:
    
    # Regex pattern for email format validation
    EMAIL_PATTERN = re.compile(
        r'^[a-zA-Z0-9_+&*-]+(?:\.[a-zA-Z0-9_+&*-]+)*@(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,7}$'
    )
    
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
    
    def __init__(self):
        pass
    
    def validate_email(self, email: str) -> Dict:
        """Main validation method"""
        email = email.lower().strip()
        
        # Step 1: Format validation
        if not self._is_valid_format(email):
            return {
                'email': email,
                'status': EmailValidationStatus.INVALID,
                'reason': 'Invalid email format',
                'mx_records': None,
                'smtp_response': None,
                'validated_at': datetime.now(UTC)
            }
        
        domain = self._extract_domain(email)
        
        # Step 2: Check blocklist
        if domain in self.BLOCKLISTED_DOMAINS:
            return {
                'email': email,
                'status': EmailValidationStatus.BLOCKLISTED,
                'reason': 'Domain is blocklisted',
                'mx_records': None,
                'smtp_response': None,
                'validated_at': datetime.now(UTC)
            }
        
        # Step 3: Check disposable
        if domain in self.DISPOSABLE_DOMAINS:
            return {
                'email': email,
                'status': EmailValidationStatus.DISPOSABLE,
                'reason': 'Disposable email address',
                'mx_records': None,
                'smtp_response': None,
                'validated_at': datetime.now(UTC)
            }
        
        # Step 4: MX record lookup
        mx_records = self._get_mx_records(domain)
        if not mx_records:
            return {
                'email': email,
                'status': EmailValidationStatus.INVALID,
                'reason': 'No MX records found for domain',
                'mx_records': None,
                'smtp_response': None,
                'validated_at': datetime.now(UTC)
            }
        
        # Step 5: SMTP validation
        status, reason, smtp_response = self._validate_via_smtp(email, mx_records)
        
        return {
            'email': email,
            'status': status,
            'reason': reason,
            'mx_records': mx_records,
            'smtp_response': smtp_response,
            'validated_at': datetime.now(UTC)
        }
    
    def _is_valid_format(self, email: str) -> bool:
        """Validate email format using regex"""
        return bool(self.EMAIL_PATTERN.match(email))
    
    def _extract_domain(self, email: str) -> str:
        """Extract domain from email address"""
        return email.split('@')[1]
    
    def _get_mx_records(self, domain: str) -> Optional[List[str]]:
        """Get MX records for domain"""
        try:
            mx_records = dns.resolver.resolve(domain, 'MX')
            return [str(r.exchange).rstrip('.') for r in mx_records]
        except Exception:
            return None
    
    def _validate_via_smtp(self, email: str, mx_records: List[str]) -> Tuple[EmailValidationStatus, str, Optional[str]]:
        """Validate email via SMTP RCPT TO command"""
        
        for mx_host in mx_records:
            try:
                status, reason, response = self._connect_and_validate(email, mx_host)
                return status, reason, response
            except Exception:
                continue
        
        return (
            EmailValidationStatus.UNKNOWN,
            "Could not connect to any MX server",
            None
        )
    
    def _connect_and_validate(self, email: str, mx_host: str) -> Tuple[EmailValidationStatus, str, str]:
        """Connect to SMTP server and validate email"""
        
        smtp = None
        try:
            # Connect with timeout
            smtp = smtplib.SMTP(timeout=30)
            smtp.connect(mx_host, 25)
            
            # EHLO
            smtp.ehlo('validator.local')
            
            # MAIL FROM
            smtp.mail('verify@validator.local')
            
            # RCPT TO - This checks if mailbox exists
            code, message = smtp.rcpt(email)
            response = f"{code} {message.decode('utf-8', errors='ignore')}"
            
            smtp.quit()
            
            # Parse RCPT TO response
            return self._parse_rcpt_response(code, response)
            
        except smtplib.SMTPServerDisconnected:
            return (
                EmailValidationStatus.UNKNOWN,
                "Server disconnected during validation",
                "Connection lost"
            )
        except smtplib.SMTPException as e:
            error_str = str(e)
            # Extract SMTP error code and message
            if hasattr(e, 'smtp_code'):
                code = e.smtp_code
                message = e.smtp_error.decode('utf-8', errors='ignore') if hasattr(e, 'smtp_error') else error_str
                response = f"{code} {message}"
                return self._parse_rcpt_response(code, response)
            
            return (
                EmailValidationStatus.UNKNOWN,
                f"SMTP error: {error_str}",
                error_str
            )
        except socket.timeout:
            return (
                EmailValidationStatus.UNKNOWN,
                "Connection timeout",
                "Timeout"
            )
        except Exception as e:
            return (
                EmailValidationStatus.UNKNOWN,
                f"Connection error: {str(e)}",
                str(e)
            )
        finally:
            if smtp:
                try:
                    smtp.quit()
                except:
                    pass
    
    def _parse_rcpt_response(self, code: int, response: str) -> Tuple[EmailValidationStatus, str, str]:
        """Parse RCPT TO response to determine email status"""
        
        response_lower = response.lower()
        
        # 250 = Success - Mailbox exists
        if code == 250:
            # Check for catch-all indicators
            if any(keyword in response_lower for keyword in [
                'catch-all', 'catch all', 'accept all', 'accepts all',
                'relay', 'wildcard'
            ]):
                return (
                    EmailValidationStatus.CATCH_ALL,
                    "Domain accepts all emails (catch-all)",
                    response
                )
            
            return (
                EmailValidationStatus.VALID,
                "Email address is valid",
                response
            )
        
        # 550 = Mailbox unavailable / User not found
        if code == 550:
            # Check for user/mailbox not found indicators
            if any(keyword in response_lower for keyword in [
                'user not found', 'user unknown', 'no such user',
                'mailbox not found', 'mailbox unavailable',
                'recipient rejected', 'address rejected',
                'does not exist', 'invalid recipient',
                'unknown user', 'no mailbox', '5.1.1',
                'mailbox does not exist', 'user does not exist'
            ]):
                return (
                    EmailValidationStatus.USER_NOT_FOUND,
                    "Mailbox does not exist (inbox not attached)",
                    response
                )
            
            # Other 550 errors
            return (
                EmailValidationStatus.INVALID,
                f"Email rejected by server: {response}",
                response
            )
        
        # 551 = User not local
        if code == 551:
            return (
                EmailValidationStatus.USER_NOT_FOUND,
                "User not local to server",
                response
            )
        
        # 552/553 = Mailbox full or policy restriction
        if code in [552, 553]:
            return (
                EmailValidationStatus.INVALID,
                "Mailbox full or policy restriction",
                response
            )
        
        # 450/451 = Temporary failure (greylisting, rate limiting)
        if code in [450, 451]:
            return (
                EmailValidationStatus.UNKNOWN,
                "Temporary failure - greylisting or rate limit",
                response
            )
        
        # 421 = Service not available
        if code == 421:
            return (
                EmailValidationStatus.UNKNOWN,
                "Service temporarily unavailable",
                response
            )
        
        # Default: Unknown
        return (
            EmailValidationStatus.UNKNOWN,
            f"Unable to determine status: {response}",
            response
        )
