# app/services/catchall.py
import asyncio
import random
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

class CatchAllDetector:
    """
    Asynchronous catch-all detection logic.
    Runs multiple RCPT TO tests per MX host with randomized delays
    and applies statistical threshold to decide catch-all presence.
    """

    def __init__(
        self,
        smtp_verify_func,          # Async function(mx_host:str, recipient:str) -> Tuple[int, bytes]
        attempts_per_mx: int = 3,
        positive_threshold: float = 0.8,
        delay_range: Tuple[float, float] = (0.2, 1.0)
    ):
        self.smtp_verify = smtp_verify_func
        self.attempts_per_mx = attempts_per_mx
        self.positive_threshold = positive_threshold
        self.delay_range = delay_range

    def generate_fake_email(self, domain: str) -> str:
        """Create a random fake email for catch-all testing."""
        from string import ascii_lowercase, digits
        random_string = ''.join(random.choices(ascii_lowercase + digits, k=20))
        return f"{random_string}@{domain}"

    async def check_catch_all(self, mx_hosts: List[str], domain: str) -> bool:
        """
        Perform catch-all detection by sending multiple RCPT TO commands
        with random fake emails to each MX host.
        Returns True if catch-all likely present based on threshold.
        """
        positive_responses = 0
        total_attempts = len(mx_hosts) * self.attempts_per_mx

        logger.info(f"Starting catch-all detection for domain '{domain}' on MX hosts: {mx_hosts}")

        for mx_host in mx_hosts:
            for _ in range(self.attempts_per_mx):
                fake_email = self.generate_fake_email(domain)
                try:
                    code, _ = await self.smtp_verify(mx_host, fake_email)
                    logger.debug(f"Catch-all test on {mx_host} for {fake_email}: SMTP code {code}")
                    if code == 250:
                        positive_responses += 1
                except Exception as e:
                    logger.warning(f"Error during catch-all SMTP check on {mx_host}: {e}")
                await asyncio.sleep(random.uniform(*self.delay_range))

        ratio = positive_responses / total_attempts if total_attempts > 0 else 0.0
        logger.info(f"Catch-all detection: {positive_responses}/{total_attempts} positive responses. Ratio={ratio:.2f}")

        return ratio >= self.positive_threshold


# Example SMTP verification async function signature you must provide from your validator:
# async def smtp_verify(mx_host: str, recipient: str) -> Tuple[int, bytes]:
#     ...
#     return (smtp_code, smtp_message_bytes)