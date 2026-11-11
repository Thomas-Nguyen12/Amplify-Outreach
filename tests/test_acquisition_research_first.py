"""Mocked end-to-end tests: no external calls, real messages or purchases."""
import asyncio
import json
import pytest
from app.config import get_settings
from app.database import init_db, rows
from app.models import Prospect
from app.scoring import score_item
from app.research_assessment import apply_research_assessment, parse_assessment
from app.drafts import create_draft
from app import pipeline

@pytest.fixture
def harness(monkeypatch, tmp_path):
    settings = {
        'DATABASE_PATH': str(tmp_path/'test.sqlite'),
        'TAVILY_ENABLED':'true', 'TAVILY_API_KEY':'mock-no-network',
        'MINDS_ENABLED':'true', 'SURREAL_ENABLED':'false',
        'MINDS_MAX_RESEARCH_PER_RUN':'3', 'AGENT_API_KEY':'',
    }
    for k,v in settings.items(): monkeypatch.setenv(k,v)
    get_settings.cache_clear()
    init_db()
    yield monkeypatch
    get_settings.cache_clear()

def prospect(*, description, signal=''):
    return Prospect(
        business_name='Indie SaaS Startup',platform='youtube_direct',
        profile_url='https://www.youtube.com/channel/UC123',
        source_url='https://www.youtube.com/watch?v=abc',
        description=description,signal=signal,source_date='2026-11-10',
        evidence_confidence=3,raw={'channel_id':'UC123'},
    )

def test_research_before_draft_for_previously_low_scoring_youtube_lead(harness):
    p=prospect(description='Small startup founder discussing building a SaaS product.')
    score_item(p)
    assert not p.qualified
    calls=[]
    async def discover(*args):
        return [p.model_copy(deep=True)],[]
    async def minds(lead):
        calls.append('research')
        return {'mind_id':'fake','alias':'fake','reply':'No verifiable content challenge was found.'}
    def draft(item, **kwargs):
        calls.append('draft')
        return create_draft(item, **kwargs)
    harness.setattr(pipeline,'discover',discover)
    harness.setattr(pipeline,'research_lead',minds)
    harness.setattr(pipeline,'create_draft',draft)
    result=asyncio.run(pipeline.run_pipeline(['startup content idea'],['web'],2,70))
    assert result['discovered']==result['saved']==1
    assert result['researched']==0 and result['research_pending']==1
    assert result['qualified']==result['drafts']==0
    assert calls==['research']
    assert len(rows('SELECT * FROM research_briefs'))==0


def test_research_happens_before_draft_for_prequalified_lead(harness):
    p=prospect(description='Small startup founder needs content ideas and competitor monitoring for a daily content calendar.',
               signal='Need help with social media and low engagement. We need daily posts.')
    calls=[]
    async def discover(*args): return [p.model_copy(deep=True)], []
    async def minds(lead):
        calls.append('research')
        return {'mind_id':'mock','alias':'mock','reply':json.dumps({'status':'completed','summary':'Researched','content_challenges':[],'evidence':[{'source_url':p.source_url,'quote':'Need help with social media and low engagement. We need daily posts.'}],'limitations':[]})}
    def draft(item, **kwargs):
        calls.append('draft')
        return create_draft(item, **kwargs)
    harness.setattr(pipeline,'discover',discover)
    harness.setattr(pipeline,'research_lead',minds)
    harness.setattr(pipeline,'create_draft',draft)
    result=asyncio.run(pipeline.run_pipeline(['test'],['web'],2,70))
    assert result['qualified']==result['researched']==result['drafts']==1
    assert calls==['research','draft']
    assert 'ready-to-post content suggestions' in rows('SELECT message FROM drafts')[0]['message']


