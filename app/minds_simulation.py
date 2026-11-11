"""Optional live HelloMinds research on FICTIONAL simulation fixtures.

The only external request is to the configured HelloMinds Mind, NEVER to the
fake prospect. Customer replies are the deterministic scripted fixtures.
Results are stored exclusively in the simulation database and exports.
"""
import asyncio
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings
from .hellominds import research_lead
from .simulation import DEFAULT_FIXTURES, _connect, _event, export_simulation, load_fixtures, run_simulation


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _create_minds_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS simulation_minds_research (
      run_id TEXT NOT NULL REFERENCES simulation_runs(run_id),
      customer_id TEXT NOT NULL,
      business_name TEXT NOT NULL,
      status TEXT NOT NULL,
      research_text TEXT NOT NULL,
      error TEXT NOT NULL,
      mind_id TEXT NOT NULL,
      researched_at TEXT NOT NULL,
      PRIMARY KEY(run_id,customer_id),
      FOREIGN KEY(run_id,customer_id) REFERENCES simulation_customers(run_id,customer_id)
    )''')


def _fictional_lead(item):
    """No emails, private data, or real social links are needed for this research."""
    return {
        'id': item['customer_id'],
        'customer_id': item['customer_id'],
        'business_name': item['business_name'],
        'website': item.get('website', ''),
        'profile_url': item.get('profile_url', ''),
        'source_url': item.get('source_url', ''),
        'signal': item.get('signal', ''),
        'description': item.get('description', ''),
        'fictional_profile': item.get('fictional_profile', {}),
        'segment': item.get('segment', 'synthetic_test'),
        'platform': item.get('platform', 'web'),
    }


async def run_minds_simulation(db_path, fixtures_path=DEFAULT_FIXTURES, *,
                               threshold=70, max_research=3, research_fn=None):
    """Score fixtures locally then ask the REAL Mind about eligible fictional prospects.

    research_fn is injected only in tests. Live runs require the configured
    Builder API key and Mind ID. No production CRM, outreach, or Stripe writes.
    """
    if not 1 <= max_research <= 20:
        raise ValueError('max_research must be between 1 and 20')
    if research_fn is None:
        cfg = get_settings()
        if not (cfg.minds_enabled and cfg.minds_builder_api_key and cfg.minds_research_mind_id):
            raise RuntimeError('Set MINDS_ENABLED=true, MINDS_BUILDER_API_KEY and MINDS_RESEARCH_MIND_ID in .env')
        research_fn = research_lead
    summary = run_simulation(db_path, fixtures_path, threshold=threshold)
    run_id = summary['run_id']
    fixture_map = {item['customer_id']: item for item in load_fixtures(fixtures_path)}
    attempts = 0
    successes = 0
    failures = 0
    with _connect(db_path) as db:
        _create_minds_table(db)
        candidates = db.execute('''SELECT c.customer_id, c.business_name FROM simulation_customers c
            JOIN simulation_messages m ON (m.run_id=c.run_id AND m.customer_id=c.customer_id)
            WHERE c.run_id=? AND c.qualified=1 AND c.eligible=1 AND c.suppressed=0
            ORDER BY c.score DESC, c.customer_id LIMIT ?''', (run_id,max_research)).fetchall()
        for candidate in candidates:
            cid = candidate['customer_id']
            lead = _fictional_lead(fixture_map[cid])
            _event(db,run_id,cid,'synthetic_minds_research_started',{'synthetic': True})
            attempts += 1
            status, reply, error, mind_id = 'succeeded', '', '', ''
            try:
                result = await research_fn(lead, synthetic=True)
                reply = result.get('reply', '')
                mind_id = result.get('mind_id', '')
                if not isinstance(reply,str) or not reply.strip():
                    raise ValueError('HelloMinds returned empty research')
                successes += 1
            except Exception as exc:
                status, error = 'failed', str(exc)[:400]
                failures += 1
            db.execute('''INSERT INTO simulation_minds_research
                (run_id,customer_id,business_name,status,research_text,error,mind_id,researched_at)
                VALUES(?,?,?,?,?,?,?,?)''',
                (run_id,cid,lead['business_name'],status,reply,error,mind_id,_utc_now()))
            _event(db,run_id,cid,'synthetic_minds_research_completed',{
                'status':status,'error':error,'research_reply_length':len(reply),
                'external_service':'hellominds','contacted_prospect':False,
                'synthetic':True})
            # Persist each completed record, including failures, in case a later call fails.
            db.commit()
        summary.update({
            'simulation_mode':'minds_live_synthetic',
            'minds_requests_attempted':attempts,
            'minds_research_succeeded':successes,
            'minds_research_failed':failures,
            'minds_uses_real_api':research_fn is research_lead,
            'research_subjects_are_fictional':True,
            'customer_responses_are_scripted':True,
        })
        db.execute('UPDATE simulation_runs SET summary_json=? WHERE run_id=?',
                   (json.dumps(summary,sort_keys=True),run_id))
        _event(db,run_id,None,'minds_simulation_completed',summary)
    return summary


def export_minds_simulation(db_path, run_id, directory):
    directory = Path(directory)
    files = export_simulation(db_path, run_id, directory)
    with _connect(db_path) as db:
        _create_minds_table(db)
        rows = [dict(r) for r in db.execute('''SELECT * FROM simulation_minds_research
            WHERE run_id=? ORDER BY customer_id''',(run_id,))]
        csv_path = directory/'minds_research.csv'
        columns = ['run_id','customer_id','business_name','status','research_text',
                   'error','mind_id','researched_at']
        with csv_path.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=columns)
            w.writeheader()
            w.writerows(rows)
        json_path=directory/'minds_research.jsonl'
        with json_path.open('w',encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps({**r,'synthetic':True},ensure_ascii=False)+'\n')
        files['minds_research_csv']=str(csv_path)
        files['minds_research_jsonl']=str(json_path)
    return files
