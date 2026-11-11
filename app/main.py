import csv, io
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from .config import get_settings
from .models import RunRequest, InterestRequest
from .database import init_db, rows, connect, audit, get_research, save_research, save_interest
from .pipeline import run_pipeline
from .treg import PLATFORMS
from .hellominds import research_lead
from .surreal_store import mirror_research, mirror_record, enabled_store, canonical_identity
from .targeting import DEFAULT_QUERIES
from .scoring import score_item
from .research_assessment import apply_research_assessment, classify_research
from .database import update_prospect_scoring
from .models import Prospect
from .surreal_store import lead_identity

app=FastAPI(title=get_settings().app_name,version="1.0.0")

@app.middleware('http')
async def require_agent_key(request: Request, call_next):
    key=get_settings().agent_api_key
    if key and request.url.path not in ('/health', '/openapi.json', '/docs', '/redoc'):
        import secrets
        if not secrets.compare_digest(request.headers.get('x-agent-key',''), key):
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'Invalid agent API key'}, status_code=401)
    return await call_next(request)

@app.on_event("startup")
def startup(): init_db()

@app.get("/health")
def health(): return {"status":"ok","app":get_settings().app_name}

@app.get('/config/targeting')
def targeting():
    s=get_settings()
    return {'segments':[x.strip() for x in s.target_segments.split(',') if x.strip()],
            'discovery_mode':s.discovery_mode,'report_frequency':s.report_frequency,
            'default_queries':DEFAULT_QUERIES,
            'offer':{'type':'subscription','currency':s.subscription_currency,
                     'interval':s.subscription_interval,'price_gbp':s.subscription_price_gbp or None,
                     'insights_frequency':s.report_frequency,
                     'teaser_url':s.teaser_url or None},'outreach_enabled':s.outreach_autosend_enabled}

@app.get("/config/platforms")
def platforms():
    s=get_settings()
    return {"web":{"enabled":s.tavily_enabled and bool(s.tavily_api_key),"api_key_configured":bool(s.tavily_api_key)},
      "youtube_direct":{"enabled":s.youtube_enabled and bool(s.youtube_api_key),
                        "api_key_configured":bool(s.youtube_api_key),
                        "searches_per_run":s.youtube_max_searches_per_run},
      **{p:{"enabled":s.treg_enabled and bool(s.treg_token) and bool(s.endpoint_for(p)),
            "endpoint_configured":bool(s.endpoint_for(p))} for p in PLATFORMS}}

@app.post("/agent/run")
async def run(req:RunRequest):
    s=get_settings()
    try:
        result = await run_pipeline(req.queries,req.platforms,req.max_results_per_query,s.minimum_lead_score)
        # No per-message human approval. Autosend still requires every documented
        # organisation, channel, research, recipient and suppression gate.
        from .outreach import configure_status, dispatch_ready
        if configure_status()['ready']:
            result['outreach'] = dispatch_ready(enabled_store(), limit=get_settings().outreach_max_per_day)
        return result
    except ValueError as e: raise HTTPException(400,str(e))
    except Exception as e:
        audit("run_error",{"error":str(e)})
        raise HTTPException(500,"Agent run failed; inspect server logs.")

@app.get('/persistent/leads')
def persistent_leads(limit: int = 100):
    """Cross-sandbox canonical leads (unlike /leads local SQLite cache)."""
    store = enabled_store()
    if not store:
        raise HTTPException(409,'SURREAL_ENABLED is not configured')
    try:
        records = store.list_records('prospects',limit)
        return [{**record, 'id': str(record.get('id', ''))} for record in records]
    except Exception:
        raise HTTPException(503,'Persistent prospect storage unavailable')

@app.get("/leads")
def leads(limit:int=100):
    return rows("SELECT * FROM prospects ORDER BY score DESC,created_at DESC LIMIT ?",(min(max(limit,1),500),))

@app.get("/leads/{lead_id}")
def lead(lead_id:int):
    r=rows("SELECT * FROM prospects WHERE id=?",(lead_id,))
    if not r: raise HTTPException(404,"Lead not found")
    return r[0]

