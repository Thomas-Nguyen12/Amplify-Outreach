"""Durable HelloMinds research lifecycle for ephemeral Daytona workers.

Pending jobs live in the existing SurrealDB research_briefs table. A retry polls
its original conversation; it does NOT send another prompt. Explicit human
reconciliation is needed for legacy jobs lacking a history marker.
"""
import json
from .hellominds import research_lead, resume_research, research_alias
from .research_assessment import classify_research, apply_research_assessment
from .scoring import score_item
from .models import Prospect
from .surreal_store import lead_identity
from .drafts import create_draft
from .config import get_settings
import asyncio
import os
from pathlib import Path

def pending_record(record):
    return bool(record) and record.get('status', classify_research(record)) != 'completed'


def _item(prospect):
    data = {k: prospect[k] for k in Prospect.model_fields if k in prospect}
    if isinstance(data.get('score_reasons'), str):
        data['score_reasons'] = json.loads(data['score_reasons'])
    return Prospect(**data)


async def process_research(store, prospect, *, start_fn=None, poll_fn=None, threshold=None):
    """Start or resume exactly one research task, safely preserving pending state.

    Callers must check suppression BEFORE entering. Never issues outbound messages.
    """
    start_fn = start_fn or research_lead
    poll_fn = poll_fn or resume_research
    identity = lead_identity(prospect)
    existing = store.get_research(identity) if store else None
    if existing and classify_research(existing) == 'completed':
        return {'research_status':'completed','already_completed':True,'outreach_sent':False}
    if existing:
        if not existing.get('alias') or 'after_fingerprint' not in existing:
            return {'research_status':'manual_review', 'outreach_sent':False,
                    'notice':'Legacy pending research has no saved history marker. Inspect Minds history; no duplicate prompt sent.'}
        result = await poll_fn(existing)
    else:
        
        if store:
            alias = research_alias(prospect)
            claimed = store.claim_research(identity, alias)
            if not claimed:
                return {

                        "research_status": "manual_review",
                        "outreach_sent": False,
                        "notice": (
                            "Research already reserved by another execution. "
                            "Do not submit another HelloMinds prompt."
                            ),
                        }
        result = await start_fn(prospect)


    status = classify_research(result)
    if store:
        # Must persist the original history marker across polling attempts.
        if existing and 'after_fingerprint' not in result:
            result['after_fingerprint'] = existing['after_fingerprint']
        if status != 'completed':
            store.save_research(identity, result)
    if status != 'completed':
        return {'research_status': 'pending' if status == 'pending' else 'manual_review',
                'alias': result.get('alias'), 'outreach_sent':False,
                'notice':'Research remains unqualified; poll the same conversation later.'}
    return finalize_report(store, prospect, result, threshold=threshold)


def finalize_report(store, prospect, result, *, threshold=None):
    """Validate and persist a completed report; keep unsupported claims out of drafts."""
    if classify_research(result) != 'completed':
        raise ValueError('Only completed structured reports can be finalised')
    identity = lead_identity(prospect)
    if store and store.is_suppressed(identity):
        raise ValueError('Suppressed prospect cannot be processed')
    if store:
        store.save_research(identity, result)
    item = _item(prospect)
    score_item(item)
    assessment = apply_research_assessment(item, result)
    if store:
        remote = store.get_prospect(identity) or {}
        store.put('prospects', identity, {**{k:v for k,v in remote.items() if k!='id'},
            **item.model_dump(exclude={'raw'}), 'dedupe_key': identity,
            'research_assessment_status':assessment['status']})
    qualified = bool(item.qualified and item.score >= (threshold or get_settings().minimum_lead_score))
    drafted = False
    if qualified and assessment['evidence_accepted'] > 0 and store and not store.get('outreach_drafts',identity):
        subject, message = create_draft(item, assessment=assessment)
        store.save_draft(identity, subject, message)
        drafted = True
    return {'research_status':'completed', 'research_completed':True,
            'assessment':assessment, 'score':item.score, 'qualified':qualified,
            'draft_prepared':drafted, 'outreach_sent':False}




async def recover_completed_from_history(store, prospect, record):
    """Recover a completed report from an existing Minds conversation.

    Read-only HelloMinds history request; no new prompt is sent.
    Only validated completed reports are persisted.
    """
    alias = record.get("alias")

    if not alias:
        return None

    settings = get_settings()

    if not settings.minds_builder_api_key:
        raise RuntimeError("HelloMinds API key is missing")

    bridge = (
        Path(__file__).resolve().parent.parent
        / "bridge"
        / "export_research_history.mjs"
    )

    env = os.environ.copy()
    env["MINDS_BUILDER_API_KEY"] = (
        settings.minds_builder_api_key
    )

    proc = await asyncio.create_subprocess_exec(
        "node",
        str(bridge),
        alias,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=60,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError("HelloMinds history lookup timed out")

    if proc.returncode != 0:
        raise RuntimeError("HelloMinds history lookup failed")

    history = json.loads(stdout)

    if history.get("alias") != alias:
        raise RuntimeError("Unexpected HelloMinds conversation alias")

    for message in history.get("messages", []):
        fingerprint = message.get("fingerprint")
        reply = message.get("reply", "")

        if not isinstance(fingerprint, str) or not fingerprint:
            continue

        result = {
            "alias": alias,
            "mind_id": record.get("mind_id", ""),
            "after_fingerprint": fingerprint,
            "reply": reply,
            "pending": False,
        }

        if classify_research(result) != "completed":
            continue

        identity = lead_identity(prospect)

        # Recheck before modifying persistent state.
        if store.is_suppressed(identity):
            return None

        latest = store.get_research(identity)

        if latest and classify_research(latest) == "completed":
            return {
                "research_status": "completed",
                "already_completed": True,
                "outreach_sent": False,
            }

        return finalize_report(store, prospect, result)

    return None




async def reconcile_pending(store, *, limit=2, poll_fn=None):
    """Recover or poll existing HelloMinds jobs without new prompts."""

    if not store:
        raise ValueError(
            "SurrealDB persistence is required "
            "to reconcile pending research"
        )

    output = []

    for record in store.list_records("research_briefs", 500):
        if len(output) >= limit:
            break

        if not pending_record(record):
            continue

        identity = record.get("prospect_identity")

        if not identity or store.is_suppressed(identity):
            continue

        prospect = store.get_prospect(identity)

        if not prospect:
            continue

        try:
            if (
                record.get("alias")
                and not record.get("after_fingerprint")
            ):
                # Interrupted start or legacy record.
                # Inspect the original conversation.
                # Never send the research prompt again.
                result = await recover_completed_from_history(
                    store,
                    prospect,
                    record,
                )

                if result is None:
                    # No valid completed report yet.
                    # Leave the record untouched.
                    continue

            elif record.get("alias"):
                # Normal recovery with a saved history marker.
                result = await process_research(
                    store,
                    prospect,
                    poll_fn=poll_fn,
                )

            else:
                # No conversation alias: manual investigation.
                continue

            output.append({
                "identity": identity,
                **result,
            })

        except Exception as exc:
            output.append({
                "identity": identity,
                "research_status": "error",
                "error_type": type(exc).__name__,
                "outreach_sent": False,
            })

    return output

