import asyncio
import csv
import json
import pytest
from app.hellominds import research_prompt
from app.minds_simulation import run_minds_simulation,export_minds_simulation,_fictional_lead
from app.simulation import load_fixtures


def test_fictional_prompt_marks_everything_as_synthetic():
    p = research_prompt({'business_name':'Fake Example'}, synthetic=True)
    assert 'FICTIONAL' in p
    assert 'Do not browse' in p
    assert 'No messages' in p
    assert '£7' in p


def test_live_prompt_keeps_real_research_mode():
    p = research_prompt({'business_name':'Real Example'})
    assert 'STRICT SYNTHETIC TEST' not in p


def test_fictional_lead_omits_response_and_secret_data():
    f = {**load_fixtures()[0], 'email': 'fake@example.invalid', 'password':'bad'}
    l = _fictional_lead(f)
    assert 'response_persona' not in l and 'password' not in l and 'email' not in l


def test_injected_minds_fake_generates_research_and_no_real_messages(tmp_path,monkeypatch):
    seen=[]
    async def fake_minds(lead, *, synthetic):
        assert synthetic is True
        assert lead['business_name']
        seen.append(lead)
        return {'reply':'SIMULATED RESEARCH: plausible daily niche-trend need, not verified.', 'mind_id':'test-mind'}
    summary = asyncio.run(run_minds_simulation(tmp_path/'sim.sqlite',max_research=3,research_fn=fake_minds))
    assert summary['customers']==8
    assert summary['minds_requests_attempted']==3
    assert summary['minds_research_succeeded']==3
    assert summary['live_messages_sent']==0
    assert summary['actual_revenue_gbp']==0
    assert len(seen)==3
    files=export_minds_simulation(tmp_path/'sim.sqlite',summary['run_id'],tmp_path/'out')
    rows=list(csv.DictReader(open(files['minds_research_csv'])))
    assert len(rows)==3
    assert all(row['status']=='succeeded' for row in rows)
    events=[json.loads(x) for x in open(files['simulation_events'])]
    assert any(e['event_type']=='synthetic_minds_research_completed' for e in events)
    assert all(x['contacted_prospect'] is False for e in events if e['event_type']=='synthetic_minds_research_completed' for x in [json.loads(e['detail_json'])])


def test_injected_failure_is_logged_without_crashing(tmp_path):
    async def fail(lead, *, synthetic):
        raise RuntimeError('simulated provider outage')
    summary=asyncio.run(run_minds_simulation(tmp_path/'sim.db',max_research=1,research_fn=fail))
    assert summary['minds_research_failed']==1
    files=export_minds_simulation(tmp_path/'sim.db',summary['run_id'],tmp_path/'logs')
    rows=[json.loads(x) for x in open(files['minds_research_jsonl'])]
    assert rows[0]['status']=='failed'
    assert 'provider outage' in rows[0]['error']


def test_minds_requires_credentials_when_not_mocked(tmp_path,monkeypatch):
    from app.config import get_settings
    monkeypatch.setenv('MINDS_ENABLED','false')
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError,match='MINDS_ENABLED'):
            asyncio.run(run_minds_simulation(tmp_path/'a.db',max_research=1))
    finally:
        get_settings.cache_clear()


def test_research_limit_guard(tmp_path):
    async def fake(lead, *, synthetic):
        return {'reply':'fine'}
    with pytest.raises(ValueError):
        asyncio.run(run_minds_simulation(tmp_path/'a.db',max_research=21,research_fn=fake))