@app.get("/drafts")
def drafts():
    return rows("SELECT d.*,p.business_name,p.platform,p.source_url FROM drafts d JOIN prospects p ON p.id=d.prospect_id ORDER BY d.created_at DESC")

@app.post("/suppression")
def suppress(body:dict):
    identity=str(body.get("identity","")).strip().lower().rstrip("/")
    reason=str(body.get("reason","User requested no further contact"))
    if not identity: raise HTTPException(400,"identity is required")
    identity = canonical_identity(identity)
    store = enabled_store()
    # Persist the opt-out before updating the disposable SQLite cache.
    # Do not acknowledge suppression if SurrealDB cannot store it.
    if store:
        try:
            store.suppress(identity, reason)
        except Exception:
            raise HTTPException(503, 'Persistent suppression storage unavailable')
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO suppression(identity,reason,created_at) VALUES(?,?,datetime('now'))",(identity,reason))
    audit("suppression_added",{"identity":identity,"reason":reason})
    return {"status":"suppressed","identity":identity}

@app.get('/persistence/status')
def persistence_status():
    store = enabled_store()
    if not store:
        return {'mode':'sqlite_only', 'surreal_connected':False}
    try:
        store.ping()
        return {'mode':'surreal_authoritative_live', 'surreal_connected':True,
                'namespace':get_settings().surreal_namespace,
                'database':get_settings().surreal_database}
    except Exception:
        raise HTTPException(503,'SurrealDB is unavailable; check server logs')


@app.get("/metrics")
def metrics():
    with connect() as db:
        return {
          "subscription_opportunities":db.execute("SELECT COUNT(*) FROM subscription_opportunities").fetchone()[0],
          "small_business_leads":db.execute("SELECT COUNT(*) FROM prospects WHERE segment='small_business'").fetchone()[0],
          "startup_leads":db.execute("SELECT COUNT(*) FROM prospects WHERE segment='startup'").fetchone()[0],
          "influencer_leads":db.execute("SELECT COUNT(*) FROM prospects WHERE segment='influencer'").fetchone()[0],
          "prospects":db.execute("SELECT COUNT(*) FROM prospects").fetchone()[0],
          "qualified":db.execute("SELECT COUNT(*) FROM prospects WHERE qualified=1").fetchone()[0],
          "drafts":db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0],
          "suppressed":db.execute("SELECT COUNT(*) FROM suppression").fetchone()[0],
          "events":db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]}

@app.get("/export/leads.csv")
def export():
    data=rows("SELECT business_name,platform,profile_url,website,description,signal,source_url,score,priority,qualified,created_at FROM prospects ORDER BY score DESC")
    out=io.StringIO()
    if data:
        w=csv.DictWriter(out,fieldnames=data[0].keys()); w.writeheader(); w.writerows(data)
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",
      headers={"Content-Disposition":"attachment; filename=leads.csv"})


@app.get("/research")
def research_list(limit:int=100):
    return rows("""SELECT r.*,p.business_name,p.website,p.source_url
      FROM research_briefs r JOIN prospects p ON p.id=r.prospect_id
      ORDER BY r.created_at DESC LIMIT ?""",(min(max(limit,1),500),))

@app.get("/research/{lead_id}")
def research_detail(lead_id:int):
    result=get_research(lead_id)
    if not result: raise HTTPException(404,"Research not found")
    return result

