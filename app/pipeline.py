
"""Live prospect discovery and research-first qualification.

HelloMinds reviews plausible segment-matched leads and selected
Instagram business candidates before outreach drafts are created.

Business-candidate status permits verification research only.
It does not establish buying intent, qualify a lead, or authorise
customer outreach.
"""

from .discovery import discover
from .scoring import score_item
from .compliance import check_prospect
from .drafts import create_draft
from .database import (
    save_prospect,
    save_draft,
    audit,
    rows,
    save_research,
    update_prospect_scoring,
)
from .config import get_settings
from .hellominds import research_lead
from .research_jobs import process_research
from .research_assessment import (
    apply_research_assessment,
    classify_research,
)
from .surreal_store import enabled_store, lead_identity
from .targeting import (
    DEFAULT_QUERIES,
    is_business_research_candidate,
)
from .models import Prospect


class PendingResearch(Exception):
    """The Mind acknowledged a task but produced no final report."""


ALLOWED = {
    "web",
    "instagram",
    "tiktok",
    "reddit",
    "youtube_direct",
}


def _stored_prospect(record):
    """Convert an older SurrealDB record to a scoring-compatible object."""

    fields = Prospect.model_fields.keys()

    import json

    data = {
        key: record[key]
        for key in fields
        if key in record
    }

    if isinstance(data.get("score_reasons"), str):
        data["score_reasons"] = json.loads(
            data["score_reasons"]
        )

    return Prospect(**data)


