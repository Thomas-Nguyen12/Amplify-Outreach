import json
"""YouTube direct connector tests: all HTTP responses are mocked."""
import asyncio
import sqlite3
import httpx
import pytest
from app.config import Settings, get_settings
from app.surreal_store import lead_identity
from app import youtube, pipeline
from app.database import init_db, rows

CHANNEL_ID = 'UC1234567890sampleChannel'
VIDEO_ID = 'v12345'


def mocked_client(calls):
    def respond(request):
        path = request.url.path.split('/')[-1]
        calls.append((path, dict(request.url.params)))
        assert request.headers.get('X-goog-api-key') == 'test-only-secret'
        if path == 'search':
            return httpx.Response(200, json={'items': [
                {'id': {'kind':'youtube#video', 'videoId':VIDEO_ID},
                 'snippet':{'channelId':CHANNEL_ID, 'title':'Daily competitor monitoring for indie founders',
                            'publishedAt':'2026-11-10T09:00:00Z'}}]})
        if path == 'channels':
            return httpx.Response(200, json={'items':[{'id':CHANNEL_ID,
                'snippet':{'title':'Indie Micro SaaS founder',
                           'description':'Bootstrapped startup looking for competitor analysis and daily market research https://indie.example'},
                'statistics':{'subscriberCount':'1200','videoCount':'21'}}]})
        if path == 'videos':
            return httpx.Response(200, json={'items':[{'id':VIDEO_ID,
                'snippet':{'title':'Daily competitor monitoring for indie founders',
                           'publishedAt':'2026-11-10T09:00:00Z'},
                'statistics':{'viewCount':'450'}}]})
        raise AssertionError(f'Unexpected path: {path}')
    return httpx.AsyncClient(transport=httpx.MockTransport(respond))


def settings(tmp_path, **changes):
    return Settings(_env_file=None, youtube_enabled=True, youtube_api_key='test-only-secret',
                    youtube_quota_db_path=str(tmp_path/'ledger.sqlite3'), **changes)


def test_youtube_search_enriches_video_and_channel_and_normalises(tmp_path):
    calls=[]
    async def run():
        async with mocked_client(calls) as client:
            return await youtube.search_youtube('indie founder', limit=5, client=client, settings=settings(tmp_path))
    leads=asyncio.run(run())
    assert len(leads)==1
    lead=leads[0]
    assert lead.platform=='youtube_direct'
    assert lead.website=='https://indie.example'
    assert lead.profile_url==f'https://www.youtube.com/channel/{CHANNEL_ID}'
    assert lead.source_url==f'https://www.youtube.com/watch?v={VIDEO_ID}'
    assert lead.raw['subscriber_count']=='1200'
    assert lead.source_date=='2026-11-10T09:00:00Z'
    assert lead.raw['is_verified_business'] is False
    assert [name for name,_ in calls]==['search','channels','videos']
    assert calls[0][1]['type']=='video'
    assert calls[0][1]['maxResults']=='5'


def test_channel_identity_does_not_change_when_website_changes(tmp_path):
    async def run():
        async with mocked_client([]) as client:
            return (await youtube.search_youtube('test', client=client, settings=settings(tmp_path)))[0]
    lead=asyncio.run(run())
    first=lead_identity(lead)
    lead.website='https://different-official-site.example'
    assert lead_identity(lead)==first
    assert first.endswith(CHANNEL_ID)


def test_search_budget_reservation_and_limit(tmp_path):
    cfg=settings(tmp_path, youtube_max_searches_per_day=1)
    async def run():
        async with mocked_client([]) as client:
            await youtube.search_youtube('first',client=client,settings=cfg)
            with pytest.raises(youtube.YouTubeQuotaError, match='budget reached'):
                await youtube.search_youtube('second',client=client,settings=cfg)
    asyncio.run(run())
    with sqlite3.connect(cfg.youtube_quota_db_path) as db:
        assert db.execute('SELECT calls FROM youtube_search_usage').fetchone()[0]==1


def test_invalid_key_or_api_error_does_not_leak_secret(tmp_path):
    cfg=settings(tmp_path)
    client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(403,text='secret')))
    async def run():
        async with client:
            with pytest.raises(youtube.YouTubeAPIError) as error:
                await youtube.search_youtube('q',client=client,settings=cfg)
            assert 'test-only-secret' not in str(error.value)
    asyncio.run(run())


