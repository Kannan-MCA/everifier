#!/usr/bin/env python3
import smtplib
import dns.resolver
import socket
import re
import ssl
import random
import string
import time

def smtp_check(mx_host, from_email, rcpt_email, retry_count=2, delay=3):
    """
    Open a new SMTP session and perform RCPT TO with retry logic.
    Uses TLS with certificate verification disabled (safe for testing).
    Returns (code, message).
    """
    for attempt in range(retry_count):
        try:
            # Increase timeout for slow servers
            with smtplib.SMTP(mx_host, 25, timeout=30) as server:
                server.set_debuglevel(0)  # Set to 1 for verbose output
                server.ehlo_or_helo_if_needed()

                # TLS section — disable certificate verification
                try:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    server.starttls(context=ctx)
                    server.ehlo()
                except Exception as e:
                    print(f"  ⚠ Skipping TLS: {e}")

                # Run MAIL FROM and RCPT TO
                server.mail(from_email)
                code, msg = server.rcpt(rcpt_email)
                return (code, msg)
                
        except smtplib.SMTPServerDisconnected as e:
            if attempt < retry_count - 1:
                print(f"  ⏳ Connection disconnected, retrying in {delay}s... (attempt {attempt + 1}/{retry_count})")
                time.sleep(delay)
                continue
            return (0, f"Connection disconnected after {retry_count} attempts: {e}".encode())
            
        except socket.timeout as e:
            if attempt < retry_count - 1:
                print(f"  ⏳ Timeout, retrying in {delay}s... (attempt {attempt + 1}/{retry_count})")
                time.sleep(delay)
                continue
            return (0, f"Connection timeout after {retry_count} attempts: {e}".encode())
            
        except smtplib.SMTPConnectError as e:
            return (0, f"Connection refused: {e}".encode())
            
        except Exception as e:
            if attempt < retry_count - 1:
                print(f"  ⏳ Error occurred, retrying in {delay}s... (attempt {attempt + 1}/{retry_count})")
                time.sleep(delay)
                continue
            return (0, str(e).encode())
    
    return (0, b"Max retries exceeded")


def get_mx_records(domain, max_records=3):
    """
    Get MX records sorted by priority.
    Returns list of MX hosts (up to max_records).
    """
    try:
        mx_records = sorted(
            dns.resolver.resolve(domain, 'MX'),
            key=lambda r: r.preference
        )
        return [str(mx.exchange).strip('.') for mx in mx_records[:max_records]]
    except Exception as e:
        return None, str(e)


def verify_email(target_email, from_email, skip_catchall=False):
    """Verify mailbox & classify as Valid, Catch‑All, Invalid, Unknown."""
    pattern = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
    if not re.match(pattern, target_email):
        return {"email": target_email, "status": "Invalid", "reason": "Bad syntax"}

    # Resolve MX records
    domain = target_email.split('@')[1]
    print(f"\n🔍 Resolving MX records for {domain}...")
    
    mx_hosts = get_mx_records(domain)
    if mx_hosts is None or not mx_hosts:
        return {"email": target_email, "status": "Unknown", "reason": f"DNS lookup failed: {mx_hosts}"}
    
    print(f"✅ Found {len(mx_hosts)} MX record(s): {mx_hosts[0]}")

    # Try each MX host until one succeeds
    code_real = 0
    msg_real = b"No MX responded"
    
    for mx_host in mx_hosts:
        print(f"📧 Testing mailbox via {mx_host}...")
        code_real, msg_real = smtp_check(mx_host, from_email, target_email, retry_count=2, delay=3)
        
        if code_real != 0:  # Got a definitive response
            break
        else:
            print(f"  ⚠ {mx_host} failed, trying next MX...")
            time.sleep(2)  # Brief delay before trying next MX
    
    # If real check failed on all MX hosts
    if code_real == 0:
        return {
            "email": target_email,
            "status": "Unknown",
            "reason": f"All MX servers unresponsive: {msg_real.decode(errors='ignore')}"
        }

    # Skip catch-all check if requested (faster)
    if skip_catchall:
        if code_real == 250:
            status = "Valid (catch-all not tested)"
            reason = "Mailbox accepted (250 OK)"
        elif code_real in (550, 551, 553, 554):
            status = "Invalid"
            reason = f"Server rejected ({code_real})"
        else:
            status = "Unknown"
            reason = f"Unhandled SMTP code: {code_real}"
        
        return {"email": target_email, "status": status, "reason": reason}

    # Fake mailbox test for catch‑all detection
    print(f"🎭 Testing for catch-all...")
    fake = ''.join(random.choices(string.ascii_lowercase + string.digits, k=15))
    fake_email = f"{fake}@{domain}"
    code_fake, msg_fake = smtp_check(mx_hosts[0], from_email, fake_email, retry_count=1, delay=2)

    # Classification logic
    if code_real == 250 and code_fake == 250:
        status = "Catch‑All"
        reason = "Server accepts all recipients (fake also 250 OK)"
    elif code_real == 250:
        status = "Valid"
        reason = "Mailbox accepted (250 OK)"
    elif code_real in (550, 551, 553, 554):
        status = "Invalid"
        reason = f"Server rejected ({code_real})"
    else:
        status = "Unknown"
        reason = f"Unhandled SMTP code: {code_real} - {msg_real.decode(errors='ignore')}"

    return {"email": target_email, "status": status, "reason": reason}


if __name__ == "__main__":
    print("\n" + "="*60)
    print("  SMTP Email Verifier with Retry & Multiple MX Support")
    print("="*60 + "\n")
    
    from_addr = input("Enter FROM email (used as MAIL FROM): ").strip()
    target = input("Enter email to verify: ").strip()
    
    # Optional: Skip catch-all check for faster verification
    skip_catchall_input = input("Skip catch-all check? (y/N): ").strip().lower()
    skip_catchall = skip_catchall_input == 'y'

    print("\n" + "-"*60)
    result = verify_email(target, from_addr, skip_catchall=skip_catchall)
    
    print("\n" + "="*60)
    print("  RESULT SUMMARY")
    print("="*60)
    print(f"Email   : {result['email']}")
    print(f"Status  : {result['status']}")
    print(f"Reason  : {result['reason']}")
    print("="*60 + "\n")
