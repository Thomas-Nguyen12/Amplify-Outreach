
from app.config import get_settings
from app.surreal_store import PersistentStore
from app.gmail_service import gmail_client
from app.gmail_replies import decode_body, visible_reply, classify_reply

s = get_settings()

if s.surreal_database != "integration_test":
    raise SystemExit("Refusing to run outside integration_test")

store = PersistentStore(settings=s)

events = store.list_records("outreach_reply_events", 20)
events = sorted(events, key=lambda x: x.get("received_at", ""))

if not events:
    raise SystemExit("No reply events found")

event = events[-1]
gmail_id = event.get("gmail_message_id")

if not gmail_id:
    raise SystemExit("Reply event has no Gmail message ID")

gmail = gmail_client(s, require_read=True)

message = gmail.users().messages().get(
    userId="me",
    id=gmail_id,
    format="full",
).execute()

body = decode_body(message.get("payload", {}))
cleaned = visible_reply(body)

print("Recorded classification:", event.get("type"))
print("Gmail message found:", bool(message))
print("Decoded body length:", len(body))
print("Visible reply length:", len(cleaned))
print("Visible reply is exactly STOP:", cleaned.strip().upper() == "STOP")
print("Current classification:", classify_reply(body))
print("Visible reply preview:", repr(cleaned[:120]))

