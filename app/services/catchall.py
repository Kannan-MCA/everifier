import asyncio
import random
import logging
from typing import List, Tuple, Set

logger = logging.getLogger(__name__)

class CatchAllDetector:
    def __init__(
        self,
        smtp_verify_func,
        attempts_per_mx: int = 3,
        positive_threshold: float = 0.8,
        delay_range: Tuple[float, float] = (0.2, 1.0),
        exclude_domains: Set[str] = None  # Default is None, not set directly!
    ):
        if exclude_domains is None:
            exclude_domains = {"gmail.com", "yahoo.com", "outlook.com"}  # Assign default inside constructor
        self.exclude_domains = exclude_domains

    def generate_fake_email(self, domain: str) -> str:
        """Create a random fake email for catch-all testing."""
        from string import ascii_lowercase, digits
        random_string = ''.join(random.choices(ascii_lowercase + digits, k=20))
        return f"{random_string}@{domain}"

    async def check_catch_all(self, mx_hosts: List[str], domain: str) -> bool:
       
        if domain in self.exclude_domains:
            logger.info(f"Skipping catch-all detection for excluded domain '{domain}'")
            return False

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
