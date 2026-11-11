"""Research completion and source-grounded outreach regression tests."""
import json
import pytest
from fastapi.testclient import TestClient
from app.models import Prospect
from app.scoring import score_item
from app.research_assessment import classify_research, apply_research_assessment
from app.drafts import create_draft
from app.database import init_db, save_prospect, get_research, rows
from app.config import get_settings
from app import main


def example():
    p = Prospect(business_name='Small Creative Studio', platform='web',
                 profile_url='https://studio.example/about',
                 source_url='https://studio.example/post',
                 description='We need content ideas and daily posts, our engagement is low. Indie small business.',
                 signal='We need help with social media and low engagement. We need daily posts.',
                 source_date='2026-11-10')
    score_item(p)
    return p


def research(*, quote=None, url=None):
    evidence = [{'source_url':url, 'quote':quote}] if quote else []
    return {'mind_id':'test-mind', 'alias':'test-alias',
            'reply': json.dumps({'status':'completed','summary':'Public content research complete.',
                                 'content_challenges':['content ideas'],
                                 'evidence':evidence,'limitations':['No buyer intent confirmed']})}


def test_acknowledgement_is_not_completed():
    r = {'reply':"On it - I'm starting prospect research. Expect the brief in 10-15 minutes."}
    assert classify_research(r)=='pending'
    assert apply_research_assessment(example(),r)['research_reviewed'] is False


def test_json_without_final_status_is_invalid():
    assert classify_research({'reply':'{"summary":"done","evidence":[]}'})=='invalid'
    assert classify_research({'reply':'{"status":"pending","summary":"working"}'})=='pending'


def test_source_correlated_quote_is_used_in_draft_without_price():
    p=example()
    r=research(quote='We need help with social media and low engagement. We need daily posts.',
               url=p.source_url)
    check=apply_research_assessment(p,r)
    assert check['research_status']=='completed'
    assert check['evidence_accepted']==1
    subject,message=create_draft(p,assessment=check)
    assert 'We need help with social media and low engagement' in message
    assert p.source_url in message
    assert 'ready-to-post content suggestions' in message
    assert '£7' not in subject+message and '7/month' not in subject+message
    assert 'AI assistance' in message


def test_unverified_quote_never_appears_in_draft():
    p=example()
    r=research(quote='We desperately want to buy your service',url=p.source_url)
    check=apply_research_assessment(p,r)
    assert check['evidence_accepted']==0
    _,message=create_draft(p,assessment=check)
    assert 'desperately' not in message
    assert 'I came across' in message


def test_price_is_omitted_even_from_prospect_name():
    p=example()
    p.business_name='Small Creative Studio £7/month'
    title,message=create_draft(p)
    assert '£7/month' not in title+message
    assert '[price omitted]' in message


def test_manual_endpoint_does_not_save_acknowledgement_as_completed(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'s.sqlite3'))
    monkeypatch.setenv('SURREAL_ENABLED','false')
    monkeypatch.setenv('AGENT_API_KEY','')
    get_settings.cache_clear()
    try:
        init_db()
        lead_id=save_prospect(example())
        async def ack(_):
            return {'mind_id':'test-mind','alias':'test-alias',
                    'reply':"On it. Research will take 15 minutes."}
        monkeypatch.setattr(main,'research_lead',ack)
        response=TestClient(main.app).post(f'/research/{lead_id}/run')
        assert response.status_code==200
        assert response.json()['research_status']=='pending'
        assert response.json()['research_completed'] is False
        assert get_research(lead_id) is None
        assert rows('SELECT * FROM drafts')==[]
    finally:
        get_settings.cache_clear()
