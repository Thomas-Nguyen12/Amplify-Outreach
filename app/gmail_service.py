"""Gmail API adapter. Tokens never leave the operator-controlled runtime.
from datetime import datetime, timezone
OAuth is deliberately interactive *only* in scripts/authorize_gmail.py.
The server refuses to launch browsers or auto-request new scopes.
"""
from __future__ import annotations
from datetime import datetime, timezone
import base64
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

SEND_SCOPE = 'https://www.googleapis.com/auth/gmail.send'
READ_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'


def safe_path(value: str) -> Path:
    if not value:
        raise ValueError('Missing Gmail credential path')
    return Path(value).expanduser().resolve()


def token_status(settings, *, require_read=False) -> dict:
    token = safe_path(settings.gmail_token_file)
    client = safe_path(settings.gmail_oauth_client_file)
    exists = token.is_file()
    scopes_ok = False
    if exists:
        try:
            from google.oauth2.credentials import Credentials
            credentials = Credentials.from_authorized_user_file(str(token))
            required = [SEND_SCOPE, READ_SCOPE] if require_read else [SEND_SCOPE]
            scopes_ok = credentials.has_scopes(required)
        except (ValueError, OSError, KeyError, ImportError):
            pass
    return {'oauth_client_file': client.is_file(), 'token_file': exists,
            'token_scopes': scopes_ok}


def gmail_client(settings, *, require_read=False):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    token = safe_path(settings.gmail_token_file)
    required = [SEND_SCOPE, READ_SCOPE] if require_read else [SEND_SCOPE]
    if not token.is_file():
        raise RuntimeError('Gmail token missing. Run python -m scripts.authorize_gmail')
    creds = Credentials.from_authorized_user_file(str(token))
    if not creds.has_scopes(required):
        raise RuntimeError('Gmail token lacks required scopes. Re-authorise explicitly with scripts.authorize_gmail')
    if not creds.valid:
        if not creds.refresh_token:
            raise RuntimeError('Gmail OAuth token expired without refresh token')
        creds.refresh(Request())
        token.write_text(creds.to_json(), encoding='utf-8')
        token.chmod(0o600)
    return build('gmail', 'v1', credentials=creds, cache_discovery=False)



def send_gmail(*, to, subject, message, idempotency_key, settings=None):
    """Send once, then retrieve Gmail's actual RFC Message-ID.

    Never resend automatically if post-send metadata lookup fails.
    """
    from .config import get_settings
    from .outreach import email_address

    s = settings or get_settings()

    sender = email_address(s.outreach_from_email)
    recipient = email_address(to)

    # Check both permissions BEFORE sending.
    gmail = gmail_client(s, require_read=True)

    mail = EmailMessage()
    mail["From"] = formataddr((s.outreach_sender_name, sender))
    mail["To"] = recipient
    mail["Reply-To"] = email_address(s.outreach_reply_to)
    mail["Subject"] = subject

    # Gmail may replace this header during sending.
    mail["Message-ID"] = make_msgid(
        domain=sender.split("@", 1)[1]
    )

    mail.set_content(message)

    raw = base64.urlsafe_b64encode(
        mail.as_bytes()
    ).decode("ascii")

    # Send the email exactly once.
    result = gmail.users().messages().send(
        userId="me",
        body={"raw": raw},
    ).execute()

    provider_id = result.get("id")

    if not provider_id:
        raise RuntimeError(
            "Gmail did not confirm message acceptance"
        )

    sent_at = datetime.now(timezone.utc).isoformat()

    # Retrieve the actual Message-ID Gmail stored.
    actual_message_id = None
    metadata_verified = False

    try:
        sent_message = gmail.users().messages().get(
            userId="me",
            id=provider_id,
            format="metadata",
            metadataHeaders=["Message-ID"],
        ).execute()

        headers = sent_message.get(
            "payload", {}
        ).get("headers", [])

        actual_message_id = next(
            (
                header.get("value", "").strip()
                for header in headers
                if header.get("name", "").lower()
                == "message-id"
            ),
            None,
        )

        metadata_verified = bool(actual_message_id)

    except Exception:
        # Gmail already accepted the email.
        # Do not resend because metadata retrieval failed.
        pass

    return {
        "provider_id": provider_id,
        "status": "accepted_by_provider",
        "rfc_message_id": actual_message_id,
        "message_id_verified": metadata_verified,
        "thread_id": result.get("threadId"),
        "sent_at": sent_at,
    }

