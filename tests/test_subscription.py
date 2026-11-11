from app.models import Prospect
from app.scoring import score_item
from app.targeting import DEFAULT_QUERIES, segment_for, subscription_fit
from app.drafts import create_draft
from app.hellominds import research_prompt
from app.database import init_db, save_prospect, save_interest, rows

def test_queries_target_small_and_startups():
    assert any('small business' in q for q in DEFAULT_QUERIES)
    assert any('startup' in q for q in DEFAULT_QUERIES)

def test_startup_recurring_fit():
    p=Prospect(business_name='Bootstrapped SaaS startup', platform='web',
       source_url='https://example.org', website='https://example.org',
       description='Looking for weekly competitor tracking and market research',
       signal='Need insights for growth',source_date='2026-11-09')
    score_item(p)
    assert p.segment=='startup'
    assert p.subscription_fit>0
    assert p.qualified
    _,message=create_draft(p)
    assert 'subscription' in message
    assert 'AI assistance' in message

def test_unverified_not_qualified_even_if_need():
    p=Prospect(business_name='Article',platform='web',source_url='https://example.org',
        description='Looking for market research competitor tracking monthly insight')
    score_item(p)
    assert p.segment=='unverified'
    assert not p.qualified

def test_research_mentions_subscription():
    assert 'SUBSCRIPTION' in research_prompt({'business_name':'Small Test Store'})

def test_interest_is_not_billing(tmp_path,monkeypatch):
    from app.config import get_settings
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'test.db'))
    get_settings.cache_clear()
    try:
        init_db()
        p=Prospect(business_name='Indie startup',platform='web',source_url='https://example.org',
           website='https://example.org',description='Looking for ongoing market research')
        score_item(p)
        pid=save_prospect(p)
        result=save_interest(pid,'https://example.org/post','Interested in recurring insights', 'interested')
        assert result['stage']=='interested'
        assert result['price_gbp']=='7'
    finally:
        get_settings.cache_clear()
