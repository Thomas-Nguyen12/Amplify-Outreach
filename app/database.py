import sqlite3, json
from pathlib import Path
from datetime import datetime, timezone
from .config import get_settings

def connect():
    path = Path(get_settings().database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db

def init_db():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS prospects (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          dedupe_key TEXT UNIQUE NOT NULL,
          business_name TEXT NOT NULL,
          platform TEXT NOT NULL,
          profile_url TEXT,
          website TEXT,
          description TEXT,
          signal TEXT,
          source_url TEXT NOT NULL,
          source_date TEXT,
          score INTEGER NOT NULL,
          priority TEXT NOT NULL,
          qualified INTEGER NOT NULL,
          segment TEXT NOT NULL DEFAULT 'unverified',
          subscription_fit INTEGER NOT NULL DEFAULT 0,
          score_reasons TEXT NOT NULL,
          raw_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS drafts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          prospect_id INTEGER NOT NULL REFERENCES prospects(id),
          subject TEXT NOT NULL,
          message TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft',
          created_at TEXT NOT NULL,
          UNIQUE(prospect_id)
        );
        CREATE TABLE IF NOT EXISTS research_briefs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          prospect_id INTEGER NOT NULL UNIQUE REFERENCES prospects(id),
          mind_id TEXT NOT NULL,
          conversation_alias TEXT NOT NULL,
          research_text TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS subscription_opportunities (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          prospect_id INTEGER NOT NULL UNIQUE REFERENCES prospects(id),
          stage TEXT NOT NULL DEFAULT 'interested',
          evidence_url TEXT NOT NULL,
          note TEXT NOT NULL,
          currency TEXT NOT NULL DEFAULT 'GBP',
          billing_interval TEXT NOT NULL DEFAULT 'month',
          price_gbp TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS suppression (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          identity TEXT UNIQUE NOT NULL,
          reason TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event_type TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        ''')
        # Upgrade databases created with the original MVP in place.
        existing = {r[1] for r in db.execute("PRAGMA table_info(prospects)")}
        if 'segment' not in existing:
            db.execute("ALTER TABLE prospects ADD COLUMN segment TEXT NOT NULL DEFAULT 'unverified'")
        if 'subscription_fit' not in existing:
            db.execute("ALTER TABLE prospects ADD COLUMN subscription_fit INTEGER NOT NULL DEFAULT 0")
        db.commit()

def audit(event_type, detail):
    with connect() as db:
        db.execute("INSERT INTO audit_events(event_type,detail_json,created_at) VALUES(?,?,?)",
                   (event_type, json.dumps(detail), datetime.now(timezone.utc).isoformat()))

def is_suppressed(identity):
    if not identity: return False
    with connect() as db:
        return db.execute("SELECT 1 FROM suppression WHERE identity=? COLLATE NOCASE", (identity,)).fetchone() is not None

def save_prospect(p):
    from .surreal_store import lead_identity
    identity = lead_identity(p)
    with connect() as db:
        db.execute('''INSERT OR IGNORE INTO prospects
        (dedupe_key,business_name,platform,profile_url,website,description,signal,source_url,source_date,
         score,priority,qualified,segment,subscription_fit,score_reasons,raw_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (identity,p.business_name,p.platform,p.profile_url,p.website,p.description,p.signal,p.source_url,
         p.source_date,p.score,p.priority,int(p.qualified),p.segment,p.subscription_fit,json.dumps(p.score_reasons),
         json.dumps(p.raw, default=str),datetime.now(timezone.utc).isoformat()))
        row = db.execute("SELECT id FROM prospects WHERE dedupe_key=?", (identity,)).fetchone()
        return row["id"] if row else None

def save_draft(prospect_id, subject, message):
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO drafts(prospect_id,subject,message,created_at) VALUES(?,?,?,?)",
                   (prospect_id,subject,message,datetime.now(timezone.utc).isoformat()))

def rows(query, args=()):
    with connect() as db:
        return [dict(r) for r in db.execute(query,args).fetchall()]


def save_research(prospect_id: int, result: dict):
    with connect() as db:
        db.execute("""INSERT INTO research_briefs
          (prospect_id,mind_id,conversation_alias,research_text,created_at)
          VALUES(?,?,?,?,?)
          ON CONFLICT(prospect_id) DO UPDATE SET
          mind_id=excluded.mind_id,conversation_alias=excluded.conversation_alias,
          research_text=excluded.research_text,created_at=excluded.created_at""",
          (prospect_id,result['mind_id'],result['alias'],result['reply'],
           datetime.now(timezone.utc).isoformat()))

def get_research(prospect_id: int):
    result = rows('SELECT * FROM research_briefs WHERE prospect_id=?',(prospect_id,))
    return result[0] if result else None


def save_interest(prospect_id: int, evidence_url: str, note: str, status: str):
    from .config import get_settings
    s = get_settings()
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        db.execute('''INSERT INTO subscription_opportunities
          (prospect_id,stage,evidence_url,note,currency,billing_interval,price_gbp,created_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?,?)
          ON CONFLICT(prospect_id) DO UPDATE SET stage=excluded.stage,
          evidence_url=excluded.evidence_url,note=excluded.note,updated_at=excluded.updated_at''',
          (prospect_id,status,evidence_url,note,s.subscription_currency,
           s.subscription_interval,s.subscription_price_gbp,now,now))
    return rows('SELECT * FROM subscription_opportunities WHERE prospect_id=?',(prospect_id,))[0]


def update_prospect_scoring(prospect_id: int, item):
    """Update an existing local prospect after the research assessment stage."""
    with connect() as db:
        db.execute('''UPDATE prospects SET score=?,priority=?,qualified=?,segment=?,
            subscription_fit=?,score_reasons=? WHERE id=?''',
            (item.score,item.priority,int(item.qualified),item.segment,
             item.subscription_fit,json.dumps(item.score_reasons),prospect_id))
