
from datetime import datetime, timezone

from app.config import get_settings
from app.gmail_service import send_gmail
from app.surreal_store import PersistentStore
from uuid import uuid4
s = get_settings()

if s.surreal_database != "integration_test":
    raise SystemExit("Refusing to run outside integration_test")

recipient = input("Enter your personal Gmail address: ").strip().lower()

if not recipient or "@" not in recipient:
    raise SystemExit("Invalid recipient")

if recipient == s.outreach_from_email.strip().lower():
    raise SystemExit("Recipient must differ from sender")

print("Test database:", s.surreal_database)
print("Recipient:", recipient)

if input("Send ONE test email? Type YES: ").strip() != "YES":
    raise SystemExit("Cancelled")

result = send_gmail(
    to=recipient,
    subject="Amplify integrated reply test",
    message="This is a test. Please reply to this email.",
    idempotency_key="manual-integration-test",
    settings=s,
)
print("Gmail message ID verified:", result["message_id_verified"])
print("Actual RFC Message-ID:", result["rfc_message_id"])
print("Gmail accepted the message.")

store = PersistentStore(settings=s)

store.put(
    "outreach_send_attempts",
    "gmail-test-" + uuid4().hex,
    {
        "email": recipient,
        "status": "accepted_by_provider",
        "provider": "gmail",
        "provider_id": result["provider_id"],
        "sent_at": result["sent_at"],
        "rfc_message_id": result["rfc_message_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    },
)

print("Test outreach attempt recorded.")

