"""Dedicated Amplify approved-email dispatcher (no discovery or research).

Required SurrealDB record, keyed by prospect identity in outreach_approvals:
    status='approved', recipient_email, draft_sha256, approved_by, approved_at
The draft_sha256 is sha256(subject + '\\n' + message), encoded as UTF-8.

This is an additional human-approval gate on top of app.outreach.dispatch_one,
which enforces consent, qualification, suppression and atomic send claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime

from app.config import get_settings
from app.outreach import configure_status, dispatch_one, email_address
from app.surreal_store import enabled_store

SITE_URL = "https://amplify-social.replit.app/"


def draft_digest(draft):
    return hashlib.sha256(
        (str(draft.get("subject", "")) + "\n" + str(draft.get("message", "")))
        .encode("utf-8")
    ).hexdigest()


def approval_is_valid(store, identity, draft):
    approval = store.get("outreach_approvals", identity)
    route = store.get("contact_routes", identity)
    if not isinstance(approval, dict) or not isinstance(route, dict):
        return False
    if approval.get("status") != "approved" or not approval.get("approved_by"):
        return False
    if approval.get("draft_sha256") != draft_digest(draft):
        return False
    if SITE_URL not in str(draft.get("message", "")):
        return False
    try:
        if email_address(approval.get("recipient_email", "")) != email_address(route.get("email", "")):
            return False
        timestamp = datetime.fromisoformat(str(approval.get("approved_at", "")).replace("Z", "+00:00"))
        if not timestamp.tzinfo:
            return False
    except (ValueError, TypeError):
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.limit <= 20:
        parser.error("--limit must be 1..20")

    dry_run = os.getenv("DRY_RUN", "true").lower() != "false"
    settings = get_settings()
    if not dry_run and not settings.outreach_autosend_enabled:
        raise SystemExit("OUTREACH_AUTOSEND_ENABLED is false: refusing live sending")

    store = enabled_store()
    if not store:
        raise SystemExit("SurrealDB must be enabled for outreach")
    store.ping()
    permission = configure_status(settings)
    if not dry_run and not permission["ready"]:
        raise SystemExit("Sending configuration gates failed: " + ", ".join(
            k for k, ok in permission["checks"].items() if not ok))

    outcomes = []
    for draft in store.list_records("outreach_drafts", 500):
        if len(outcomes) >= args.limit:
            break
        if draft.get("status") != "draft" or draft.get("sent") is not False:
            continue
        identity = draft.get("prospect_identity")
        if not identity or not approval_is_valid(store, identity, draft):
            continue
        if store.is_suppressed(identity):
            continue
        if dry_run:
            result = {"status": "approved_preview_only"}
        else:
            result = dispatch_one(store, identity, settings=settings)
        # Do not log email addresses or draft text in GitHub Actions output.
        outcomes.append({"status": result.get("status", "unknown")})
    print(json.dumps({"dry_run": dry_run, "candidates_processed": len(outcomes),
                      "outcomes": outcomes}, indent=2))


if __name__ == "__main__":
    main()
