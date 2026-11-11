"""Consent-first automated email outreach, with no per-message review.

Fails closed unless ALL operational, hackathon and recipient-level gates pass.
Never sends social-platform DMs/comments. Uses Resend's idempotency header plus
SurrealDB atomic claims to avoid duplicates across Daytona sandboxes.
"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone
from email.utils import parseaddr
from urllib.request import Request, urlopen
from .config import get_settings
from .drafts import _PRICE
from .surreal_store import canonical_identity

EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

def email_address(value: str) -> str:
    addr = parseaddr(str(value or ''))[1].strip().lower()
    if addr != str(value or '').strip().lower() or not EMAIL_RE.fullmatch(addr):
        raise ValueError('Valid plain email address required')
    return addr

def now():
    return datetime.now(timezone.utc).isoformat()

def configure_status(settings=None):
    s = settings or get_settings()
    gmail_checks = {}
    if getattr(s,'outreach_provider','resend') == 'gmail':
        from .gmail_service import token_status
        gmail_checks = token_status(s)
    provider_ok = (bool(s.resend_api_key and s.outreach_from_email and s.outreach_reply_to)
                   if getattr(s,'outreach_provider','resend') == 'resend'
                   else bool(s.outreach_from_email and s.outreach_reply_to and all(gmail_checks.values())))
    checks = {
        'enabled': s.outreach_autosend_enabled,
        'organiser_permission': s.hackathon_outreach_permission_granted and bool(s.hackathon_permission_reference.strip()),
        'approved_email_channel': s.outreach_email_channel_permitted,
        'surrealdb': s.surreal_enabled,
        'api_authentication': bool(s.agent_api_key),
        'provider_credentials': provider_ok,
        'sender_identity': bool(s.outreach_sender_name.strip()),
        'daily_limit': s.outreach_max_per_day > 0,
    }
    return {'ready':all(checks.values()), 'checks': checks, 'mode':'explicit_opt_in_only',
            'human_per_message_approval':False, 'channels':['email'], 'provider':getattr(s,'outreach_provider','resend'), 'outreach_live': s.outreach_autosend_enabled}

def register_contact(store, *, identity, email, source_url, consent_reference, consent_at,
                     consent_method, jurisdiction, known_contact=False, excluded=False):
    """Record *documented* consent; self-entered assertions are not independently verified.

    Do not use for an address merely appearing on a YouTube About or website page.
    The operator must have independent, auditable, affirmative opt-in evidence.
    """
    identity = canonical_identity(identity)
    addr = email_address(email)
    if not source_url.startswith('https://') or not consent_reference.startswith('https://'):
        raise ValueError('HTTPS contact source and auditable consent evidence URLs required')
    if consent_method not in ('opt_in_form','inbound_request','double_opt_in'):
        raise ValueError('Only explicit opt-in methods are accepted')
    timestamp = datetime.fromisoformat(consent_at.replace('Z','+00:00'))
    if not timestamp.tzinfo or timestamp > datetime.now(timezone.utc):
        raise ValueError('Consent timestamp must be timezone-aware and not in the future')
    if (datetime.now(timezone.utc)-timestamp).days > 365:
        raise ValueError('Consent too old: obtain fresh permission')
    if not jurisdiction.strip() or known_contact or excluded:
        raise ValueError('Unknown jurisdiction or excluded/known contact')
    if not store.get_prospect(identity):
        raise ValueError('Prospect not found in persistent store')
    if store.is_suppressed(identity) or store.is_suppressed('mailto:'+addr):
        raise ValueError('Prospect or email address suppressed')
    payload = {'prospect_identity':identity,'email':addr,'source_url':source_url,
               'consent_reference':consent_reference,'consent_at':timestamp.isoformat(),
               'consent_method':consent_method,'jurisdiction':jurisdiction,
               'known_contact':False,'excluded':False,'status':'active',
               'recorded_at':now()}
    store.put('contact_routes',identity,payload)
    return {'identity':identity,'email':addr,'status':'active',
            'notice':'Evidence provided by operator; actual consent not independently validated'}

def suppress_email(store, email: str, reason='Opted out'):
    address = email_address(email)
    store.suppress('mailto:'+address,reason)
    route_identities=[]
    for route in store.list_records('contact_routes',500):
        if route.get('email','').lower()==address:
            identity=route.get('prospect_identity','')
            if identity:
                store.suppress(identity,reason)
                route_identities.append(identity)
    return {'email':address,'suppressed_identities':route_identities}

def send_resend(*, to, subject, message, idempotency_key, settings=None):
    """Only invoke after all gates and atomic claims have succeeded."""
    s = settings or get_settings()
    payload={'from':f'{s.outreach_sender_name} <{email_address(s.outreach_from_email)}>',
             'reply_to':email_address(s.outreach_reply_to),'to':[email_address(to)],
             'subject':subject,'text':message}
    req=Request('https://api.resend.com/emails',data=json.dumps(payload).encode(),
        headers={'Authorization':'Bearer '+s.resend_api_key,
                 'Content-Type':'application/json','Idempotency-Key':idempotency_key},method='POST')
    with urlopen(req,timeout=20) as resp:
        data=json.loads(resp.read().decode('utf-8'))
    if not data.get('id'):
        raise RuntimeError('Email provider did not confirm acceptance')
    return {'provider_id':data['id'],'status':'accepted_by_provider'}

def dispatch_one(store, identity, *, settings=None, provider=None):
    """Automatically send exactly one email if all eligibility gates succeed.

    No automatic retry after uncertainty, including process crash after claim.
    A positive provider response means *accepted*, not delivered/read.
    """
    s=settings or get_settings()
    identity=canonical_identity(identity)
    state=configure_status(s)
    if not state['ready']:
        return {'status':'blocked_configuration','missing':[k for k,v in state['checks'].items() if not v]}
    lead=store.get_prospect(identity)
    route=store.get('contact_routes',identity)
    research=store.get_research(identity)
    draft=store.get_draft(identity)
    if not lead or not route or not research or not draft:
        return {'status':'blocked_missing_records'}
    from .research_assessment import classify_research
    if (not lead.get('qualified') or int(lead.get('score',0)) < s.minimum_lead_score
            or lead.get('segment') not in {'small_business','startup','influencer'}
            or lead.get('research_assessment_status') != 'completed_with_correlated_evidence'
            or classify_research(research) != 'completed'
            or route.get('status')!='active' or route.get('known_contact') or route.get('excluded')
            or route.get('consent_method') not in ('opt_in_form','inbound_request','double_opt_in')
            or not route.get('consent_reference') or not route.get('jurisdiction')
            or draft.get('status')!='draft' or draft.get('sent') is not False):
        return {'status':'blocked_ineligible'}
    addr=email_address(route['email'])
    if store.is_suppressed(identity) or store.is_suppressed('mailto:'+addr):
        return {'status':'blocked_suppressed'}
    # Avoid sending if permission has been revoked or become stale since registration.
    when=datetime.fromisoformat(route['consent_at'].replace('Z','+00:00'))
    if not when.tzinfo or (datetime.now(timezone.utc)-when).days > 365:
        return {'status':'blocked_stale_consent'}
    subject=str(draft.get('subject','')).strip()
    body=str(draft.get('message','')).strip()
    if not subject or not body or _PRICE.search(subject+'\n'+body):
        return {'status':'blocked_invalid_draft'}
    if 'human review' in body.lower() or 'has not been sent' in body.lower():
        return {'status':'blocked_legacy_draft'}
    if 'AI assistance' not in body:
        return {'status':'blocked_missing_ai_disclosure'}
    # Insert traceable sender and an actionable opt-out by replying.
    body=body+f'\n\nSender: {s.outreach_sender_name}\nFor no further contact, reply STOP to {email_address(s.outreach_reply_to)}.\n'
    if _PRICE.search(body):
        return {'status':'blocked_price'}
    # Check existing contact claim, then reserve one globally shared daily slot.
    # Race-safe atomic slot creation means parallel Daytona sandboxes cannot
    # exceed the configured day cap. A duplicate race may waste a slot safely.
    claim_id='mailto:'+addr
    if store.get('outreach_send_claims',claim_id):
        return {'status':'already_claimed'}
    day=datetime.now(timezone.utc).date().isoformat()
    slot=None
    for n in range(s.outreach_max_per_day):
        key=f'{day}:{n}'
        if store.create_once('outreach_daily_slots',key,{'day':day,'slot':n,'email':addr,'identity':identity,'at':now()}):
            slot=n
            break
    if slot is None:
        return {'status':'blocked_daily_cap'}
    claim={'prospect_identity':identity,'email':addr,'claimed_at':now(),
           'status':'claimed_unknown_until_confirmed'}
    if not store.create_once('outreach_send_claims',claim_id,claim):
        return {'status':'already_claimed'}
    key='social-trend-first-contact-'+hashlib.sha256(addr.encode()).hexdigest()[:48]
    attempt={'identity':identity,'email':addr,'day':day,'slot':slot,
             'idempotency_key':key,'status':'unknown','created_at':now()}
    store.put('outreach_send_attempts',claim_id,attempt)
    try:
        if provider is None:
            if getattr(s,'outreach_provider','resend') == 'gmail':
                from .gmail_service import send_gmail
                provider=send_gmail
            else:
                provider=send_resend
        delivery=provider(to=addr,subject=subject,message=body,
                                           idempotency_key=key,settings=s)
    except Exception as exc:
        store.put('outreach_send_attempts',claim_id,{**attempt,'status':'unknown','error_type':type(exc).__name__})
        return {'status':'unknown','notice':'Do not retry automatically; inspect provider dashboard'}
    # Provider acceptance is NOT delivery confirmation.
    store.put('outreach_send_attempts',claim_id,{**attempt,**delivery,'updated_at':now()})
    store.put('outreach_send_claims',claim_id,{**claim,'status':'accepted_by_provider'})
    store.put('outreach_drafts',identity,{**{k:v for k,v in draft.items() if k!='id'},
        'status':'sent','sent':True,'provider_id':delivery['provider_id'],'sent_at':now()})
    return {'status':'accepted_by_provider','provider_id':delivery['provider_id'],'email':addr}

def dispatch_ready(store, limit=3, *, provider=None):
    outcomes=[]
    for draft in store.list_records('outreach_drafts',500):
        if len(outcomes)>=limit: break
        if draft.get('status')!='draft': continue
        identity=draft.get('prospect_identity')
        if not identity or not store.get('contact_routes',identity):
            continue  # Avoid starving eligible opt-in leads behind uncontactable drafts.
        result=dispatch_one(store,identity,provider=provider)
        outcomes.append({'identity':identity,**result})
    return outcomes