async def run_pipeline(queries, platforms, limit, threshold):
    queries = queries or DEFAULT_QUERIES

    s = get_settings()
    inferred = not bool(platforms)

    if not platforms:
        platforms = (
            ["web"]
            if s.tavily_enabled and s.tavily_api_key
            else []
        ) + [
            platform
            for platform in sorted(
                ALLOWED - {"web", "youtube_direct"}
            )
            if (
                s.treg_enabled
                and s.treg_token
                and s.endpoint_for(platform)
            )
        ]

    if inferred and s.youtube_enabled and s.youtube_api_key:
        platforms.append("youtube_direct")

    if not platforms:
        raise ValueError(
            "No live discovery provider. "
            "Set Tavily, Treg or direct YouTube credentials."
        )

    unknown = set(platforms) - ALLOWED

    if unknown:
        raise ValueError(
            f"Unsupported platforms: {sorted(unknown)}"
        )

    for platform in platforms:
        if platform == "web":
            if not (s.tavily_enabled and s.tavily_api_key):
                raise ValueError(
                    "Live web search requires TAVILY_ENABLED=true "
                    "and TAVILY_API_KEY"
                )

        elif platform == "youtube_direct":
            if not (s.youtube_enabled and s.youtube_api_key):
                raise ValueError(
                    "Direct YouTube search requires "
                    "YOUTUBE_ENABLED=true and YOUTUBE_API_KEY"
                )

        elif not (
            s.treg_enabled
            and s.treg_token
            and s.endpoint_for(platform)
        ):
            raise ValueError(
                f"Live {platform} search requires configured "
                "Treg endpoint and token"
            )

    if s.discovery_mode != "live_search":
        raise ValueError(
            "This pipeline requires live_search mode"
        )

    store = enabled_store()

    if store:
        # Fail closed before making local changes if SurrealDB
        # is unavailable.
        store.ping()

    report = {
        "discovered": 0,
        "saved": 0,
        "qualified": 0,
        "drafts": 0,
        "errors": [],
        "leads": [],
        "researched": 0,
        "already_known": 0,
        "suppressed": 0,
        "persistent_store": bool(store),
        "research_assessed": 0,
        "research_evidence_correlated": 0,
        "research_pending": 0,
    }

    allowed_segments = {
        part.strip()
        for part in s.target_segments.split(",")
    }

    other = [
        platform
        for platform in platforms
        if platform != "youtube_direct"
    ]

    jobs = (
        [(query, other) for query in queries]
        if other
        else []
    )

    if "youtube_direct" in platforms:
        from .youtube import scheduled_youtube_queries

        selected = (
            queries
            if queries != DEFAULT_QUERIES
            else scheduled_youtube_queries(
                s.youtube_max_searches_per_run
            )
        )

        jobs.extend(
            (query, ["youtube_direct"])
            for query in selected[
                :s.youtube_max_searches_per_run
            ]
        )

    report["youtube_queries"] = [
        query
        for query, job_platforms in jobs
        if "youtube_direct" in job_platforms
    ]

    report["youtube_searches_planned"] = len(
        report["youtube_queries"]
    )

    for query, job_platforms in jobs:
        items, errors = await discover(
            query,
            job_platforms,
            limit,
        )

        report["errors"].extend(errors)
        report["discovered"] += len(items)

        for item in items:
            # Preliminary deterministic scoring and segmentation.
            score_item(item)

            identity = lead_identity(item)

            blocked = (
                store.is_suppressed(identity)
                if store
                else None
            )

            compliance = check_prospect(
                item,
                suppressed=blocked,
            )

            # Compliance eligibility remains mandatory before
            # either storage or research.
            if not compliance["eligible_for_research"]:
                if blocked:
                    report["suppressed"] += 1
                continue

            existing = (
                store.get_prospect(identity)
                if store
                else None
            )

            if not existing and store:
                payload = item.model_dump(
                    exclude={"raw"}
                )
                payload["dedupe_key"] = identity

                if not store.claim_prospect(
                    identity,
                    payload,
                ):
                    existing = store.get_prospect(
                        identity
                    )

            if existing:
                report["already_known"] += 1

                # Preserve the existing logic for stored leads.
                # Older records may not contain Instagram metadata
                # needed for business-candidate verification.
                if (
                    s.minds_enabled
                    and existing.get("segment")
                        in allowed_segments
                    and (
                        report["researched"]
                        + report["research_pending"]
                        < s.minds_max_research_per_run
                    )
                ):
                    try:
                        result = await process_research(
                            store,
                            existing,
                            start_fn=research_lead,
                        )

                        state = result["research_status"]

                        if (
                            state == "completed"
                            and not result.get(
                                "already_completed"
                            )
                        ):
                            report["researched"] += 1
                            report["research_assessed"] += 1

                            report[
                                "research_evidence_correlated"
                            ] += result["assessment"][
                                "evidence_accepted"
                            ]

                            report["drafts"] += int(
                                result.get(
                                    "draft_prepared",
                                    False,
                                )
                            )

                        elif state == "pending":
                            report["research_pending"] += 1

                    except Exception as exc:
                        report["errors"].append({
                            "stage": "research_retry",
                            "identity": identity,
                            "error": str(exc),
                        })

                continue

            pid = save_prospect(item)
            report["saved"] += 1

            research_completed = False
            assessment = None

            # NEW:
            # Research either a recognised target segment
            # or a plausible Instagram business candidate.
            #
            # Candidate status only permits further investigation.
            # It does not automatically qualify the lead.
            research_candidate = (
                item.segment in allowed_segments
                or is_business_research_candidate(item)
            )

            if (
                s.minds_enabled
                and research_candidate
                and (
                    report["researched"]
                    + report["research_pending"]
                    < s.minds_max_research_per_run
                )
            ):
                try:
                    # Persistent research jobs allow subsequent
                    # runs to recover pending HelloMinds tasks.
                    result = await process_research(
                        store,
                        item.model_dump(
                            exclude={"raw"}
                        ),
                        start_fn=research_lead,
                    )

                    if (
                        result["research_status"]
                        == "completed"
                        and not result.get(
                            "already_completed"
                        )
                    ):
                        report["researched"] += 1
                        report["research_assessed"] += 1

                        report[
                            "research_evidence_correlated"
                        ] += result["assessment"][
                            "evidence_accepted"
                        ]

                        report["drafts"] += int(
                            result.get(
                                "draft_prepared",
                                False,
                            )
                        )

                        assessment = result["assessment"]
                        research_completed = True

                        if store:
                            item = _stored_prospect(
                                store.get_prospect(
                                    identity
                                )
                            )

                        update_prospect_scoring(
                            pid,
                            item,
                        )

                    elif (
                        result["research_status"]
                        == "pending"
                    ):
                        report["research_pending"] += 1

                except Exception as exc:
                    report["errors"].append({
                        "stage": "hellominds_or_persistence",
                        "identity": identity,
                        "error": str(exc),
                    })

            # Keep the existing deterministic qualification
            # threshold and explicit content-need requirement.
            eligible = (
                item.score >= threshold
                and item.qualified
            )

            if eligible:
                report["qualified"] += 1

            evidence_ready = bool(
                assessment
                and assessment["evidence_accepted"] > 0
            )

            # When Minds is enabled, do not prepare a new
            # outreach draft unless research has completed
            # and the normal evidence requirements are met.
            if eligible and (
                not s.minds_enabled
                or (
                    research_completed
                    and evidence_ready
                    and not store
                )
            ):
                subject, message = create_draft(
                    item,
                    assessment=assessment,
                )

                if store:
                    store.save_draft(
                        identity,
                        subject,
                        message,
                    )

                save_draft(
                    pid,
                    subject,
                    message,
                )

                report["drafts"] += 1

            report["leads"].append({
                "id": pid,
                "business_name": item.business_name,
                "platform": item.platform,
                "source_url": item.source_url,
                "score": item.score,
                "qualified": eligible,
                "segment": item.segment,
                "subscription_fit": item.subscription_fit,
                "reasons": item.score_reasons,
                "compliance": compliance,
                "research_completed": research_completed,
                "draft_prepared": bool(
                    eligible
                    and (
                        not s.minds_enabled
                        or (
                            research_completed
                            and evidence_ready
                        )
                    )
                ),
            })

    audit(
        "agent_run",
        {
            "queries": queries,
            "platforms": platforms,
            "report_counts": {
                key: report[key]
                for key in (
                    "discovered",
                    "saved",
                    "qualified",
                    "drafts",
                    "researched",
                )
            },
        },
    )

    return report

