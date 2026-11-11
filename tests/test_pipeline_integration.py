"""Integration tests with mocked discovery. No external API calls."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from app.config import get_settings
from app.database import init_db, rows, connect
from app.models import Prospect
from app.pipeline import run_pipeline
from app.main import app

@pytest.fixture
def local_db(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'crm.sqlite3'))
    monkeypatch.setenv('TAVILY_ENABLED','true')
    monkeypatch.setenv('TAVILY_API_KEY','synthetic-no-network')
    monkeypatch.setenv('TREG_ENABLED','false')
    monkeypatch.setenv('MINDS_ENABLED','false')
    monkeypatch.setenv('SURREAL_ENABLED','false')
    monkeypatch.setenv('AGENT_API_KEY','')
    get_settings.cache_clear()
    init_db()
    yield
    get_settings.cache_clear()


def fixture_prospect(name,website,description,signal):
    return Prospect(business_name=name,platform='web',website=website,
        profile_url=website,source_url=website+'/news',source_date='2026-11-10',
        description=description,signal=signal,evidence_confidence=4)


def test_pipeline_mocks_discovery_without_http(local_db,monkeypatch):
    from app import pipeline
    good=fixture_prospect('Small indie business','https://smallshop.example',
      'Independent small business looking for daily competitor monitoring and market research',
      'Need insights for daily trend tracking and growth')
    bad=fixture_prospect('Magazine article','https://magazine.example',
      'Story about the creator economy with no customer need','Weekly news')
    async def fake_discover(query,platforms,limit):
        assert platforms==['web']
        return [good.model_copy(deep=True),bad.model_copy(deep=True)],[]
    monkeypatch.setattr(pipeline,'discover',fake_discover)
    result=asyncio.run(run_pipeline(['synthetic query'],['web'],2,70))
    assert result['discovered']==2
    assert result['qualified']==1
    assert result['drafts']==1
    assert len(rows('SELECT * FROM prospects'))==2
    assert len(rows('SELECT * FROM drafts'))==1
    assert rows('SELECT event_type FROM audit_events')[-1]['event_type']=='agent_run'


def test_suppressed_customer_is_not_saved(local_db,monkeypatch):
    from app import pipeline
    prospect=fixture_prospect('Indie startup','https://suppressed.example',
       'Bootstrapped startup looking for daily competitor monitoring and market research',
       'Need insights for launching a new app')
    with connect() as db:
        db.execute("INSERT INTO suppression(identity,reason,created_at) VALUES(?,?,datetime('now'))",
                   ('https://suppressed.example','test opt out'))
    async def fake_discover(*args):
        return [prospect],[]
    monkeypatch.setattr(pipeline,'discover',fake_discover)
    report=asyncio.run(run_pipeline(['synthetic'],['web'],2,70))
    assert report['saved']==0
    assert report['drafts']==0
    assert not rows('SELECT * FROM prospects')


def test_api_reports_subscription_and_outreach_disabled(local_db):
    client=TestClient(app)
    config=client.get('/config/targeting')
    assert config.status_code==200
    data=config.json()
    assert set(data['segments'])=={'startup','small_business','influencer'}
    assert data['offer']['price_gbp']=='7'
    assert data['offer']['insights_frequency']=='daily'
    assert data['outreach_enabled'] is False
    assert client.get('/health').status_code==200


def test_api_key_protects_non_health_endpoints(local_db,monkeypatch):
    monkeypatch.setenv('AGENT_API_KEY','synthetic-test-secret')
    get_settings.cache_clear()
    client=TestClient(app)
    assert client.get('/health').status_code==200
    assert client.get('/leads').status_code==401
    assert client.get('/leads',headers={'x-agent-key':'synthetic-test-secret'}).status_code==200