@app.post("/research/{lead_id}/run")
async def research_run(lead_id: int):
    """Research a local lead regardless of initial qualification (no outreach)."""
    records = rows("SELECT * FROM prospects WHERE id=?", (lead_id,))
    if not records:
        raise HTTPException(404, "Lead not found")
    record = records[0]
    s = get_settings()
    store = enabled_store()
    try:
        # No AI-based escalation for a prospect on the suppression list.
        identity = lead_identity(record)
        from .database import is_suppressed
        if (store and store.is_suppressed(identity)) or is_suppressed(identity):
            raise HTTPException(409, 'Prospect is suppressed; research blocked')
        previous = store.get_research(identity) if store else None
        if previous and previous.get('status') == 'pending':
            from .hellominds import resume_research
            if 'after_fingerprint' not in previous:
                return {'lead_id':lead_id,'research_status':'manual_review',
                        'notice':'Legacy pending task has no saved history marker; inspect conversation history.',
                        'outreach_sent':False}
            result = await resume_research(previous)
        else:
            result = await research_lead(record)
        research_status = classify_research(result)
        if research_status != 'completed':
            if store:
                store.save_research(identity, result)
            audit('research_pending', {'lead_id': lead_id, 'mind_id':result.get('mind_id'), 'status':research_status})
            return {'lead_id':lead_id, **result, 'research_status':research_status,
                    'research_completed':False, 'outreach_sent':False,
                    'notice':'No completed structured report received. No research qualification or draft created.'}
        import json
        source = {k: record[k] for k in Prospect.model_fields if k in record}
        if isinstance(source.get('score_reasons'), str):
            source['score_reasons'] = json.loads(source['score_reasons'])
        item = Prospect(**source)
        score_item(item)
        assessment = apply_research_assessment(item, result)
        # Durable first, local cache second.
        if store:
            store.save_research(identity, result)
            remote = store.get_prospect(identity) or {}
            store.put('prospects', identity, {
                **{k: v for k, v in remote.items() if k != 'id'},
                **item.model_dump(exclude={'raw'}), 'dedupe_key': identity,
                'research_assessment_status': assessment['status'],
            })
        save_research(lead_id, result)
        update_prospect_scoring(lead_id, item)
        audit('research_completed', {'lead_id': lead_id, 'mind_id': result.get('mind_id'),
                                     'research_assessment': assessment['status']})
        return {'lead_id': lead_id, **result, 'research_status':'completed', 'research_completed':True, 'qualification': {
            'score': item.score, 'qualified': item.qualified,
            'assessment': assessment, 'outreach_sent': False,
        }}
    except HTTPException:
        raise
    except Exception as exc:
        audit('research_error', {'lead_id': lead_id, 'error_type': type(exc).__name__})
        raise HTTPException(502, 'Research failed; check server logs and credentials')


@app.get('/persistent/research')
def persistent_research(limit: int = 100):
    """Research statuses and report text across sandbox restarts."""
    store = enabled_store()
    if not store:
        raise HTTPException(409, 'SurrealDB persistence is required')
    return [{**r, 'id':str(r.get('id',''))}
            for r in store.list_records('research_briefs', limit)]


@app.get('/persistent/drafts')
def persistent_drafts(limit: int = 100):
    """Unsent customer-facing messages across sandbox restarts."""
    store = enabled_store()
    if not store:
        raise HTTPException(409, 'SurrealDB persistence is required')
    return [{**r, 'id':str(r.get('id',''))}
            for r in store.list_records('outreach_drafts', limit)]


@app.post('/research/persistent/import')
def import_completed_research(body: dict):
    """Manually reconcile a legacy finished Minds JSON report (never send outreach)."""
    from .surreal_store import canonical_identity
    from .research_jobs import finalize_report
    from .research_assessment import classify_research
    store = enabled_store()
    if not store:
        raise HTTPException(409, 'SurrealDB persistence is required')
    identity = body.get('identity', '')
    report = body.get('report')
    if not isinstance(identity, str) or not identity or not isinstance(report, dict):
        raise HTTPException(422, 'identity (profile URL) and report (JSON object) are required')
    try:
        identity = canonical_identity(identity)
        if store.is_suppressed(identity):
            raise HTTPException(409, 'Prospect suppressed')
        prospect = store.get_prospect(identity)
        if not prospect:
            raise HTTPException(404, 'Prospect not found in SurrealDB')
        result = {'reply':__import__('json').dumps(report),
                  'alias':str(body.get('alias','')), 'mind_id':str(body.get('mind_id','')),
                  'imported_from_history':True}
        if classify_research(result) != 'completed':
            raise HTTPException(422, 'Report must follow the completed structured research contract')
        outcome = finalize_report(store, prospect, result)
        audit('research_manual_import', {'identity':identity, 'status':outcome['research_status']})
        return {'identity':identity, 'imported':True, **outcome}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422,str(exc))


