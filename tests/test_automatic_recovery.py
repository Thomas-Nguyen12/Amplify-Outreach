
"""Tests for automatic HelloMinds history recovery.

All services are mocked. No network calls, real database writes,
new research prompts, or customer messages are made.
"""

import asyncio
import json
from types import SimpleNamespace
from app.research_assessment import classify_research
from app import research_jobs
from app.research_jobs import reconcile_pending
from app.surreal_store import lead_identity

from tests.test_research_recovery import (
    FakePersistentStore,
    prospect,
    complete_report,
)


class FakeProcess:
    """Simulate the read-only Node.js history exporter."""

    returncode = 0

    def __init__(self, payload):
        self.payload = payload

    async def communicate(self):
        return json.dumps(self.payload).encode(), b""


def prepare_reserved_job():
    """Create a research reservation without a fingerprint."""

    store = FakePersistentStore()
    lead = prospect()
    identity = lead_identity(lead)

    store.save_prospect(identity, lead.model_dump())

    alias = "research_automatic_recovery_test"

    assert store.claim_research(identity, alias) is True

    record = store.get_research(identity)

    assert record["status"] == "reserved"
    assert "after_fingerprint" not in record

    return store, lead, identity, alias


def mock_history_export(monkeypatch, alias, reply):
    """Intercept Node execution and return fake conversation history."""

    calls = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        calls.append(args)

        # Only the read-only history exporter is permitted.
        assert args[0] == "node"
        assert str(args[1]).endswith(
            "export_research_history.mjs"
        )
        assert args[2] == alias

        return FakeProcess({
            "alias": alias,
            "messages": [
                {
                    "fingerprint": "real-test-fingerprint",
                    "reply": reply,
                }
            ],
        })

    monkeypatch.setattr(
        research_jobs.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    monkeypatch.setattr(
        research_jobs,
        "get_settings",
        lambda: SimpleNamespace(
            minds_builder_api_key="fake-test-key",
            minimum_lead_score=70,
        ),
    )

    return calls


def test_automatic_recovery_finalizes_completed_report(monkeypatch):
    """Recover completed research without submitting another prompt."""

    store, lead, identity, alias = prepare_reserved_job()

    report = complete_report()

    # Simulate the exact HTML wrapper returned by HelloMinds.
    wrapped_reply = "<pre>" + json.dumps(report) + "</pre>"

    calls = mock_history_export(
        monkeypatch,
        alias,
        wrapped_reply,
    )

    async def must_not_start_research(*args, **kwargs):
        raise AssertionError(
            "Automatic recovery must not submit another prompt"
        )

    monkeypatch.setattr(
        research_jobs,
        "research_lead",
        must_not_start_research,
    )

    # Simulate the next hourly Cloud Run execution.
    results = asyncio.run(
        reconcile_pending(store, limit=2)
    )

    assert len(results) == 1

    outcome = results[0]

    assert outcome["research_status"] == "completed"
    assert outcome["research_completed"] is True
    assert outcome["outreach_sent"] is False
    assert outcome["qualified"] is False

    # The completed report must be durable.
    saved = store.get_research(identity)

    assert classify_research(saved) == "completed"
    assert saved["alias"] == alias
    assert saved["after_fingerprint"] == (
        "real-test-fingerprint"
    )

    assert saved["reply"] == wrapped_reply

    # Unsupported claims cannot create an outreach draft.
    assert store.get("outreach_drafts", identity) is None

    # Exactly one history lookup, zero new research prompts.
    assert len(calls) == 1

    # Reconciliation is idempotent for completed research.
    again = asyncio.run(
        reconcile_pending(store, limit=2)
    )

    assert again == []
    assert len(calls) == 1


def test_incomplete_history_does_not_finalize(monkeypatch):
    """An acknowledgement must not be treated as completed research."""

    store, lead, identity, alias = prepare_reserved_job()

    calls = mock_history_export(
        monkeypatch,
        alias,
        "On it - I am starting research now.",
    )

    async def must_not_start_research(*args, **kwargs):
        raise AssertionError(
            "An incomplete job must not be restarted"
        )

    monkeypatch.setattr(
        research_jobs,
        "research_lead",
        must_not_start_research,
    )

    results = asyncio.run(
        reconcile_pending(store, limit=2)
    )

    # No valid completed report was found.
    assert results == []

    # The original reservation remains intact.
    saved = store.get_research(identity)

    assert saved["status"] == "reserved"
    assert saved["alias"] == alias
    assert "after_fingerprint" not in saved

    assert store.get("outreach_drafts", identity) is None

    # History was inspected, but no prompt was submitted.
    assert len(calls) == 1

