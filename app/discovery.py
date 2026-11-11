
import re

import httpx

from .config import get_settings
from .models import Prospect
from .treg import call_platform


def normalise_web(result):
    url = result.get("url", "")
    title = result.get("title", "")
    content = result.get("content", "")

    return Prospect(
        business_name=title[:160] or "Unverified business",
        platform="web",
        description=content[:1200],
        signal=title[:300],
        source_url=url,
        profile_url=url,
        evidence_confidence=2,
        raw=result,
    )


async def tavily_search(query, limit):
    s = get_settings()

    if not s.tavily_enabled or not s.tavily_api_key:
        return []

    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": s.tavily_api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": limit,
                "include_answer": False,
            },
        )

        response.raise_for_status()

        return [
            normalise_web(item)
            for item in response.json().get("results", [])
        ]


def normalise_instagram(profile):
    """Convert a Treg Instagram profile into an Amplify prospect."""

    if not isinstance(profile, dict):
        return None

    username = str(
        profile.get("username")
        or profile.get("user_name")
        or ""
    ).strip().lstrip("@")

    profile_url = (
        profile.get("profile_url")
        or profile.get("url")
        or profile.get("link")
        or ""
    )

    # Construct a profile URL only if the username is valid.
    if not profile_url and re.fullmatch(r"[A-Za-z0-9._]{1,30}", username):
        profile_url = f"https://www.instagram.com/{username}/"

    if not (
        isinstance(profile_url, str)
        and profile_url.startswith(("https://", "http://"))
    ):
        return None

    business_name = (
        profile.get("full_name")
        or profile.get("fullName")
        or profile.get("name")
        or username
        or "Unverified business"
    )

    description = (
        profile.get("biography")
        or profile.get("bio")
        or profile.get("description")
        or ""
    )
    website = (
        profile.get("external_url")
        or profile.get("website")
        or ""
    )
    return Prospect(
        business_name=str(business_name)[:160],
        platform="instagram",
        profile_url=profile_url,
        source_url=profile_url,
        website=str(website),
        description=str(description)[:1200],
        signal=str(description)[:300],
        evidence_confidence=2,
        raw=profile,
    )


def normalise_treg_result(item, platform):
    """Convert an existing generic Treg result into a prospect."""

    if not isinstance(item, dict):
        return None

    url = item.get("url")

    if not url:
        return None

    return Prospect(
        business_name=(
            item.get("business_name")
            or item.get("title")
            or "Unverified business"
        ),
        platform=platform,
        profile_url=item.get("profile_url") or url,
        website=item.get("website", ""),
        description=item.get("description", ""),
        signal=item.get("text") or item.get("title", ""),
        source_url=url,
        source_date=str(item.get("created_at", "")),
        evidence_confidence=2,
        raw=item,
    )


async def discover(query, platforms, limit):
    """Discover prospects from live sources without sending outreach."""

    found = []
    errors = []

    for platform in platforms:
        try:
            if platform == "youtube_direct":
                from .youtube import search_youtube

                found.extend(await search_youtube(query, limit))

            elif platform == "web":
                found.extend(await tavily_search(query, limit))

            else:
                raw = await call_platform(platform, query, limit)

                if not isinstance(raw, dict):
                    raise ValueError(
                        f"Unexpected {platform} response: expected dictionary"
                    )

                if raw.get("success") is False:
                    raise ValueError(
                        f"{platform} provider reported failure"
                    )

                if platform == "instagram":
                    results = raw.get("profiles", [])
                else:
                    results = raw.get("results", [])

                if not isinstance(results, list):
                    raise ValueError(
                        f"Unexpected {platform} results format"
                    )

                for item in results[:limit]:
                    if platform == "instagram":
                        prospect = normalise_instagram(item)
                    else:
                        prospect = normalise_treg_result(
                            item,
                            platform,
                        )

                    if prospect is not None:
                        found.append(prospect)

        except Exception as exc:
            errors.append({
                "platform": platform,
                "query": query,
                "error": str(exc),
            })

    return found, errors
