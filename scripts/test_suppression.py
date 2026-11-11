
from app.config import get_settings
from app.surreal_store import PersistentStore
from app.outreach import suppress_email

s = get_settings()

if s.surreal_database != "integration_test":
    raise SystemExit("Refusing to modify production database")

store = PersistentStore(settings=s)

email = input("Enter your personal Gmail address: ").strip().lower()

if not email or "@" not in email:
    raise SystemExit("Invalid email address")

if email == s.outreach_from_email.strip().lower():
    raise SystemExit("Cannot suppress the sending account")

confirm = input(
    f"Record test opt-out for {email}? Type YES: "
).strip()

if confirm != "YES":
    raise SystemExit("Cancelled")

result = suppress_email(
    store,
    email,
    reason="STOP received in Gmail integration test",
)

print("Suppression recorded:", result)
print(
    "Suppression verified:",
    store.is_suppressed("mailto:" + email),
)

