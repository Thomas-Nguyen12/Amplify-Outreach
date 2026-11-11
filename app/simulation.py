"""Offline-only simulated buyer experiment. No HTTP, mail, DMs, Stripe or live services.

All contacts/messages/responses are synthetic. Simulation data is strictly separate
from the real prospects, drafts, opportunities, and audit_events tables.
"""
import csv
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings
from .models import Prospect
from .scoring import score_item
from .drafts import create_draft
from .compliance import check_prospect

DEFAULT_FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'synthetic_customers.json'
PERSONAS = {'interested', 'question', 'declined', 'no_response'}
RESPONSE_TEXT = {
    'interested': 'SIMULATED RESPONSE: I would like to see a sample of the £7/month daily insights.',
    'question': 'SIMULATED RESPONSE: Can you show how daily insights could help my niche?',
    'declined': 'SIMULATED RESPONSE: Not interested, please do not contact us again.',
    'no_response': '',
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS simulation_runs (
          run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
          fixture_path TEXT NOT NULL, threshold INTEGER NOT NULL,
          offer_price_gbp TEXT NOT NULL, frequency TEXT NOT NULL,
          summary_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS simulation_customers (
          run_id TEXT NOT NULL REFERENCES simulation_runs(run_id),
          customer_id TEXT NOT NULL, business_name TEXT NOT NULL,
          segment TEXT NOT NULL, platform TEXT NOT NULL,
          score INTEGER NOT NULL, qualified INTEGER NOT NULL,
          eligible INTEGER NOT NULL, suppressed INTEGER NOT NULL,
          qualification_reasons TEXT NOT NULL,
          PRIMARY KEY(run_id,customer_id)
        );
        CREATE TABLE IF NOT EXISTS simulation_messages (
          run_id TEXT NOT NULL REFERENCES simulation_runs(run_id),
          customer_id TEXT NOT NULL, subject TEXT NOT NULL,
          message TEXT NOT NULL, delivery_status TEXT NOT NULL,
          simulated_at TEXT NOT NULL,
          PRIMARY KEY(run_id,customer_id),
          FOREIGN KEY(run_id,customer_id) REFERENCES simulation_customers(run_id,customer_id)
        );
        CREATE TABLE IF NOT EXISTS simulation_responses (
          run_id TEXT NOT NULL REFERENCES simulation_runs(run_id),
          customer_id TEXT NOT NULL, response_type TEXT NOT NULL,
          response_text TEXT NOT NULL, simulated_at TEXT NOT NULL,
          PRIMARY KEY(run_id,customer_id),
          FOREIGN KEY(run_id,customer_id) REFERENCES simulation_customers(run_id,customer_id)
        );
        CREATE TABLE IF NOT EXISTS simulation_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL REFERENCES simulation_runs(run_id),
          customer_id TEXT, event_type TEXT NOT NULL,
          detail_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
    ''')
    return db


def _event(db, run_id, customer_id, event_type, detail):
    db.execute('''INSERT INTO simulation_events(run_id,customer_id,event_type,detail_json,created_at)
                  VALUES(?,?,?,?,?)''',
               (run_id,customer_id,event_type,json.dumps(detail,sort_keys=True),_now()))


def load_fixtures(path=DEFAULT_FIXTURES):
    fixtures=json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(fixtures,list):
        raise ValueError('Fixtures must be a list')
    seen=set()
    for item in fixtures:
        if not isinstance(item,dict) or not item.get('customer_id'):
            raise ValueError('Each fixture must have a customer_id')
        if item['customer_id'] in seen:
            raise ValueError('Fixture customer IDs must be unique')
        seen.add(item['customer_id'])
        if item.get('response_persona','no_response') not in PERSONAS:
            raise ValueError(f"Unsupported response persona for {item['customer_id']}")
    return fixtures


def run_simulation(db_path, fixtures_path=DEFAULT_FIXTURES, *, threshold=70, run_id=None):
    """Execute a deterministic offline test, returning counts and the run ID.

    Uses the real qualification, compliance and draft functions. The only
    simulation-specific elements are synthetic input and synthetic response.
    """
    if not 0 <= threshold <= 100:
        raise ValueError('threshold must be between 0 and 100')
    if run_id is None:
        run_id='sim-'+uuid.uuid4().hex[:12]
    fixtures=load_fixtures(fixtures_path)
    s=get_settings()
    summary={'run_id':run_id,'simulation':True,'customers':0,'qualified':0,
             'simulated_messages_sent':0,'simulated_interested':0,
             'simulated_questions':0,'simulated_declines':0,
             'simulated_no_response':0,'excluded_or_unqualified':0,
             'currency':s.subscription_currency,'subscription_price_gbp':s.subscription_price_gbp,
             'billing_interval':s.subscription_interval,'insights_frequency':s.report_frequency,
             'live_messages_sent':0,'actual_subscriptions':0,'actual_revenue_gbp':0}
    with _connect(db_path) as db:
        db.execute('''INSERT INTO simulation_runs(run_id,created_at,fixture_path,threshold,
                      offer_price_gbp,frequency,summary_json) VALUES(?,?,?,?,?,?,?)''',
                   (run_id,_now(),str(fixtures_path),threshold,s.subscription_price_gbp,
                    s.report_frequency,'{}'))
        for item in fixtures:
            cid=item['customer_id']
            prospect=Prospect(**{k:v for k,v in item.items() if k in Prospect.model_fields})
            score_item(prospect)
            suppressed=bool(item.get('suppressed',False))
            eligible=check_prospect(prospect, suppressed=suppressed)['eligible_for_research']
            allowed=(prospect.qualified and prospect.score>=threshold and eligible and not suppressed)
            summary['customers']+=1
            summary['qualified']+=int(allowed)
            db.execute('''INSERT INTO simulation_customers
                (run_id,customer_id,business_name,segment,platform,score,qualified,eligible,
                 suppressed,qualification_reasons) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (run_id,cid,prospect.business_name,prospect.segment,prospect.platform,
                 prospect.score,int(prospect.qualified),int(eligible),int(suppressed),
                 json.dumps(prospect.score_reasons)))
            _event(db,run_id,cid,'synthetic_customer_evaluated',
                   {'score':prospect.score,'qualified':prospect.qualified,
                    'eligible':eligible,'suppressed':suppressed,'platform':prospect.platform})
            if not allowed:
                summary['excluded_or_unqualified']+=1
                _event(db,run_id,cid,'simulation_contact_skipped',
                       {'reason':'unqualified_or_suppressed'})
                continue
            subject,message=create_draft(prospect)
            # Delivery_status is ONLY a local simulated event, never a network send.
            db.execute('''INSERT INTO simulation_messages
                (run_id,customer_id,subject,message,delivery_status,simulated_at)
                VALUES(?,?,?,?,?,?)''',
                (run_id,cid,subject,message,'simulated_sent',_now()))
            _event(db,run_id,cid,'synthetic_message_simulated_sent',
                   {'subject':subject,'channel':'offline_simulator','sent_to_external_service':False})
            summary['simulated_messages_sent']+=1
            persona=item.get('response_persona','no_response')
            response=RESPONSE_TEXT[persona]
            db.execute('''INSERT INTO simulation_responses
                (run_id,customer_id,response_type,response_text,simulated_at)
                VALUES(?,?,?,?,?)''',(run_id,cid,persona,response,_now()))
            _event(db,run_id,cid,'synthetic_customer_response',
                   {'response_type':persona,'message':response,'source':'synthetic_fixture'})
            summary['simulated_'+('questions' if persona=='question' else
                    'declines' if persona=='declined' else
                    'interested' if persona=='interested' else 'no_response')]+=1
        db.execute('UPDATE simulation_runs SET summary_json=? WHERE run_id=?',
                   (json.dumps(summary,sort_keys=True),run_id))
        _event(db,run_id,None,'simulation_completed',summary)
    return summary


def export_simulation(db_path, run_id, directory):
    """Export customer, message, response and append-only event logs to files."""
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    outputs={}
    with _connect(db_path) as db:
        found=db.execute('SELECT 1 FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone()
        if not found:
            raise ValueError('Simulation run not found')
        for table,filename in (
            ('simulation_customers','customers.csv'),
            ('simulation_messages','messages.csv'),
            ('simulation_responses','responses.csv'),
        ):
            records=[dict(x) for x in db.execute(f'SELECT * FROM {table} WHERE run_id=? ORDER BY customer_id',(run_id,))]
            path=directory/filename
            with path.open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=list(records[0]) if records else
                    [x[1] for x in db.execute(f'PRAGMA table_info({table})')])
                writer.writeheader()
                writer.writerows(records)
            outputs[table]=str(path)
        events=directory/'events.jsonl'
        with events.open('w',encoding='utf-8') as f:
            for row in db.execute('SELECT * FROM simulation_events WHERE run_id=? ORDER BY id',(run_id,)):
                f.write(json.dumps(dict(row),sort_keys=True)+'\n')
        outputs['simulation_events']=str(events)
        summary=json.loads(db.execute('SELECT summary_json FROM simulation_runs WHERE run_id=?',(run_id,)).fetchone()[0])
        summ=directory/'summary.json'
        summ.write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
        outputs['summary']=str(summ)
    return outputs