@app.get('/research/persistent/pending')
def research_pending(limit: int = 100):
    """Find durable pending Mind tasks even when SQLite is empty."""
    store = enabled_store()
    if not store:
        raise HTTPException(409, 'SurrealDB persistence is required')
    from .research_jobs import pending_record
    records = store.list_records('research_briefs', min(limit, 500))
    return [{'identity':r.get('prospect_identity'), 'alias':r.get('alias'),
             'research_status':r.get('status','unknown')}
            for r in records if pending_record(r)]


@app.post('/research/persistent/reconcile')
async def research_reconcile(limit: int = 2):
    """Resume bounded pending conversations; DOES NOT send another prompt."""
    store = enabled_store()
    if not store:
        raise HTTPException(409, 'SurrealDB persistence is required')
    from .research_jobs import reconcile_pending
    results = await reconcile_pending(store, limit=min(max(limit, 1), 10))
    from .outreach import configure_status, dispatch_ready
    dispatch = dispatch_ready(store,limit=get_settings().outreach_max_per_day) if configure_status()['ready'] else []
    return {'results': results, 'outreach':dispatch}


@app.get('/opportunities')
def opportunities(limit:int=100):
    return rows("""SELECT o.*, p.business_name,p.segment,p.website,p.source_url,p.score
       FROM subscription_opportunities o JOIN prospects p ON p.id=o.prospect_id
       ORDER BY o.updated_at DESC LIMIT ?""",(min(max(limit,1),500),))

@app.post('/opportunities/{lead_id}')
def record_opportunity(lead_id:int, body:InterestRequest):
    match=rows('SELECT * FROM prospects WHERE id=?',(lead_id,))
    if not match: raise HTTPException(404,'Lead not found')
    if not match[0]['qualified']:
        raise HTTPException(409,'Lead is not qualified for this target segment')
    opportunity=save_interest(lead_id,str(body.evidence_url),body.note,body.status)
    audit('subscription_opportunity_updated', {'lead_id':lead_id, 'stage':body.status, 'evidence_url':str(body.evidence_url)})
    if get_settings().surreal_enabled:
        try: mirror_record('subscription_opportunities',str(lead_id),opportunity)
        except Exception as e: audit('surreal_mirror_error',{'lead_id':lead_id,'stage':'opportunity','error':str(e)})
    return {'status':'recorded','opportunity':opportunity,
            'notice':'This records a sales-stage signal, NOT a paid Stripe subscription.'}


@app.get('/outreach/status')
def outreach_status():
    """Reports safety gates; never exposes secrets."""
    from .outreach import configure_status
    return configure_status()

@app.post('/outreach/contacts')
def outreach_register_contact(body: dict):
    """Register an independently evidenced explicit opt-in. Not a send approval.

    Operator must not register publicly scraped emails as consent. A real inbound
    opt-in form can call this authenticated endpoint in a future integration.
    """
    from .outreach import register_contact, configure_status, dispatch_one
    store=enabled_store()
    if not store: raise HTTPException(409,'SurrealDB required')
    try:
        record=register_contact(store,**{k:body[k] for k in (
            'identity','email','source_url','consent_reference','consent_at',
            'consent_method','jurisdiction')},
            known_contact=bool(body.get('known_contact',False)),
            excluded=bool(body.get('excluded',False)))
        sent=dispatch_one(store,record['identity']) if configure_status()['ready'] else {'status':'blocked_configuration'}
        audit('opt_in_contact_recorded',{'identity':record['identity'],'dispatch_status':sent['status']})
        return {**record,'dispatch':sent}
    except KeyError as exc: raise HTTPException(422,f'Missing field: {exc}')
    except ValueError as exc: raise HTTPException(422,str(exc))

