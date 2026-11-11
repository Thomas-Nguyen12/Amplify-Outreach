"""Read-only live YouTube API smoke test; one search call, no database writes."""
import argparse
import asyncio
from app.config import get_settings
from app.youtube import search_youtube

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--query', default='indie founder building SaaS startup')
    parser.add_argument('--limit', type=int, default=3)
    args = parser.parse_args()
    settings = get_settings()
    if not settings.youtube_enabled or not settings.youtube_api_key:
        raise SystemExit('Set YOUTUBE_ENABLED=true and YOUTUBE_API_KEY in .env')
    items = await search_youtube(args.query, args.limit)
    print('YouTube public-data search returned', len(items), 'prospect candidates')
    for item in items:
        print({'name':item.business_name, 'channel':item.profile_url,
               'evidence':item.source_url, 'published':item.source_date})
    print('This does NOT verify businesses or contact anyone.')

if __name__ == '__main__':
    asyncio.run(main())
