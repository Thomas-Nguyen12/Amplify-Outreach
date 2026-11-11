"""End-to-end local synthetic customers, messaging and response audit tests."""
import csv
import json
import sqlite3
from pathlib import Path

import pytest

from app.config import get_settings
from app.simulation import load_fixtures, run_simulation, export_simulation

@pytest.fixture
def simulated(tmp_path, monkeypatch):
    # Disable all network service adapters explicitly, regardless of host .env.
    for key,value in {
        'DATABASE_PATH':str(tmp_path/'real.sqlite3'),
        'TAVILY_ENABLED':'false','TREG_ENABLED':'false',
        'MINDS_ENABLED':'false','SURREAL_ENABLED':'false',
        'TARGET_SEGMENTS':'small_business,startup,influencer',
        'SUBSCRIPTION_PRICE_GBP':'7','REPORT_FREQUENCY':'daily',
    }.items():
        monkeypatch.setenv(key,value)
    get_settings.cache_clear()
    db=tmp_path/'simulation.sqlite3'
    summary=run_simulation(db)
    yield db,summary,tmp_path
    get_settings.cache_clear()


def test_simulation_counts_and_offline_safety(simulated):
    db,s,_=simulated
    assert s['simulation'] is True
    assert s['customers']==8
    assert s['simulated_messages_sent']==5
    assert s['qualified']==5
    assert s['simulated_interested']==2
    assert s['simulated_questions']==1
    assert s['simulated_declines']==1
    assert s['simulated_no_response']==1
    assert s['excluded_or_unqualified']==3
    assert s['live_messages_sent']==s['actual_subscriptions']==s['actual_revenue_gbp']==0
    assert s['subscription_price_gbp']=='7'
    assert s['insights_frequency']=='daily'


def test_all_three_segments_have_messages(simulated):
    db,s,_=simulated
    with sqlite3.connect(db) as c:
        segments={r[0] for r in c.execute('''SELECT DISTINCT c.segment FROM simulation_customers c
          JOIN simulation_messages m ON m.run_id=c.run_id AND m.customer_id=c.customer_id
          WHERE c.run_id=?''',(s['run_id'],))}
    assert segments=={'startup','small_business','influencer'}


def test_no_outbound_or_unqualified_customer_contacted(simulated):
    db,s,_=simulated
    with sqlite3.connect(db) as c:
        rows=c.execute('''SELECT c.qualified,c.eligible,c.suppressed,m.delivery_status,m.message
          FROM simulation_messages m JOIN simulation_customers c
          ON c.run_id=m.run_id AND c.customer_id=m.customer_id
          WHERE m.run_id=?''',(s['run_id'],)).fetchall()
        blocked=c.execute('''SELECT COUNT(*) FROM simulation_messages WHERE run_id=?
          AND customer_id IN ('SIM-006','SIM-007','SIM-008')''',(s['run_id'],)).fetchone()[0]
    assert rows and blocked==0
    for qualified,eligible,suppressed,status,message in rows:
        assert qualified==eligible==1 and suppressed==0
        assert status=='simulated_sent'
        assert '£7/month' not in message
        assert 'daily insights' in message
        assert 'AI assistance' in message


def test_response_logs_correspond_only_to_simulated_messages(simulated):
    db,s,_=simulated
    with sqlite3.connect(db) as c:
        m={r[0] for r in c.execute('SELECT customer_id FROM simulation_messages WHERE run_id=?',(s['run_id'],))}
        response={r[0]:r[1:] for r in c.execute('''SELECT customer_id,response_type,response_text
          FROM simulation_responses WHERE run_id=?''',(s['run_id'],))}
    assert set(response)==m
    assert response['SIM-005']==('no_response','')
    assert response['SIM-004'][0]=='declined'
    assert 'SIMULATED RESPONSE' in response['SIM-001'][1]


def test_simulation_never_writes_real_crm(simulated):
    db,s,tmp_path=simulated
    assert not (tmp_path/'real.sqlite3').exists()
    with sqlite3.connect(db) as c:
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'prospects' not in tables
    assert 'drafts' not in tables
    assert 'subscription_opportunities' not in tables


def test_export_contains_customer_message_response_and_event_logs(simulated):
    db,s,tmp_path=simulated
    outputs=export_simulation(db,s['run_id'],tmp_path/'logs')
    with open(outputs['simulation_customers'],newline='') as f:
        customers=list(csv.DictReader(f))
    with open(outputs['simulation_messages'],newline='') as f:
        messages=list(csv.DictReader(f))
    with open(outputs['simulation_responses'],newline='') as f:
        replies=list(csv.DictReader(f))
    events=[json.loads(x) for x in Path(outputs['simulation_events']).read_text().splitlines()]
    summary=json.loads(Path(outputs['summary']).read_text())
    assert len(customers)==8
    assert len(messages)==len(replies)==5
    assert len(events)==8+3+5+5+1
    assert summary==s
    assert {'synthetic_message_simulated_sent','synthetic_customer_response','simulation_contact_skipped'} <= {e['event_type'] for e in events}


def test_multiple_runs_preserve_separate_logs(simulated):
    db,s,_=simulated
    next_run=run_simulation(db)
    assert next_run['run_id']!=s['run_id']
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT COUNT(*) FROM simulation_customers').fetchone()[0]==16
        assert c.execute('SELECT COUNT(*) FROM simulation_messages').fetchone()[0]==10


def test_repeated_fixture_outcome_is_deterministic(simulated):
    db,s,_=simulated
    repeat=run_simulation(db)
    assert {k:v for k,v in s.items() if k!='run_id'}=={k:v for k,v in repeat.items() if k!='run_id'}


def test_invalid_duplicate_fixture_is_rejected(tmp_path):
    fixture=tmp_path/'fixture.json'
    fixture.write_text(json.dumps([{'customer_id':'DUP'},{'customer_id':'DUP'}]))
    with pytest.raises(ValueError,match='unique'):
        load_fixtures(fixture)


def test_invalid_persona_rejected(tmp_path):
    fixture=tmp_path/'fixture.json'
    fixture.write_text(json.dumps([{'customer_id':'ONE','response_persona':'paid_subscriber'}]))
    with pytest.raises(ValueError,match='Unsupported response persona'):
        load_fixtures(fixture)


def test_invalid_threshold_rejected(tmp_path):
    with pytest.raises(ValueError,match='threshold'):
        run_simulation(tmp_path/'sim.db',threshold=101)


def test_unknown_export_run_rejected(simulated):
    db,_,tmp_path=simulated
    with pytest.raises(ValueError,match='not found'):
        export_simulation(db,'not-a-run',tmp_path/'logs')


def test_no_external_services_are_called(monkeypatch,tmp_path):
    # A network failure monkeypatch makes unintended external calls fail this test.
    import socket
    def blocked(*args,**kwargs):
        raise AssertionError('Network attempt during offline simulation')
    monkeypatch.setattr(socket.socket,'connect',blocked)
    result=run_simulation(tmp_path/'offline.sqlite3')
    assert result['simulated_messages_sent']==5