@app.post('/outreach/dispatch')
def outreach_dispatch(limit:int=3):
    """Automatically send eligible unsent emails; no per-message approval step."""
    from .outreach import dispatch_ready, configure_status
    status=configure_status()
    if not status['ready']:
        raise HTTPException(409,{'reason':'Automated sending is not authorised/configured','checks':status['checks']})
    store=enabled_store()
    if not store: raise HTTPException(409,'SurrealDB required')
    try: return {'results':dispatch_ready(store,min(max(limit,1),get_settings().outreach_max_per_day))}
    except Exception:
        raise HTTPException(503,'Dispatch persistence unavailable; no retry until logs examined')

@app.post('/outreach/optout')
def outreach_optout(body:dict):
    """Authenticated operator/inbound opt-out endpoint; immediate global suppression."""
    from .outreach import suppress_email
    store=enabled_store()
    if not store: raise HTTPException(409,'SurrealDB required')
    try:
        return suppress_email(store,body.get('email',''),body.get('reason','Recipient opted out'))
    except ValueError as exc: raise HTTPException(422,str(exc))

@app.post('/outreach/replies')
def outreach_record_reply(body:dict):
    """Securely record a genuine reply for interested/opt-out handoff.

    This is not an inbox poller; an authenticated inbound integration must supply
    externally verified replies. Never assume a logged reply proves a sale.
    """
    from .outreach import email_address, suppress_email, now
    store=enabled_store()
    if not store: raise HTTPException(409,'SurrealDB required')
    try: addr=email_address(body.get('email',''))
    except ValueError as exc: raise HTTPException(422,str(exc))
    kind=body.get('type')
    if kind not in ('interested','question','not_interested','opt_out','other'):
        raise HTTPException(422,'Unsupported reply category')
    evidence=body.get('evidence_reference','')
    if not evidence.startswith('https://'):
        raise HTTPException(422,'Provide a restricted-access HTTPS proof reference')
    import uuid
    event_id=str(uuid.uuid4())
    store.put('outreach_reply_events',event_id,
              {'email':addr,'type':kind,'evidence_reference':evidence,'received_at':now()})
    if kind in ('opt_out','not_interested'):
        suppress_email(store,addr,'Recipient replied '+kind)
    return {'recorded':True,'type':kind,'opted_out':kind in ('opt_out','not_interested')}

@app.get('/outreach/attempts')
def outreach_attempts(limit:int=100):
    store=enabled_store()
    if not store: raise HTTPException(409,'SurrealDB required')
    return [{**r,'id':str(r.get('id',''))} for r in store.list_records('outreach_send_attempts',limit)]


@app.get('/gmail/status')
def gmail_status():
    from .gmail_service import token_status
    s=get_settings()
    return {'provider':s.outreach_provider, 'reply_poll_enabled':s.gmail_reply_poll_enabled,
            'send':token_status(s), 'read':token_status(s,require_read=True)}

@app.post('/gmail/replies/poll')
def gmail_poll_replies(limit:int=50):
    """Read inbox for correlated replies; safely suppress clear opt-outs.

    Requires X-Agent-Key middleware authentication, enabled SurrealDB, and
    GMAIL_REPLY_POLL_ENABLED=true. Never runs as an automatic sent-email trigger.
    """
    s=get_settings()
    if not s.agent_api_key:
        raise HTTPException(409,'Set AGENT_API_KEY before enabling reply polling')
    if not s.gmail_reply_poll_enabled or s.outreach_provider!='gmail':
        raise HTTPException(409,'Gmail reply polling is disabled')
    store=enabled_store()
    if not store: raise HTTPException(409,'SurrealDB required')
    from .gmail_replies import poll_replies
    try: return poll_replies(store,settings=s,limit=limit)
    except Exception:
        raise HTTPException(503,'Inbox reconciliation failed; inspect logs and do not infer all replies were read')
