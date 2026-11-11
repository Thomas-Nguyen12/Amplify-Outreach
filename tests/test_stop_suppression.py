
"""End-to-end STOP-to-suppression test using a fake Gmail inbox.

No live Gmail requests, emails, or SurrealDB modifications.
"""

from datetime import datetime, timedelta, timezone

from app.gmail_replies import poll_replies
from tests.test_autonomous_outreach import FakeStore
from tests.test_gmail_integration import GmailSettings, MockRead, inbound


def test_stop_reply_automatically_suppresses_sender():
    settings = GmailSettings()
    store = FakeStore()

    recipient = "customer@example.org"
    identity = "youtube:test-business"
    original_message_id = "<original-test-message@gmail.com>"

    sent_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    received_at = sent_at + timedelta(minutes=2)

    # Simulate an email previously sent by the integrated agent.
    store.put(
        "outreach_send_attempts",
        "gmail-test-001",
        {
            "email": recipient,
            "provider": "gmail",
            "status": "accepted_by_provider",
            "rfc_message_id": original_message_id,
            "sent_at": sent_at.isoformat(),
            "created_at": sent_at.isoformat(),
            "updated_at": sent_at.isoformat(),
        },
    )

    # Simulate a contact linked to the same prospect.
    store.put(
        "contact_routes",
        identity,
        {
            "email": recipient,
            "prospect_identity": identity,
            "status": "active",
        },
    )

    # The customer has NOT previously opted out.
    assert not store.is_suppressed("mailto:" + recipient)
    assert not store.is_suppressed(identity)

    # Simulate a real Gmail reply, including Gmail's wrapped quote.
    reply = inbound(
        id="gmail-stop-test-001",
        address=f"Customer <{recipient}>",
        msgid=original_message_id,
        body=(
            "STOP\n\n"
            "On Wed, 11 Nov 2026 at 14:12, Amplify <\n"
            "amplify.outreach.team@gmail.com> wrote:\n"
            "> This is a test email."
        ),
        when=received_at,
    )

    gmail = MockRead([reply])

    # FIRST POLL: the agent must detect STOP and suppress the sender.
    first = poll_replies(
        store,
        settings=settings,
        gmail=gmail,
        limit=50,
    )

    assert first["matched"] == 1
    assert first["opted_out"] == 1
    assert first["needs_review"] == 0

    # Suppression must be created automatically.
    assert store.is_suppressed("mailto:" + recipient)

    # The linked prospect identity must also be suppressed.
    assert store.is_suppressed(identity)

    # The reply event must be recorded as an opt-out.
    event = store.get(
        "outreach_reply_events",
        "gmail:gmail-stop-test-001",
    )

    assert event is not None
    assert event["type"] == "opt_out"
    assert event["email"] == recipient

    # SECOND POLL: the same reply must not be processed twice.
    second = poll_replies(
        store,
        settings=settings,
        gmail=gmail,
        limit=50,
    )

    assert second["matched"] == 0
    assert second["opted_out"] == 0
    assert second["already_recorded"] == 1

    print("STOP-to-suppression test passed!")

