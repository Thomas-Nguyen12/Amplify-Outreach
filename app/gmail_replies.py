"""Read-only, correlation-gated Gmail inbox reconciliation.

Only messages from the exact email address of a sent contact are considered.
Ambiguous replies go to human review; unambiguous opt-outs are suppressed.
No automatic follow-up messages are generated.
"""
from __future__ import annotations
import base64
from datetime import datetime, timezone
from email.utils import parseaddr
from .gmail_service import gmail_client
from .outreach import now, suppress_email


def decode_body(payload):
    if not payload:
        return ''
    if payload.get('mimeType') == 'text/plain' and payload.get('body', {}).get('data'):
        return base64.urlsafe_b64decode(payload['body']['data'] + '===').decode('utf-8', errors='replace')
    for part in payload.get('parts', []):
        text = decode_body(part)
        if text:
            return text
    return ''


def visible_reply(text):
    lines=[]
    for line in text.splitlines():
        trimmed=line.strip()
        if trimmed.startswith('>') or trimmed.lower().startswith('on ') and trimmed.lower().endswith('wrote:'):
            break
        if trimmed in ('--', '-- '):
            break
        lines.append(line)
        if len(lines)>=25: break
    return '\n'.join(lines).strip()[:2000]


def classify_reply(body):
    """Conservative: only clear unsubscribe language is acted on automatically."""
    import re
    first_line = next(
    (line.strip().lower() for line in body.splitlines() if line.strip()),
    "")

    if first_line in {"stop", "unsubscribe", "please unsubscribe"}:
        return "opt_out"
    top=visible_reply(body).strip().lower()
    if re.fullmatch(r'(stop|unsubscribe|remove me|opt out|opt-out|do not contact me|don.t contact me|please unsubscribe|please remove me)[.!\s]*', top):
        return 'opt_out'
    if any(phrase in top for phrase in ('please unsubscribe', 'remove me from your list', 'do not contact me again', 'stop emailing me', "don't email me again")):
        return 'opt_out'
    return 'needs_review'


def poll_replies(store, *, settings=None, gmail=None, limit=50):
    from .config import get_settings
    s=settings or get_settings()
    if not s.surreal_enabled or not s.agent_api_key:
        raise RuntimeError('Persistent store and authenticated API are required')
    if not s.gmail_reply_poll_enabled:
        raise RuntimeError('GMAIL_REPLY_POLL_ENABLED is false')
    client=gmail or gmail_client(s, require_read=True)
    # Recently received INBOX messages only; no mutation/mark-read needed.
    response=client.users().messages().list(
        userId='me', labelIds=['INBOX'], maxResults=min(max(1,limit),100)).execute()
    # Correlate to an actual accepted send, not merely an imported lead/contact.
    attempts={a.get('email','').lower():a for a in store.list_records('outreach_send_attempts',500)
              if a.get('status') == 'accepted_by_provider' and a.get('email')}
    result={'checked':0,'matched':0,'opted_out':0,'needs_review':0,'already_recorded':0}
    for summary in response.get('messages', []):
        msgid=summary['id']
        event_id='gmail:'+msgid
        if store.get('outreach_reply_events', event_id):
            result['already_recorded']+=1
            continue
        item=client.users().messages().get(userId='me',id=msgid,format='full').execute()
        result['checked']+=1
        headers={h['name'].lower():h['value'] for h in item.get('payload',{}).get('headers',[])}
        sender=parseaddr(headers.get('from',''))[1].lower()
        attempt=attempts.get(sender)
        if not attempt or sender == s.outreach_from_email.lower():
            continue
        # Only post-send mail is a plausible response. Gmail internalDate is milliseconds.
        when=int(item.get('internalDate','0') or 0)
        sent_time = (
                attempt.get("sent_at")
                or attempt.get("created_at")
                or attempt.get("updated_at")
                ) 
        sent = datetime.fromisoformat(sent_time.replace('Z', '+00:00')) if sent_time else None

        if not sent or when < int(sent.timestamp()*1000):
            continue
        # Thread correlation if supported; otherwise require References / In-Reply-To.
        references=headers.get('references','')+' '+headers.get('in-reply-to','')
        original=attempt.get('rfc_message_id','')
        if not original or original not in references:
            continue
        result['matched']+=1
        body=decode_body(item.get('payload',{}))
        kind=classify_reply(body)
        if kind=='opt_out':
            # Suppress first: if persistence fails, do not record as processed.
            suppress_email(store,sender,'Recipient opted out by Gmail reply')
            result['opted_out']+=1
        else:
            result['needs_review']+=1
        store.put('outreach_reply_events',event_id,{
            'email':sender,'type':kind,'provider':'gmail','gmail_message_id':msgid,
            'received_at':datetime.fromtimestamp(when/1000,timezone.utc).isoformat(),
            'recorded_at':now(), 'subject':headers.get('subject','')[:250],
            'notice':'Review the dedicated Gmail inbox; no reply text stored'})
    return result
