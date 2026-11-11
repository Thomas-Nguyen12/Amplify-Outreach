import asyncio
import pytest
from app.config import get_settings
from app.models import Prospect, RunRequest
from app.scoring import score_item
from app.hellominds import research_prompt
from app.pipeline import run_pipeline
from app.targeting import DEFAULT_QUERIES


def test_confirmed_default_settings():
    s=get_settings()
    assert s.discovery_mode=='live_search'
    assert s.target_segments=='small_business,startup,influencer'
    assert s.subscription_price_gbp=='7'
    assert s.report_frequency=='daily'
    assert any('influencer' in q for q in DEFAULT_QUERIES)
    assert RunRequest().platforms==[]


def test_influencer_segment_and_daily_subscription():
    p=Prospect(business_name='Independent content creator influencer',platform='web',
      source_url='https://example.com/creator', website='https://example.com',
      description='Looking for daily social trends, content ideas and audience insights',
      signal='Need help with content planning')
    score_item(p)
    assert p.segment=='influencer'
    assert p.qualified
    prompt=research_prompt({'business_name':p.business_name})
    assert 'DAILY' in prompt and '£7/MONTH' in prompt


def test_live_search_without_credentials_fails_clearly(monkeypatch):
    monkeypatch.setenv('TAVILY_ENABLED','false')
    monkeypatch.setenv('TREG_ENABLED','false')
    monkeypatch.setenv('YOUTUBE_ENABLED', 'false')
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match='No live discovery provider'):
            asyncio.run(run_pipeline([],[],2,70))
        with pytest.raises(ValueError, match='TAVILY_API_KEY'):
            asyncio.run(run_pipeline([],['web'],2,70))
    finally:
        get_settings.cache_clear()
