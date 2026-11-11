"""Gmail API tests: mocked service; absolutely no real email or credentials."""
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
import base64
from email import message_from_bytes
from types import SimpleNamespace
import pytest
from app.gmail_service import send_gmail, token_status, SEND_SCOPE, READ_SCOPE
from app.gmail_replies import classify_reply, poll_replies
from tests.test_autonomous_outreach import FakeStore


@dataclass
class GmailSettings:
    outreach_from_email:str='project@gmail.com'
    outreach_reply_to:str='project@gmail.com'
    outreach_sender_name:str='Social Trend Team'
    gmail_oauth_client_file:str='not_found_client.json'
    gmail_token_file:str='not_found_token.json'
    gmail_reply_poll_enabled:bool=True
    surreal_enabled:bool=True
    agent_api_key:str='test-secret'

class MockSend:
    def __init__(self):
        self.payload = None
        self.metadata_requested = False

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, **kwargs):
        self.payload = kwargs
        return self

    def get(self, **kwargs):
        self.metadata_requested = True
        assert kwargs["id"] == "gmail-test123"
        assert kwargs["format"] == "metadata"
        assert "Message-ID" in kwargs["metadataHeaders"]
        return self

    def execute(self):
        if self.metadata_requested:
            return {
                "payload": {
                    "headers": [
                        {
                            "name": "Message-ID",
                            "value": "<actual-gmail-message@gmail.com>",
                        }
                    ]
                }
            }

        return {
            "id": "gmail-test123",
            "threadId": "thread-test123",
        }

def test_send_uses_gmail_api_and_preserves_reply_to(monkeypatch):
    svc = MockSend()

    monkeypatch.setattr(
        "app.gmail_service.gmail_client",
        lambda s, require_read=False: svc,
    )

    result = send_gmail(
        to="customer@example.org",
        subject="Test",
        message="AI assistance",
        idempotency_key="persistent-claim",
        settings=GmailSettings(),
    )

    assert result["provider_id"] == "gmail-test123"
    assert result["thread_id"] == "thread-test123"

    # Must use the Message-ID retrieved from Gmail.
    assert result["rfc_message_id"] == (
        "<actual-gmail-message@gmail.com>"
    )
    assert result["message_id_verified"] is True
    assert svc.metadata_requested is True

    msg = message_from_bytes(
        base64.urlsafe_b64decode(svc.payload["body"]["raw"])
    )

    assert msg["To"] == "customer@example.org"
    assert msg["Reply-To"] == "project@gmail.com"
    assert msg.get_payload(decode=True).decode().strip() == (
        "AI assistance"
    )

def test_gmail_token_status_fails_closed_on_missing_files():
    assert token_status(GmailSettings())=={
        'oauth_client_file':False,'token_file':False,'token_scopes':False}


@pytest.mark.parametrize('reply,expected',[
    ('STOP','opt_out'),('Please unsubscribe','opt_out'),
    ('Please remove me from your list.','opt_out'),
    ('What is the subscription price?','needs_review'),
    ('Can we arrange a call?','needs_review'),
    ('Thanks!\n\n> For no further contact, reply STOP','needs_review'),
])
def test_reply_classification(reply,expected):
    assert classify_reply(reply)==expected


class MockRead:
    def __init__(self, messages):self.messages_map={m['id']:m for m in messages};self.current=None
    def users(self):return self
    def messages(self):return self
    def list(self,**kw):return SimpleNamespace(execute=lambda:{'messages':[{'id':m} for m in self.messages_map]})
    def get(self,**kw):self.current=kw['id'];return self
    def execute(self):return self.messages_map[self.current]


def inbound(id, address, msgid, body, when):
    return {'id':id,'internalDate':str(int(when.timestamp()*1000)),
            'payload':{'mimeType':'text/plain','headers':[
                {'name':'From','value':address},
                {'name':'In-Reply-To','value':msgid},
                {'name':'Subject','value':'Re: Hello'}],
                'body':{'data':base64.urlsafe_b64encode(body.encode()).decode()}}}


def test_reply_poll_correlates_and_suppresses_only_matched_optout():
    s=GmailSettings();store=FakeStore();sent=datetime.now(timezone.utc)-timedelta(hours=1)
    store.put('outreach_send_attempts','mailto:client@example.org',{
        'email':'client@example.org','status':'accepted_by_provider',
        'updated_at':sent.isoformat(),'rfc_message_id':'<original@gmail.com>'})
    messages=[
        inbound('a','Client <client@example.org>','<original@gmail.com>','STOP',datetime.now(timezone.utc)),
        inbound('b','stranger@example.org','<original@gmail.com>','STOP',datetime.now(timezone.utc)),
        inbound('c','client@example.org','<unrelated@gmail.com>','STOP',datetime.now(timezone.utc)),
        inbound('d','client@example.org','<original@gmail.com>','STOP',sent-timedelta(minutes=10))]
    result=poll_replies(store,settings=s,gmail=MockRead(messages))
    assert result['opted_out']==1 and result['matched']==1
    assert store.is_suppressed('mailto:client@example.org')
    assert not store.is_suppressed('mailto:stranger@example.org')
    assert poll_replies(store,settings=s,gmail=MockRead(messages))['already_recorded']==1


def test_reply_poll_disabled_even_with_mock_inbox():
    s=GmailSettings(gmail_reply_poll_enabled=False)
    with pytest.raises(RuntimeError,match='false'):
        poll_replies(FakeStore(),settings=s,gmail=MockRead([]))