def test_research_outage_does_not_prepare_unreviewed_draft(harness):
    p=prospect(description='Small startup needs content ideas and daily posts, has low engagement, and competitor monitoring.')
    async def discover(*args): return [p], []
    async def failure(lead): raise RuntimeError('synthetic research outage')
    harness.setattr(pipeline,'discover',discover)
    harness.setattr(pipeline,'research_lead',failure)
    result=asyncio.run(pipeline.run_pipeline(['test'],['web'],2,70))
    assert result['saved']==1 and result['researched']==0 and result['drafts']==0
    assert len(result['errors'])==1


def test_mind_hallucinated_purchase_intent_cannot_qualify():
    p=prospect(description='Startup founder talks about launching a product.')
    before=score_item(p).score
    research={'reply':json.dumps({'subscription_fit':'strong', 'evidence':[{
        'source_url':'https://www.youtube.com/watch?v=abc',
        'quote':'We definitely want to purchase social media analytics every day',
    }]})}
    review=apply_research_assessment(p,research)
    assert review['evidence_accepted']==0
    assert p.score==before and p.qualified is False


def test_research_correlates_only_exact_known_public_quote():
    quote='We need content ideas and daily posts, our engagement is low'
    p=prospect(description=quote)
    score_item(p)
    research={'reply':json.dumps({'status':'completed','summary':'Test','content_challenges':[],'limitations':[],'evidence':[
        {'source_url':p.profile_url,'quote':quote},
        {'source_url':'https://attacker.example/bogus', 'quote':quote},
    ]})}
    review=apply_research_assessment(p,research)
    assert review['status']=='completed_with_correlated_evidence'
    assert review['evidence_accepted']==1


def test_targeting_not_based_only_on_startup_topic():
    p=prospect(description='A video discussing the startup ecosystem without a request for marketing help.')
    score_item(p)
    assert not p.qualified
    assert p.buying_intent == 0


def test_offer_mentions_actual_subscription_deliverables():
    p=prospect(description='A small startup needs content ideas')
    score_item(p)
    _,msg=create_draft(p)
    for phrase in ('daily insights','competitor','hot-topic','ready-to-post content suggestions'):
        assert phrase in msg
    assert 'AI assistance' in msg


def test_invalid_research_json_is_safe():
    assert parse_assessment('Normal narrative with no JSON') is None
    assert parse_assessment('```json\n{"evidence":[]}\n```') == {'evidence':[]}


def test_manual_research_endpoint_runs_on_unqualified_lead(harness):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import save_prospect, get_research
    from app import main
    p=prospect(description='Startup founder building in public, but no verified content pain.')
    score_item(p)
    assert not p.qualified
    lead_id=save_prospect(p)
    async def mocked(lead):
        return {'mind_id':'mock','alias':'manual-test','reply':json.dumps({'status':'completed','summary':'No independently established content need.','content_challenges':[],'evidence':[],'limitations':['Unknown']})}
    harness.setattr(main,'research_lead',mocked)
    response=TestClient(app).post(f'/research/{lead_id}/run')
    assert response.status_code==200
    body=response.json()
    assert body['qualification']['qualified'] is False
    assert body['qualification']['outreach_sent'] is False
    assert json.loads(get_research(lead_id)['research_text'])['status']=='completed'
    assert not rows('SELECT * FROM drafts')


def test_manual_research_does_not_run_for_suppressed_prospect(harness):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import save_prospect, connect
    from app import main
    from app.surreal_store import lead_identity
    p=prospect(description='Startup needs content ideas and daily posts')
    score_item(p)
    lead_id=save_prospect(p)
    # Test local suppression because SURREAL_ENABLED=false.
    with connect() as db:
        db.execute('INSERT INTO suppression(identity,reason,created_at) VALUES(?,?,datetime("now"))',
                   (lead_identity(p),'fictional opt out'))
    calls=[]
    async def mocked(lead):
        calls.append(lead)
        return {'mind_id':'mock','alias':'x','reply':'bad'}
    harness.setattr(main,'research_lead',mocked)
    response=TestClient(app).post(f'/research/{lead_id}/run')
    assert response.status_code==409
    assert calls==[]
