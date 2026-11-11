from app.config import get_settings
from app.database import init_db, connect
from scripts.migrate_sqlite_to_surreal import migrate
from tests.test_persistence_end_to_end import FakePersistentStore


def test_migration_dry_run_and_suppression_first(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'legacy.sqlite'))
    monkeypatch.setenv('SURREAL_ENABLED','true')
    get_settings.cache_clear()
    init_db()
    with connect() as db:
        db.execute('''INSERT INTO prospects
        (dedupe_key,business_name,platform,source_url,score,priority,qualified,
         segment,subscription_fit,score_reasons,raw_json,created_at)
         VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
         ('https://startup.example','Fictional Startup','web','https://startup.example',
          86,'high',1,'startup',15,'[]','{}','2026-11-10'))
        db.execute("INSERT INTO suppression(identity,reason,created_at) VALUES(?,?,?)",
                   ('https://startup.example','opt out','2026-11-10'))
    fake=FakePersistentStore()
    assert migrate(apply=False,store=fake)['prospects']==1
    assert not fake.tables
    result=migrate(apply=True,store=fake)
    assert result['written_prospects']==1
    assert result['written_suppressions']==1
    assert fake.is_suppressed('https://startup.example')
    assert migrate(apply=True,store=fake)['written_prospects']==0
    get_settings.cache_clear()
