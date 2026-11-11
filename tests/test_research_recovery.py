"""Recovery and the pasted DPL research contract, using fake services only."""
import asyncio
import json
from app.models import Prospect
from app.research_jobs import process_research, reconcile_pending
from app.research_assessment import classify_research, apply_research_assessment
from app.surreal_store import lead_identity
from tests.test_persistence_end_to_end import FakePersistentStore as BaseStore

class FakePersistentStore(BaseStore):
    def list_records(self, table, limit=100):
        return [dict(data, prospect_identity=identity)
                for (name, identity), data in self.tables.items() if name == table][:limit]



def prospect():
    return Prospect(business_name='DPL Seller Academy', platform='youtube_direct',
        profile_url='https://www.youtube.com/channel/UCeChZk4udBaifSp0zDIFkDw',
        source_url='https://www.youtube.com/watch?v=5FhWPjEmnQQ',
        signal='5 Marketing Trends Small Businesses can Actually Use in 2026',
        segment='small_business',
        description='Publishes guides and tutorials for marketplace sellers')


def complete_report():
    return {'status':'completed',
        'summary':'DPL Seller Academy publishes timely tutorials; no demonstrated content-marketing pain, and existing trend monitoring is contrary evidence.',
        'segment':'small_business',
        'content_challenges':['No observed difficulty producing content', 'Existing in-house trend monitoring'],
        'recurring_need':'possible', 'subscription_fit':'possible', 'confidence':'medium',
        'evidence':[{'source_url':'[imagehttps://dpl.company/blogs/',
                     'quote':'Existing trend monitoring is in use', 'observed_at':'2026-11-11'}],
        'hypotheses':['They may not need the service'],
        'limitations':['No decision-maker or willingness to subscribe identified']}


def test_supplied_dpl_report_format_accepted_but_bad_links_are_not_evidence():
    p = prospect()
    data = {'reply':json.dumps(complete_report())}
    assert classify_research(data)=='completed'
    checked=apply_research_assessment(p, data)
    assert checked['evidence_accepted']==0
    assert checked['verified_findings']==[]
    assert p.qualified is False


def test_resume_across_sandboxes_does_not_send_twice():
    store=FakePersistentStore()
    p=prospect()
    identity=lead_identity(p)
    store.save_prospect(identity,p.model_dump())
    count={'start':0,'poll':0}
    async def start(_):
        count['start']+=1
        return {'alias':'research_abc', 'mind_id':'test', 'reply':'On it, I am starting research.',
                'pending':True, 'after_fingerprint':'before-start'}
    async def poll(state):
        count['poll']+=1
        assert state['alias']=='research_abc'
        assert state['after_fingerprint']=='before-start'
        return {'alias':state['alias'], 'mind_id':'test', 'reply':json.dumps(complete_report()),
                'after_fingerprint':state['after_fingerprint']}
    first=asyncio.run(process_research(store,p.model_dump(),start_fn=start,poll_fn=poll))
    assert first['research_status']=='pending'
    assert store.get_research(identity)['after_fingerprint']=='before-start'
    # Fake fresh sandbox: only store survives, no SQLite ID is passed.
    second=asyncio.run(reconcile_pending(store,limit=1,poll_fn=poll))
    assert second[0]['research_status']=='completed'
    assert second[0]['assessment']['evidence_accepted']==0
    assert count=={'start':1,'poll':1}
    assert store.get('outreach_drafts',identity) is None
    again=asyncio.run(reconcile_pending(store,limit=1,poll_fn=poll))
    assert again==[]


def test_suppression_prevents_recovering_pending_job():
    store=FakePersistentStore()
    p=prospect()
    identity=lead_identity(p)
    store.save_prospect(identity,p.model_dump())
    store.save_research(identity,{'status':'pending','alias':'research_abc',
                                  'after_fingerprint':'prior','reply':''})
    store.suppress(identity,'no contact')
    async def fail(_):
        raise AssertionError('Suppressed prospect was polled')
    result=asyncio.run(reconcile_pending(store,limit=1,poll_fn=fail))
    assert result==[]


def test_legacy_pending_job_without_marker_requires_manual_review():
    store=FakePersistentStore()
    p=prospect()
    identity=lead_identity(p)
    store.save_prospect(identity,p.model_dump())
    store.save_research(identity,{'status':'pending','alias':'old_alias','reply':'On it'})
    async def fail(_):
        raise AssertionError('Never poll without saved history marker')
    result=asyncio.run(process_research(store,p.model_dump(),poll_fn=fail))
    assert result['research_status']=='manual_review'


def test_import_completed_legacy_report_no_unsupported_draft(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app import main
    from app.config import get_settings
    from app.database import init_db
    store=FakePersistentStore()
    p=prospect()
    identity=lead_identity(p)
    store.save_prospect(identity, p.model_dump())
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'test.sqlite'))
    monkeypatch.setenv('AGENT_API_KEY','')
    monkeypatch.setenv('SURREAL_ENABLED','true')
    get_settings.cache_clear()
    init_db()
    monkeypatch.setattr(main,'enabled_store',lambda:store)
    try:
        r=TestClient(main.app).post('/research/persistent/import', json={
            'identity':identity, 'alias':'legacy_conversation', 'report':complete_report()})
        assert r.status_code==200, r.text
        body=r.json()
        assert body['research_status']=='completed'
        assert body['assessment']['evidence_accepted']==0
        assert body['draft_prepared'] is False
        assert store.get_research(identity)['imported_from_history'] is True
        assert store.get('outreach_drafts',identity) is None
    finally:
        get_settings.cache_clear()
