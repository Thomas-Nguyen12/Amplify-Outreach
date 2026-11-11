"""Optional live request; never called by the ordinary pytest suite."""
import asyncio
import os
import pytest

@pytest.mark.skipif(os.environ.get('RUN_YOUTUBE_SMOKE') != 'yes',
                    reason='Requires RUN_YOUTUBE_SMOKE=yes and a real YouTube API key')
def test_youtube_live_public_metadata():
    from app.config import get_settings
    from app.youtube import search_youtube
    get_settings.cache_clear()
    s=get_settings()
    if not (s.youtube_enabled and s.youtube_api_key):
        pytest.fail('Set YOUTUBE_ENABLED=true and YOUTUBE_API_KEY; no requests sent')
    # Single search request + enrichment. Does not store leads or send outreach.
    items=asyncio.run(search_youtube('indie founder building SaaS', 3))
    assert isinstance(items,list)
    for item in items:
        assert item.platform=='youtube_direct'
        assert item.profile_url.startswith('https://www.youtube.com/channel/UC')
        assert item.raw.get('channel_id')
