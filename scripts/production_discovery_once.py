
"""One live discovery and research run. No email dispatch."""

import asyncio
import json

from app.config import get_settings
from app.outreach import configure_status
from app.pipeline import run_pipeline
from app.surreal_store import enabled_store
from app.treg import PLATFORMS

async def main():
    s = get_settings()

    assert s.surreal_enabled and s.surreal_database == "main"
    assert s.discovery_mode == "live_search"
    assert s.youtube_enabled and s.youtube_api_key
    assert s.treg_enabled and s.treg_token
    assert s.minds_enabled
    assert s.minds_max_research_per_run <= 2
    assert not s.outreach_autosend_enabled
    assert not configure_status()["ready"]

    store = enabled_store()
    assert store is not None
    store.ping()

    treg = [
        p for p in PLATFORMS
        if p in {"instagram", "tiktok", "reddit"}
        and s.endpoint_for(p)
    ]
    assert treg, "No configured Treg platform"

    platforms = ["youtube_direct", treg[0]]
    print("Starting live production discovery")
    print("Platforms:", platforms)
    print("Database: main")
    print("Email sending: disabled", flush=True)

    result = await run_pipeline(
        queries=["coffee shop"],
        platforms=platforms,
        limit=3,
        threshold=s.minimum_lead_score,
    )

    summary = {k: v for k, v in result.items() if k != "leads"}
    print(json.dumps(summary, indent=2, default=str))

if __name__ == "__main__":
    asyncio.run(main())
