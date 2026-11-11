"""End-to-end live pipeline persistence scenarios; no external calls or API keys."""
import asyncio
import json
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from app.config import get_settings
from app.database import init_db, rows
from app.main import app
from app.models import Prospect
from app.pipeline import run_pipeline
from app import pipeline, main
from app.surreal_store import canonical_identity, lead_identity

class FakePersistentStore:
    """Models a Surreal instance that survives fresh Daytona/SQLite processes."""
    def __init__(self):
        self.tables = {}
        self.down = False
    def ping(self):
        self._ensure()
        return True
    def _ensure(self):
        if self.down:
            raise ConnectionError('Simulated SurrealDB outage')
    def get(self, table, identity):
        self._ensure()
        return deepcopy(self.tables.get((table, identity)))
    def put(self, table, identity, data):
        self._ensure()
        self.tables[(table, identity)] = deepcopy(data)
    def claim_prospect(self, identity, data):
        self._ensure()
        if self.get_prospect(identity):
            return False
        self.save_prospect(identity, data)
        return True
    def get_prospect(self, identity):
        return self.get('prospects', identity)
    def save_prospect(self, identity, data):
        self.put('prospects', identity, data)
    def is_suppressed(self, identity):
        return bool(self.get('suppression', identity))
    def suppress(self, identity, reason):
        self.put('suppression',identity,{'identity':identity,'reason':reason})
    def get_research(self, identity):
        return self.get('research_briefs', identity)
    def save_research(self, identity, data):
        self.put('research_briefs',identity,data)
    def save_draft(self, identity, subject, message):
        self.put('outreach_drafts',identity,{'subject':subject,'message':message,'sent':False})

@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = FakePersistentStore()
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'one.sqlite'))
    monkeypatch.setenv('TAVILY_ENABLED','true')
    monkeypatch.setenv('TAVILY_API_KEY','not-a-real-token')
    monkeypatch.setenv('TREG_ENABLED','false')
    monkeypatch.setenv('MINDS_ENABLED','true')
    monkeypatch.setenv('SURREAL_ENABLED','true')
    monkeypatch.setenv('AGENT_API_KEY','')
    get_settings.cache_clear()
    init_db()
    monkeypatch.setattr(pipeline,'enabled_store',lambda:store)
    monkeypatch.setattr(main,'enabled_store',lambda:store)
    calls={'research':0}
    async def research(lead):
        calls['research']+=1
        return {'mind_id':'synthetic-mind','alias':'test-alias','reply':json.dumps({'status':'completed','summary':'Mock verified interface, fictional lead.','content_challenges':[],'limitations':[],'evidence':[{'source_url':profiles[0].profile_url,'quote':'looking for competitor analysis and daily market research'}]})}
    monkeypatch.setattr(pipeline,'research_lead',research)
    profiles=[Prospect(business_name='Indie Tiny SaaS',platform='web',
        website='https://indie-saas.example/',profile_url='https://indie-saas.example/about',
        source_url='https://indie-saas.example/launch',source_date='2026-11-10',
        description='Early stage startup looking for competitor analysis and daily market research',
        signal='Need insights for launching and trend analytics',evidence_confidence=5)]
    async def discover(*args):
        return [p.model_copy(deep=True) for p in profiles],[]
    monkeypatch.setattr(pipeline,'discover',discover)
    yield store, calls, profiles, tmp_path, monkeypatch
    get_settings.cache_clear()

def run():
    return asyncio.run(run_pipeline(['test only'],['web'],2,70))

def fresh_sandbox(tmp_path,monkeypatch,label):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/f'{label}.sqlite'))
    get_settings.cache_clear()
    init_db()

def test_cross_sandbox_persistence_prevents_duplicates_and_second_research(setup):
    store,calls,_,tmp_path,monkeypatch=setup
    first=run()
    assert first['saved']==first['qualified']==first['drafts']==first['researched']==1
    assert calls['research']==1
    assert len(store.tables)==3  # prospect + draft + research
    fresh_sandbox(tmp_path,monkeypatch,'new-daytona-sandbox')
    second=run()
    assert second['already_known']==1
    assert second['saved']==second['drafts']==second['researched']==0
    assert calls['research']==1
    assert not rows('SELECT * FROM drafts')

def test_suppression_survives_fresh_sandbox(setup):
    store,calls,profiles,tmp_path,monkeypatch=setup
    identity=lead_identity(profiles[0])
    client=TestClient(app)
    response=client.post('/suppression',json={'identity':identity,'reason':'opt out test'})
    assert response.status_code==200
    assert store.is_suppressed(identity)
    fresh_sandbox(tmp_path,monkeypatch,'third-sandbox')
    report=run()
    assert report['suppressed']==1 and report['saved']==0
    assert calls['research']==0

def test_outage_fails_closed_before_any_drafts_or_research(setup):
    store,calls,_,_,_=setup
    store.down=True
    with pytest.raises(ConnectionError, match='outage'):
        run()
    assert calls['research']==0
    assert not rows('SELECT * FROM prospects')

def test_suppression_api_does_not_acknowledge_failed_durable_write(setup):
    store,_,_,_,_=setup
    store.down=True
    client=TestClient(app)
    response=client.post('/suppression',json={'identity':'https://fake.example','reason':'test'})
    assert response.status_code==503
    assert not rows('SELECT * FROM suppression')

def test_canonical_id_stable_across_url_variants():
    assert canonical_identity('http://WWW.Example.Org/') == canonical_identity('https://example.org')
    assert canonical_identity('https://example.org/a') != canonical_identity('https://example.org/b')


def test_failed_research_retries_without_duplicate_draft(setup):
    store,calls,profiles,tmp_path,monkeypatch=setup
    async def failing(lead):
        raise RuntimeError('temporary research outage')
    monkeypatch.setattr(pipeline,'research_lead',failing)
    first=run()
    assert first['saved']==1
    assert first['drafts']==0  # Research must succeed before the first draft.
    assert first['researched']==0
    fresh_sandbox(tmp_path,monkeypatch,'restart-after-failure')
    async def recovered(lead):
        calls['research']+=1
        return {'mind_id':'test','alias':'test','reply':json.dumps({'status':'completed','summary':'Recovered research','content_challenges':[],'limitations':[],'evidence':[{'source_url':profiles[0].profile_url,'quote':'looking for competitor analysis and daily market research'}]})}
    monkeypatch.setattr(pipeline,'research_lead',recovered)
    second=run()
    assert second['saved']==0
    assert second['drafts']==1  # First draft after recovered research; no duplicates.
    assert second['researched']==1
    assert calls['research']==1
    assert json.loads(store.get_research(lead_identity(profiles[0]))['reply'])['summary']=='Recovered research'
