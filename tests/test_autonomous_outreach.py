"""No real email network calls; fail-closed autonomy and dedup regression tests."""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from app.outreach import dispatch_one, configure_status, register_contact, suppress_email
from app.drafts import create_draft
from app.models import Prospect
from app.surreal_store import canonical_identity

@dataclass
class Config:
    outreach_autosend_enabled:bool=True
    hackathon_outreach_permission_granted:bool=True
    hackathon_permission_reference:str='https://example.org/permission/approved'
    outreach_email_channel_permitted:bool=True
    surreal_enabled:bool=True
    agent_api_key:str='secret-test-only'
    resend_api_key:str='test-fake-key'
    outreach_from_email:str='team@example.org'
    outreach_reply_to:str='reply@example.org'
    outreach_sender_name:str='Social Trend Team'
    outreach_max_per_day:int=2
    minimum_lead_score:int=70

class FakeStore:
    def __init__(self): self.tables={};self.blocked=set()
    def get(self, table, identity): return self.tables.get(table,{}).get(identity)
    def put(self,table,identity,data): self.tables.setdefault(table,{})[identity]=data.copy()
    def create_once(self,table,identity,data):
        if identity in self.tables.get(table,{}): return False
        self.put(table,identity,data);return True
    def list_records(self,table,limit=100): return list(self.tables.get(table,{}).values())[:limit]
    def is_suppressed(self, identity): return identity in self.blocked
    def suppress(self,identity,reason): self.blocked.add(identity)
    def get_prospect(self,identity):return self.get('prospects',identity)
    def get_research(self,identity):return self.get('research_briefs',identity)
    def get_draft(self,identity):return self.get('outreach_drafts',identity)

def fixture():
    s=Config(); store=FakeStore()
    identity=canonical_identity('https://youtube.com/channel/UCexample')
    store.put('prospects',identity,{'qualified':True,'score':85,'segment':'small_business',
                'research_assessment_status':'completed_with_correlated_evidence'})
    payload={'status':'completed','summary':'Evidence exists','content_challenges':['content ideas'],
             'evidence':[{'source_url':'https://example.org/post','quote':'We need content ideas'}],
             'limitations':[]}
    store.put('research_briefs',identity,{'reply':json.dumps(payload),'status':'completed'})
    p=Prospect(business_name='Example Ltd',platform='youtube_direct',source_url='https://example.org/post')
    subj, msg=create_draft(p)
    store.put('outreach_drafts',identity,{'prospect_identity':identity,'subject':subj,
                                       'message':msg,'sent':False,'status':'draft'})
    return s,store,identity

def consent(store,identity,email='hello@example.org'):
    return register_contact(store,identity=identity,email=email,source_url='https://example.org/contact',
        consent_reference='https://example.org/optins/123',consent_at=datetime.now(timezone.utc).isoformat(),
        consent_method='double_opt_in',jurisdiction='UK')

def test_off_by_default():
    config=Config(outreach_autosend_enabled=False)
    assert not configure_status(config)['ready']

def test_blocked_without_registered_contact():
    s,store,i=fixture(); assert dispatch_one(store,i,settings=s)['status']=='blocked_missing_records'

def test_consent_not_inferred_from_public_email():
    s,store,i=fixture()
    try:
        register_contact(store,identity=i,email='hello@example.org',source_url='https://example.org',
            consent_reference='https://example.org/evidence',consent_at=datetime.now(timezone.utc).isoformat(),
            consent_method='publicly_listed',jurisdiction='UK')
    except ValueError: pass
    else: raise AssertionError('public email is not consent')

def test_single_autosend_dedup_and_no_price():
    s,store,i=fixture();consent(store,i)
    sent=[]
    def provider(**kw):
        sent.append(kw);return {'provider_id':'email-test-1','status':'accepted_by_provider'}
    first=dispatch_one(store,i,settings=s,provider=provider)
    assert first['status']=='accepted_by_provider'
    assert len(sent)==1 and '£7' not in sent[0]['message']
    assert 'AI assistance' in sent[0]['message'] and 'reply STOP' in sent[0]['message']
    assert dispatch_one(store,i,settings=s,provider=provider)['status'] in ('blocked_ineligible','already_claimed')
    assert len(sent)==1

def test_suppression_blocks_and_optout_cross_identity():
    s,store,i=fixture();consent(store,i)
    suppress_email(store,'hello@example.org')
    assert dispatch_one(store,i,settings=s)['status']=='blocked_suppressed'

def test_organiser_not_authorised_cannot_send():
    s,store,i=fixture();consent(store,i)
    s.hackathon_outreach_permission_granted=False
    assert dispatch_one(store,i,settings=s)['status']=='blocked_configuration'

def test_legacy_draft_blocked():
    s,store,i=fixture();consent(store,i)
    store.tables['outreach_drafts'][i]['message']+='\nhuman review; has not been sent'
    assert dispatch_one(store,i,settings=s)['status']=='blocked_legacy_draft'

def test_unknown_provider_response_never_retries():
    s,store,i=fixture();consent(store,i)
    def fail(**kw):raise TimeoutError('ambiguous timeout')
    assert dispatch_one(store,i,settings=s,provider=fail)['status']=='unknown'
    assert dispatch_one(store,i,settings=s,provider=fail)['status']=='already_claimed'

def test_daily_cap_is_shared_slots():
    s,store,i=fixture();consent(store,i)
    s.outreach_max_per_day=0
    assert dispatch_one(store,i,settings=s)['status']=='blocked_configuration'

def test_daily_cap_blocks_next_distinct_consent_and_no_network_send():
    s,store,i=fixture();consent(store,i)
    s.outreach_max_per_day=1
    sent=[]
    def provider(**kw):
        sent.append(kw);return {'provider_id':'id'+str(len(sent))}
    j=canonical_identity('https://youtube.com/channel/UCsecond')
    for tab in ('prospects','research_briefs','outreach_drafts'):
        store.put(tab,j,store.get(tab,i))
    store.tables['outreach_drafts'][j]['prospect_identity']=j
    consent(store,j,email='different@example.org')
    assert dispatch_one(store,i,settings=s,provider=provider)['status']=='accepted_by_provider'
    assert dispatch_one(store,j,settings=s,provider=provider)['status']=='blocked_daily_cap'
    assert len(sent)==1


def test_dispatch_skips_leads_without_opt_in():
    from app.outreach import dispatch_ready
    s,store,i=fixture()
    assert dispatch_ready(store,limit=2,provider=lambda **kwargs:None)==[]
