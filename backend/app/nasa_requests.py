"""One shared, bounded retry budget for a preview's SIA and Cutout requests."""
import time
import urllib.error
from email.utils import parsedate_to_datetime

from research import spherex

MAX_CANDIDATES = 10
MAX_REQUESTS = 16
REQUEST_SECONDS = 20
TOTAL_SECONDS = 120
MAX_ATTEMPTS = 3
MAX_WAIT = 15


class BudgetStopped(Exception):
    pass


def retry_after_seconds(value):
    if not value:
        return 0
    try:
        value = value.strip()
        if value.isdigit():
            return int(value)
        return max(0, parsedate_to_datetime(value).timestamp() - time.time())
    except (ValueError, TypeError, OverflowError, AttributeError):
        return 0


class RequestBudget:
    def __init__(self):
        self.deadline = time.monotonic() + TOTAL_SECONDS
        self.requests = 0
        self.not_before = 0
        self.stop_reason = None

    def check(self):
        if self.stop_reason:
            raise BudgetStopped(self.stop_reason)
        remaining = self.deadline - time.monotonic()
        wait = max(0, self.not_before - time.monotonic())
        if remaining <= 0:
            self.stop_reason = "deadline"
        elif self.requests >= MAX_REQUESTS:
            self.stop_reason = "request_limit"
        elif wait > MAX_WAIT or wait >= remaining:
            # Never shorten a server's Retry-After or bypass it on another URL.
            self.stop_reason = "retry_after"
        if self.stop_reason:
            raise BudgetStopped(self.stop_reason)
        if wait:
            time.sleep(wait)
        if time.monotonic() >= self.deadline:
            self.stop_reason = "deadline"
            raise BudgetStopped(self.stop_reason)

    def fetch(self, url, path, cap, events):
        for attempt in range(MAX_ATTEMPTS):
            self.check()
            self.requests += 1
            try:
                return spherex.fetch(url, path, cap, events,
                    timeout=min(REQUEST_SECONDS, self.deadline - time.monotonic()), deadline=self.deadline)
            except urllib.error.HTTPError as exc:
                if exc.code != 503:
                    raise
                delay = max(2 ** attempt, retry_after_seconds(exc.headers.get("Retry-After") if exc.headers else None))
                # Cooldown is host-wide within this preview, including when the
                # current candidate exhausts retries and we move to another one.
                self.not_before = time.monotonic() + delay
                if attempt + 1 == MAX_ATTEMPTS:
                    raise
