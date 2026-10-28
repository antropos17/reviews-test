"""Bounded retries for idempotent reads from external services."""
import time
import requests


def get(url, *, attempts=3, delay=1, **kwargs):
    for attempt in range(attempts):
        try:
            response = requests.get(url, **kwargs)
            if getattr(response, 'status_code', 200) not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                return response
        except (requests.Timeout, requests.ConnectionError):
            if attempt == attempts - 1:
                raise
        time.sleep(delay * (2 ** attempt))