def test_channel_search_without_video_enrichment(tmp_path):
    cfg=settings(tmp_path,youtube_search_type='channel')
    async def run():
        def respond(req):
            if req.url.path.endswith('/search'):
                return httpx.Response(200,json={'items':[{'id':{'channelId':CHANNEL_ID},
                    'snippet':{'channelId':CHANNEL_ID,'title':'Founder video'}}]})
            return httpx.Response(200,json={'items':[{'id':CHANNEL_ID,'snippet':{'title':'Small brand shop',
                        'description':'independent business looking for daily trends'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await youtube.search_youtube('shop',client=client,settings=cfg)
    lead=asyncio.run(run())[0]
    assert lead.source_url==lead.profile_url
    assert lead.source_date==''
    assert lead.raw['video_id'] is None


def test_query_rotation_budget():
    a=youtube.scheduled_youtube_queries(2,hour=0)
    b=youtube.scheduled_youtube_queries(2,hour=1)
    assert len(a)==len(b)==2
    assert a!=b
    assert all(q in youtube.YOUTUBE_QUERIES for q in a+b)


def test_pipeline_youtube_to_surreal_to_minds_no_duplicate(tmp_path,monkeypatch):
    """Mock YouTube + Surreal + HelloMinds; exercise actual live processing."""
    from tests.test_persistence_end_to_end import FakePersistentStore
    store=FakePersistentStore()
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'one.sqlite3'))
    monkeypatch.setenv('YOUTUBE_ENABLED','true')
    monkeypatch.setenv('YOUTUBE_API_KEY','fake')
    monkeypatch.setenv('TAVILY_ENABLED','false')
    monkeypatch.setenv('TREG_ENABLED','false')
    monkeypatch.setenv('SURREAL_ENABLED','true')
    monkeypatch.setenv('MINDS_ENABLED','true')
    monkeypatch.setenv('MINDS_MAX_RESEARCH_PER_RUN','2')
    get_settings.cache_clear()
    init_db()
    monkeypatch.setattr(pipeline,'enabled_store',lambda:store)
    research_calls=[]
    async def mocked_minds(lead):
        research_calls.append(lead)
        return {'mind_id':'mock-mind','alias':'research','reply':json.dumps({'status':'completed','summary':'Synthetic research result only','content_challenges':[],'limitations':[],'evidence':[{'source_url':f'https://www.youtube.com/channel/{CHANNEL_ID}','quote':'looking for competitor analysis and daily market research'}]})}
    monkeypatch.setattr(pipeline,'research_lead',mocked_minds)
    async def mocked_discover(query,platforms,limit):
        assert platforms==['youtube_direct']
        from app.models import Prospect
        return [Prospect(platform='youtube_direct',business_name='Indie Micro SaaS founder',
              profile_url=f'https://www.youtube.com/channel/{CHANNEL_ID}',
              website='https://indie.example',source_url=f'https://www.youtube.com/watch?v={VIDEO_ID}',
              source_date='2026-11-10',evidence_confidence=4,
              description='Bootstrapped startup looking for competitor analysis and daily market research',
              signal='Daily competitor monitoring for indie founders')],[]
    monkeypatch.setattr(pipeline,'discover',mocked_discover)
    try:
        first=asyncio.run(pipeline.run_pipeline(['test query'],['youtube_direct'],5,70))
        assert first['saved']==first['qualified']==first['drafts']==first['researched']==1
        assert len(research_calls)==1
        from app.surreal_store import canonical_identity
        identity=canonical_identity(f'https://www.youtube.com/channel/{CHANNEL_ID}')
        assert store.get_prospect(identity)
        assert json.loads(store.get_research(identity)['reply'])['summary']=='Synthetic research result only'
        assert store.tables[('outreach_drafts',identity)]['sent'] is False
        monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'fresh-daytona.sqlite3'))
        get_settings.cache_clear()
        init_db()
        second=asyncio.run(pipeline.run_pipeline(['test query'],['youtube_direct'],5,70))
        assert second['already_known']==1
        assert second['saved']==second['drafts']==second['researched']==0
        assert not rows('SELECT * FROM drafts')
    finally:
        get_settings.cache_clear()
