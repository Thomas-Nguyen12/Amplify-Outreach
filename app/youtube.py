"""Official YouTube Data API v3 prospect discovery (public metadata only).

Discovery is *evidence gathering*, not verification of buyer intent or permission
for outreach. Search results may describe people other than the channel owner.
No contact details or comments are collected and no YouTube messages are sent.
"""
import hashlib
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from .models import Prospect
from .config import get_settings

LOG = logging.getLogger(__name__)
API_ROOT = 'https://www.googleapis.com/youtube/v3'
# Choose one or two searches per hourly run; rotation covers all three segments.
YOUTUBE_QUERIES = [
    'small business owner struggling to post on social media',
    'indie startup founder content marketing challenges launch',
    'micro influencer need content ideas audience engagement',
    'independent ecommerce brand competitor social media trends',
    'small SaaS startup need social media content calendar',
    'creator struggling with content ideas trending topics',
]


class YouTubeAPIError(RuntimeError):
    pass


class YouTubeQuotaError(YouTubeAPIError):
    pass


def official_channel_url(channel_id: str) -> str:
    if not channel_id or not channel_id.startswith('UC'):
        raise ValueError('Invalid YouTube channel ID')
    return f'https://www.youtube.com/channel/{channel_id}'


def _pacific_day():
    return datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat()


