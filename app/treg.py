
"""Treg API integration for live social-media discovery.

Instagram uses the verified ScrapeCreators profile-search operation
with GET and a `query` URL parameter.

Other platforms retain the original POST/JSON request format until
their individual endpoint schemas have been verified.
"""

import asyncio
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from .config import get_settings


PLATFORMS = [
    "instagram",
    "tiktok",
    "linkedin",
    "reddit",
    "x",
    "youtube",
]

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
MAX_RETRY_DELAY = 30


class TregError(RuntimeError):
    """Error communicating with a Treg provider."""


def retry_delay(response: httpx.Response, attempt: int) -> float:
    """Calculate retry delay, respecting Retry-After when provided."""

    retry_after = response.headers.get("Retry-After")

    if retry_after:
        try:
            seconds = float(retry_after)

            if seconds >= 0:
                return min(MAX_RETRY_DELAY, seconds)

        except ValueError:
            try:
                retry_date = parsedate_to_datetime(retry_after)

                if retry_date.tzinfo is None:
                    retry_date = retry_date.replace(
                        tzinfo=timezone.utc
                    )

                seconds = (
                    retry_date - datetime.now(timezone.utc)
                ).total_seconds()

                return min(MAX_RETRY_DELAY, max(0, seconds))

            except (TypeError, ValueError, OverflowError):
                pass

    # Exponential backoff with a small amount of jitter.
    delay = 2 ** (attempt + 1)
    jitter = random.uniform(0, 0.5)

    return min(MAX_RETRY_DELAY, delay + jitter)


async def call_platform(platform: str, query: str, limit: int):
    """Call a configured Treg endpoint for a single discovery query."""

    settings = get_settings()

    if not settings.treg_enabled:
        raise TregError("Treg integration is disabled")

    if not settings.treg_token:
        raise TregError("TREG_TOKEN is not configured")

    if platform not in PLATFORMS:
        raise TregError(f"Unsupported Treg platform: {platform}")

    endpoint = settings.endpoint_for(platform)

    if not endpoint:
        raise TregError(
            f"No verified Treg endpoint configured for {platform}"
        )

    # Treg endpoint settings contain operation IDs, not full URLs.
    endpoint = endpoint.strip().strip("/")

    if "://" in endpoint:
        raise TregError(
            "Treg endpoint must be an operation ID, not a full URL"
        )

    url = (
        f"{settings.treg_base_url.rstrip('/')}/call/{endpoint}"
    )

    headers = {
        settings.treg_auth_header: (
            f"{settings.treg_auth_prefix}{settings.treg_token}"
        ),
    }

    async with httpx.AsyncClient(timeout=45) as client:

        for attempt in range(MAX_ATTEMPTS):

            if platform == "instagram":
                # Verified ScrapeCreators Instagram search format.
                response = await client.get(
                    url,
                    headers=headers,
                    params={"query": query},
                )

            else:
                # Existing request format for other platforms.
                # Verify the upstream schema before enabling them.
                response = await client.post(
                    url,
                    headers={
                        **headers,
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": query,
                        "limit": limit,
                    },
                )

            if response.status_code not in RETRYABLE_STATUS_CODES:
                response.raise_for_status()
                return response.json()

            if attempt == MAX_ATTEMPTS - 1:
                response.raise_for_status()

            delay = retry_delay(response, attempt)

            print(
                f"Treg {platform}: HTTP {response.status_code}; "
                f"retrying in {delay:.1f}s "
                f"(attempt {attempt + 1}/{MAX_ATTEMPTS})",
                flush=True,
            )

            await asyncio.sleep(delay)

    raise TregError(
        f"Treg {platform} request failed after {MAX_ATTEMPTS} attempts"
    )
