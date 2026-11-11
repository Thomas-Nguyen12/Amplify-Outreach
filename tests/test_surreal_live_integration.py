"""OPT-IN database CRUD test. Never runs in normal pytest or production tables.

Runs using ONLY the configured namespace/database: provision a dedicated test
namespace/database before enabling. It creates uniquely keyed synthetic records
then cleans them up. It does not contact people or social APIs.
"""
import os
import uuid
import pytest

@pytest.mark.skipif(os.getenv('RUN_SURREAL_INTEGRATION') != 'yes',
                    reason='Set RUN_SURREAL_INTEGRATION=yes with a TEST-only database')
def test_real_surreal_round_trip(monkeypatch):
    from app.config import get_settings
    from app.surreal_store import PersistentStore, canonical_identity
    monkeypatch.setenv('SURREAL_ENABLED','true')
    get_settings.cache_clear()
    settings=get_settings()
    if not (settings.surreal_url and settings.surreal_password):
        pytest.fail('SurrealDB credentials missing')
    if settings.surreal_database.lower() not in ('test', 'testing', 'simulation', 'integration_test'):
        pytest.fail('Refusing to run destructive CRUD test outside a designated test database')
    store=PersistentStore(settings)
    marker=uuid.uuid4().hex
    identity=canonical_identity(f'https://{marker}.example.invalid')
    # Test only isolated deterministic IDs created by THIS invocation.
    tables=['prospects','suppression','research_briefs','outreach_drafts']
    try:
        assert store.ping()
        assert store.get_prospect(identity) is None
        store.save_prospect(identity, {'business_name':'FICTIONAL TEST BUSINESS',
                                      'segment':'startup','score':91})
        result=store.get_prospect(identity)
        assert result is not None and result['business_name']=='FICTIONAL TEST BUSINESS'
        store.suppress(identity,'automated opt-out scenario')
        assert store.is_suppressed(identity)
        store.save_research(identity, {'mind_id':'simulated','alias':'test',
                                       'reply':'Synthetic research only'})
        assert store.get_research(identity)['reply']=='Synthetic research only'
        store.save_draft(identity,'Synthetic subject','Message NOT SENT')
        assert store.get_draft(identity)['sent'] is False
        store2=PersistentStore(settings)
        assert store2.is_suppressed(identity)
        assert store2.get_prospect(identity)['score']==91
    finally:
        for table in reversed(tables):
            store.remove(table,identity)
        get_settings.cache_clear()