def _reserve_search(settings):
    """Best-effort local process-safe quota ledger; ephemeral sandboxes reset it.

    Reserve *before* requests because unsuccessful YouTube requests may consume quota.
    A shared central limiter is required for multiple Daytona sandboxes/projects.
    """
    path = Path(settings.youtube_quota_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=30) as db:
        db.execute('CREATE TABLE IF NOT EXISTS youtube_search_usage (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        day = _pacific_day()
        row = db.execute('SELECT calls FROM youtube_search_usage WHERE day=?', (day,)).fetchone()
        count = row[0] if row else 0
        if count >= settings.youtube_max_searches_per_day:
            raise YouTubeQuotaError(f'Local YouTube search budget reached ({count}/{settings.youtube_max_searches_per_day}) on {day} PT')
        db.execute('INSERT INTO youtube_search_usage(day,calls) VALUES(?,1) '
                   'ON CONFLICT(day) DO UPDATE SET calls=calls+1', (day,))
        db.commit()
        LOG.info('youtube_search_reserved day=%s count=%d limit=%d', day, count+1, settings.youtube_max_searches_per_day)


def _extract_website(description: str) -> str:
    """Only use a clear HTTP(S) URL in channel-owner-provided description.

    Do not infer an official business website from video descriptions or titles.
    """
    import re
    for value in re.findall(r'https?://[^\s<>"\']+', description or ''):
        cleaned = value.rstrip('.,;)')
        host = (urlparse(cleaned).hostname or '').lower()
        if host and not any(host == h or host.endswith('.'+h) for h in
                            ('youtube.com','youtu.be','instagram.com','tiktok.com','x.com','twitter.com','facebook.com')):
            return cleaned
    return ''


async def _get(client, path, params, api_key):
    # Key is sent as an HTTP header, not logged or included in exception strings.
    try:
        response = await client.get(f'{API_ROOT}/{path}', params=params,
                                    headers={'X-goog-api-key': api_key})
    except httpx.RequestError as exc:
        raise YouTubeAPIError(f'YouTube network error: {type(exc).__name__}') from exc
    if response.status_code >= 400:
        try:
            error = response.json().get('error', {})
            message = str(error.get('message', 'Unspecified API error'))
            reasons = error.get('errors') or []
            reason = reasons[0].get('reason', 'unknown') if reasons and isinstance(reasons[0], dict) else 'unknown'
        except (ValueError, AttributeError, TypeError):
            message, reason = 'Unknown API error', 'unknown'
        # Error messages may contain user-controlled input or key material;
        # never echo the full raw response, URL, or credentials in logs.
        if 'referer' in message.lower():
            reason = 'HTTP_REFERRER_RESTRICTION'
            message = 'API key is restricted to websites; use a server-compatible key.'
        elif 'key' in message.lower():
            message = 'API key or permissions rejected; inspect Google Cloud configuration.'
        text = f'YouTube {path} failed (HTTP {response.status_code}, reason={reason}): {message[:200]}'
        if reason in ('quotaExceeded', 'dailyLimitExceeded', 'rateLimitExceeded') or response.status_code == 429:
            raise YouTubeQuotaError(text)
        raise YouTubeAPIError(text)
    try:
        return response.json()
    except ValueError as exc:
        raise YouTubeAPIError('YouTube returned invalid JSON') from exc


async def search_youtube(query: str, limit: int = 10, *, client=None, settings=None, track_quota=True) -> list[Prospect]:
    """One official search call plus batched channel/video enrichment calls.

    Search may return video or channel records. All candidate identities use the
    immutable YouTube channel URL, even when discovered via a video search.
    """
    settings = settings or get_settings()
    if not settings.youtube_enabled or not settings.youtube_api_key:
        raise YouTubeAPIError('Set YOUTUBE_ENABLED=true and YOUTUBE_API_KEY for direct search')
    if track_quota:
        _reserve_search(settings)
    owner = client is None
    if owner:
        client = httpx.AsyncClient(timeout=25)
    try:
        search = await _get(client, 'search', {
            'part': 'snippet', 'type': settings.youtube_search_type,
            'q': query, 'maxResults': max(1, min(limit, 50)),
            'safeSearch': 'moderate',
        }, settings.youtube_api_key)
        items = search.get('items', [])
        channel_ids = []
        video_ids = []
        for item in items:
            snippet = item.get('snippet') or {}
            obj_id = item.get('id') or {}
            channel_id = obj_id.get('channelId') or snippet.get('channelId')
            if channel_id and channel_id not in channel_ids:
                channel_ids.append(channel_id)
            if obj_id.get('videoId') and obj_id['videoId'] not in video_ids:
                video_ids.append(obj_id['videoId'])
        # One metadata request for up to 50 channels and another for 50 videos.
        channels = {}
        if channel_ids:
            detail = await _get(client, 'channels', {
                'part': 'snippet,statistics,contentDetails', 'id': ','.join(channel_ids[:50]),
                'maxResults': 50,
            }, settings.youtube_api_key)
            channels = {x['id']: x for x in detail.get('items', []) if x.get('id')}
        videos = {}
        if video_ids and settings.youtube_enrich_videos:
            detail = await _get(client, 'videos', {
                'part': 'snippet,statistics', 'id': ','.join(video_ids[:50]),
                'maxResults': 50,
            }, settings.youtube_api_key)
            videos = {x['id']: x for x in detail.get('items', []) if x.get('id')}
        leads = []
        for item in items:
            snippet = item.get('snippet') or {}
            obj_id = item.get('id') or {}
            channel_id = obj_id.get('channelId') or snippet.get('channelId')
            # Never create an unverified identity using a video ID.
            channel = channels.get(channel_id)
            if not channel or not channel_id:
                continue
            detail = channel.get('snippet') or {}
            stats = channel.get('statistics') or {}
            video_id = obj_id.get('videoId')
            video = videos.get(video_id) or {}
            video_detail = video.get('snippet') or {}
            channel_url = official_channel_url(channel_id)
            channel_description = detail.get('description') or ''
            # Keep video evidence separate from channel identity and description.
            video_title = (video_detail.get('title') or snippet.get('title') or '') if video_id else ''
            video_url = f'https://www.youtube.com/watch?v={video_id}' if video_id else ''
            signal = (f'Public YouTube video: {video_title}' if video_title else
                      f'Public channel: {detail.get("title", "")}')
            # Source date comes from video evidence when available; channel creation
            # alone is not an indication of recent activity.
            source_date = (video_detail.get('publishedAt') or snippet.get('publishedAt') or '') if video_id else ''
            leads.append(Prospect(
                business_name=detail.get('title') or 'Unverified YouTube channel',
                platform='youtube_direct', profile_url=channel_url,
                website=_extract_website(channel_description),
                source_url=video_url or channel_url,
                source_date=source_date,
                description=channel_description[:1200],
                signal=signal[:300], evidence_confidence=3 if video_id else 2,
                raw={'channel_id':channel_id, 'video_id':video_id,
                     'subscriber_count':stats.get('subscriberCount'),
                     'video_count':stats.get('videoCount'),
                     'video_title':video_title, 'video_url':video_url,
                     'video_published_at':source_date,
                     'video_view_count':(video.get('statistics') or {}).get('viewCount'),
                     'query':query, 'source':'youtube_data_api_v3',
                     'is_verified_business':False,
                     'note':'Channel identity and buying intent are not verified by YouTube search'},
            ))
        return leads
    finally:
        if owner:
            await client.aclose()


def scheduled_youtube_queries(max_searches: int, *, hour=None):
    """Rotate selected segment queries across hourly runs without excess calls."""
    if hour is None:
        hour = int(datetime.now(timezone.utc).timestamp() // 3600)
    return [YOUTUBE_QUERIES[(hour * max_searches + n) % len(YOUTUBE_QUERIES)]
            for n in range(max_searches)]
