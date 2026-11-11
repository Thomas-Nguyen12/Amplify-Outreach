
"""Recover completed HelloMinds reports from existing conversations.

Default mode: preview only, no database writes.
Apply mode: validate and persist completed reports.

Never sends new research prompts or customer emails.
"""

import argparse
import json
import os
import subprocess
from pathlib import Path

from app.config import get_settings
from app.research_assessment import classify_research
from app.research_jobs import finalize_report
from app.surreal_store import enabled_store


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bridge" / "export_research_history.mjs"


def fetch_history(alias, api_key):
    env = os.environ.copy()
    env["MINDS_BUILDER_API_KEY"] = api_key

    result = subprocess.run(
        ["node", str(BRIDGE), alias],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )

    return json.loads(result.stdout)["messages"]


def completed_result(record, messages):
    """Find a complete report and preserve its real fingerprint."""

    # The SDK returns newest history messages first.
    # Select the first response passing full Python validation.
    for message in messages:
        fingerprint = message.get("fingerprint")
        reply = message.get("reply", "")

        if not fingerprint or not reply:
            continue

        candidate = {
            "alias": record["alias"],
            "mind_id": record.get("mind_id", ""),
            "after_fingerprint": fingerprint,
            "reply": reply,
            "pending": False,
        }

        if classify_research(candidate) == "completed":
            return candidate

    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Save validated completed research to SurrealDB",
    )
    args = parser.parse_args()

    settings = get_settings()

    if not settings.minds_builder_api_key:
        raise RuntimeError("HelloMinds API key is not configured")

    if not settings.surreal_enabled:
        raise RuntimeError("SurrealDB must be enabled")

    store = enabled_store()

    if store is None:
        raise RuntimeError("SurrealDB store unavailable")

    store.ping()

    records = store.list_records("research_briefs", 500)

    recovered = 0
    reviewed = 0

    print("Mode:", "APPLY" if args.apply else "PREVIEW")
    print("Research records:", len(records))

    for record in records:
        alias = record.get("alias")
        identity = record.get("prospect_identity")

        if not alias or not identity:
            continue

        if record.get("status") == "completed":
            print(f"{alias}: already completed — skipping")
            continue

        try:
            prospect = store.get_prospect(identity)

            if not prospect:
                print(f"{alias}: missing prospect — skipping")
                continue

            if store.is_suppressed(identity):
                print(f"{alias}: suppressed — skipping")
                continue

            messages = fetch_history(
                alias,
                settings.minds_builder_api_key,
            )

            reviewed += 1

            result = completed_result(record, messages)

            if result is None:
                print(
                    f"{alias}: no valid completed report "
                    f"({len(messages)} Mind messages)"
                )
                continue

            print(f"{alias}: valid completed report found")

            if args.apply:
                outcome = finalize_report(
                    store,
                    prospect,
                    result,
                )

                recovered += 1

                print(
                    "  Saved:",
                    outcome["research_status"],
                    "| Score:",
                    outcome["score"],
                    "| Qualified:",
                    outcome["qualified"],
                    "| Accepted evidence:",
                    outcome["assessment"]["evidence_accepted"],
                    "| Draft:",
                    outcome["draft_prepared"],
                )

        except Exception as exc:
            # Do not print research text, credentials or full
            # HTTP error payloads to production logs.
            print(
                f"{alias}: recovery failed "
                f"({type(exc).__name__})"
            )

    print()
    print("Conversations inspected:", reviewed)
    print("Completed reports saved:", recovered)


if __name__ == "__main__":
    main()
